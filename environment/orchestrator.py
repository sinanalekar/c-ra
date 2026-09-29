"""Research orchestrator: the coordinator implementing the core
loop (master prompt section 2):

target -> hypothesis -> experiment design -> controlled execution
-> observation -> negative controls -> falsification ->
reproduction -> evidence grading -> disposition

VERITAS controls every state transition. A successful original
experiment without serious falsification is NOT a validated
finding; dispositions are SUPPORTED / REFUTED / INCONCLUSIVE /
BLOCKED until every gate passes."""
from __future__ import annotations

import time


HYPOTHESIS_STATES = (
    "PROPOSED", "REGISTERED", "TESTING", "SUPPORTED", "REFUTED",
    "INCONCLUSIVE", "SUPERSEDED", "VALIDATED",
)


class Orchestrator:
    def __init__(self, config, registry, permissions,
                 journal, targets):
        self.config = config
        self.registry = registry
        self.permissions = permissions
        self.journal = journal
        self.targets = targets
        self.hypotheses: dict[str, dict] = {}
        self.experiments: dict[str, dict] = {}
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
            "coverage": self.targets.coverage_report(),
        }
