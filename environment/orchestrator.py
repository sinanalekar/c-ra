"""Research orchestrator: the coordinator implementing the core
loop (master prompt section 2):

target -> hypothesis -> experiment design -> controlled execution
-> observation -> negative controls -> falsification ->
reproduction -> evidence grading -> disposition

VERITAS controls every state transition. A successful original
experiment without serious falsification is NOT a validated
finding; dispositions are SUPPORTED / REFUTED / INCONCLUSIVE /
BLOCKED until every gate passes.

The multi-agent specialists (section 8) run as inspectable
AgentRuns: hypothesis generation, experiment design, review
pipeline, and report writing are checkpointed agent steps in the
journal's activity stream."""
from __future__ import annotations

import time

from .agents import (AgentRun, ReviewPipeline,
                     _local_challenges)
from .reports import generate_report
from .routing import route as route_target


HYPOTHESIS_STATES = (
    "PROPOSED", "REGISTERED", "TESTING", "SUPPORTED", "REFUTED",
    "INCONCLUSIVE", "SUPERSEDED", "VALIDATED",
)


class Orchestrator:
    def __init__(self, config, registry, permissions,
                 journal, targets, provider_store=None):
        self.config = config
        self.registry = registry
        self.permissions = permissions
        self.journal = journal
        self.targets = targets
        self.provider_store = provider_store
        self.review = ReviewPipeline(provider_store, journal) \
            if provider_store else ReviewPipeline(None, journal)
        self.agent_runs: dict[str, dict] = {}
        self.hypotheses: dict[str, dict] = {}
        self.experiments: dict[str, dict] = {}
        self.reports: dict[str, dict] = {}
        self._seq = 0
        self.journal.append(
            "research_session_started",
            engines=[e["name"] for e in
                     self.registry.describe_all()
                     if e["available"]])

    # ------------------------------------------------ hypothesis
    def register_hypothesis(self, claim: str, target_id: str,
                            engine: str,
                            falsification: str = "",
                            params: dict | None = None) -> dict:
        self._seq += 1
        hid = f"EH-{self._seq:04d}"
        rec = {
            "hypothesis_id": hid,
            "target": target_id,
            "claim": claim,
            "engine": engine,
            "null_hypothesis":
                "the observed behavior has an environmental, "
                "tooling, or benign explanation",
            "falsification_conditions": falsification or
                "negative controls reproduce the observation; "
                "or the result fails independent reproduction",
            "params": params or {},
            "state": "REGISTERED",
            "registered_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.hypotheses[hid] = rec
        self.journal.append("hypothesis_registered", **{
            "hypothesis_id": hid, "claim": claim,
            "target": target_id, "engine": engine})
        return rec

    # ------------------------------------------------ experiment
    def run_experiment(self, hypothesis_id: str,
                       params: dict | None = None) -> dict:
        hyp = self.hypotheses.get(hypothesis_id)
        if hyp is None:
            return {"error": "unknown hypothesis"}
        engine = self.registry.get(hyp["engine"])
        if not engine.available():
            self.journal.append(
                "engine_unavailable", engine=hyp["engine"])
            return {
                "hypothesis_id": hypothesis_id,
                "disposition": "BLOCKED",
                "reason": f"engine {hyp['engine']} unavailable",
            }
        # authorization gate: identify target -> verify scope ->
        # verify capability (deny by default; insufficient
        # authorization is a recorded BLOCKED disposition -
        # master prompt section 25)
        for cap in engine.authorization_requirements:
            if not self.permissions.check(cap,
                                         scope=hyp["target"]):
                self.journal.append(
                    "authorization_denied",
                    capability=cap, scope=hyp["target"],
                    experiment_blocked=True)
                hyp["state"] = "INCONCLUSIVE"
                return {
                    "hypothesis_id": hypothesis_id,
                    "disposition": "BLOCKED",
                    "reason": "insufficient authorization: "
                              f"{cap} (scope {hyp['target']})",
                }
        self._seq += 1
        exp_id = f"EX-{self._seq:04d}"
        hyp["state"] = "TESTING"
        self.journal.append(
            "experiment_started", experiment_id=exp_id,
            hypothesis_id=hypothesis_id,
            engine=engine.name, target=hyp["target"])
        ctx = {"granted": [
            c for c in engine.authorization_requirements
            if self.permissions.check(c)]}
        result = engine.execute(
            exp_id, hyp, params or hyp["params"], ctx)

        # negative-control gate
        controls_pass = all(
            c.get("passed", False)
            for c in result.controls) if result.controls \
            else False

        # falsification gate: independent reproduction
        repro = engine.reproduce(exp_id, {
            "params": params or hyp["params"], **ctx})
        reproduced = (
            repro.disposition == result.disposition
            and result.disposition in
            ("SUPPORTED", "REFUTED"))

        disposition = result.disposition
        reason = result.summary
        if disposition == "SUPPORTED" and not controls_pass:
            disposition = "INCONCLUSIVE"
            reason = "negative controls missing or failed"
        elif disposition == "SUPPORTED" and not reproduced:
            disposition = "INCONCLUSIVE"
            reason = "not reproduced independently"
        elif disposition == "SUPPORTED":
            reason = "controls + reproduction passed"
        rec = {
            "experiment_id": exp_id,
            "hypothesis_id": hypothesis_id,
            "engine": engine.name,
            "target": hyp["target"],
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                time.gmtime()),
            "result": result.as_dict(),
            "reproduction": repro.as_dict(),
            "negative_controls_pass": controls_pass,
            "reproduced": reproduced,
            "disposition": disposition,
            "evidence": result.evidence,
        }
        self.experiments[exp_id] = rec
        hyp["state"] = {
            "SUPPORTED": "SUPPORTED",
            "REFUTED": "REFUTED",
            "INCONCLUSIVE": "INCONCLUSIVE",
            "BLOCKED": "REFUTED",
        }.get(disposition, "INCONCLUSIVE")
        self.journal.append(
            "experiment_completed",
            experiment_id=exp_id,
            hypothesis_id=hypothesis_id,
            engine=engine.name,
            disposition=disposition,
            controls_pass=controls_pass,
            reproduced=reproduced,
            reason=reason if disposition != "BLOCKED"
            else result.summary)
        self.targets.record_experiment(hyp["target"], {
            "ts": rec["ts"],
            "experiment_id": exp_id,
            "has_negative_control": controls_pass,
            "reproduced": reproduced,
            "evidence": bool(result.evidence),
        })
        return rec

    # ------------------------------------------------ agents
    def run_agent(self, kind: str, task: dict) -> dict:
        """Run a specialist agent as an inspectable, checkpointed
        AgentRun. The LOCAL policies do the deterministic work;
        model roles layer on top when providers are bound."""
        from .agents import SPECIALISTS
        if kind not in SPECIALISTS:
            failed = {"agent": kind, "state": "FAILED",
                      "steps": [], "task": task,
                      "result": {
                          "error": "unknown agent kind"}}
            if self.journal:
                self.journal.append(
                    "agent_failed", agent=kind,
                    reason="unknown agent kind")
            return failed
        run = AgentRun(kind, task, self.journal)
        self.agent_runs[run.agent_kind + "-" +
                        str(len(self.agent_runs))] = \
            {"run": run}
        try:
            run.state = "RUNNING"
            run.started = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            if kind == "hypothesis_generator":
                target = self.targets.get(
                    task.get("target_id", ""))
                if target is None:
                    raise ValueError("unknown target")
                run._step("design_questions_loaded",
                          detail=route_target(dict(
                              target))[
                              "design_questions"])
                run.checkpoint()
                r = route_target(dict(target))
                claim = (
                    "On %s (%s), the %s surface violates %s "
                    "under %s experiments (%s template), "
                    "detectable with the repaired control "
                    "staying clean"
                    % (target["product"],
                       target["parent_category"],
                       r["design_questions"][
                           "1_attack_surface"],
                       task.get("vulnerability_class",
                                "its security property"),
                       r["chosen"]["engine"],
                       r["chosen"]["template"]))
                run._step("hypothesis_drafted", detail=claim)
                run.checkpoint()
                run.result = {"claim": claim,
                              "engine": r["chosen"]["engine"],
                              "params": {
                                  "template":
                                      r["chosen"][
                                          "template"]}}
            elif kind == "experiment_designer":
                target = self.targets.get(
                    task.get("target_id", ""))
                r = route_target(dict(target),
                                 task.get(
                                     "vulnerability_class", ""))
                run._step("experiments_ranked",
                          detail=[e["template"] for e in
                                  r["ranked_experiments"]])
                run.checkpoint()
                run.result = r
            elif kind == "hypothesis_challenger":
                challenges = _local_challenges(task)
                run._step("challenge_classes_enumerated",
                          detail=[c["class"] for c in
                                  challenges])
                run.checkpoint()
                run.result = {"challenges": challenges}
            elif kind == "evidence_reviewer":
                exp = self.experiments.get(
                    task.get("experiment_id", ""), {})
                matrix = self.review.run(exp) if exp else {}
                run._step("review_pipeline_ran",
                          detail=matrix.get("verdict"))
                run.checkpoint()
                run.result = matrix
            elif kind == "report_writer":
                rec = self.generate_report(
                    task.get("experiment_id", ""))
                run._step("report_generated",
                          detail=rec and rec.get("sha256"))
                run.checkpoint()
                run.result = rec
            else:
                raise ValueError(
                    f"unknown agent kind {kind!r}")
            run.state = "DONE"
        except Exception as e:
            run.state = "FAILED"
            run.result = {"error": repr(e)}
        return run.inspect()

    def agent_status(self) -> list:
        return [{"agent": k,
                 "state": v["run"].state,
                 "steps": len(v["run"].steps)}
                for k, v in self.agent_runs.items()]

    # ------------------------------------------------ reports
    def generate_report(self, experiment_id: str) -> dict:
        exp = self.experiments.get(experiment_id)
        if exp is None:
            return {"error": "unknown experiment"}
        hyp = self.hypotheses.get(
            exp["hypothesis_id"], {})
        target = self.targets.get(exp["target"]) or {}
        pipeline = self.review.run(exp)
        entries = self.journal.entries()
        report = generate_report(
            exp, hyp, dict(target), pipeline, entries)
        self.reports[experiment_id] = report
        self.journal.append(
            "report_generated",
            experiment_id=experiment_id,
            sha256=report["sha256"],
            disposition=report["disposition"])
        return report

    # ------------------------------------------------ status
    def status(self) -> dict:
        return {
            "hypotheses": [
                {"id": h, "state": r["state"],
                 "claim": r["claim"]}
                for h, r in self.hypotheses.items()],
            "experiments": [
                {"id": x, "disposition": r["disposition"],
                 "engine": r["engine"]}
                for x, r in self.experiments.items()],
            "engines": self.registry.describe_all(),
            "agents": self.agent_status(),
            "reports": [
                {"experiment_id": k,
                 "sha256": v["sha256"],
                 "disposition": v["disposition"]}
                for k, v in self.reports.items()],
            "coverage": self.targets.coverage_report(),
        }
