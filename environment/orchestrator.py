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
                 journal, targets, provider_store=None,
                 runtimes=None):
        self.config = config
        self.registry = registry
        self.permissions = permissions
        self.journal = journal
        self.targets = targets
        self.provider_store = provider_store
        self.runtimes = runtimes or {}
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
    def run_agent(self, kind: str, task: dict,
                  parent_task_id: str | None = None,
                  model_override: dict | None = None) -> dict:
        """Run a specialist agent as an inspectable, checkpointed
        AgentRun with a stable run_id and real controls. The
        LOCAL policies do the deterministic work; bound model
        roles layer on top (resolve_role honors per-task
        overrides)."""
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
        role_route = {"mode": "LOCAL"}
        if self.provider_store is not None:
            role_route = \
                self.provider_store.resolve_role(
                    kind if kind in
                    ("coordinator", "planner",
                     "coding_agent", "researcher",
                     "browser_agent", "terminal_agent",
                     "evidence_reviewer", "report_writer",
                     "security_researcher") else
                    "coordinator", model_override)
        run = AgentRun(kind, task, self.journal,
                       task_id=parent_task_id,
                       model_route=role_route)
        self.agent_runs[run.run_id] = {"run": run}
        try:
            run.state = "RUNNING"
            run.started = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._execute_agent(run, kind, task)
            run.state = "DONE"
        except Exception as e:
            run.state = "FAILED"
            run.result = {"error": repr(e)}
        if parent_task_id:
            self._task_event(parent_task_id, "agent_done",
                             kind,
                             run_id=run.run_id,
                             state=run.state)
        return run.inspect()

    def _execute_agent(self, run, kind, task):
        """The real per-agent executions. Every advertised
        specialist has one - none are config-only."""
        if kind == "hypothesis_generator":
            target = self.targets.get(
                task.get("target_id", ""))
            if target is None:
                raise ValueError("unknown target")
            r = route_target(dict(target))
            run._step("design_questions_loaded",
                      detail=r["design_questions"])
            run.checkpoint()
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
                                  r["chosen"]["template"]}}
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
        elif kind == "coordinator":
            objective = task.get("objective", "")
            mem = self.runtimes.get("memory")
            recalled = mem.recall(objective, limit=5) \
                if mem else []
            plan = [
                "understand: " + objective[:120],
                "authorize: verify capabilities for the "
                "workspace in scope",
                "inspect: workspace tree + git status",
                "plan: decompose into specialist steps",
                "execute: delegate (coding/terminal/"
                "browser/research specialists)",
                "verify: run available checks",
                "report: artifacts + summary",
            ]
            run._step("memory_recalled",
                      detail=[r["text"][:60]
                              for r in recalled])
            run.checkpoint()
            run._step("plan_sketched",
                      detail=plan)
            run.checkpoint()
            run.result = {"plan": plan,
                         "recalled": len(recalled)}
        elif kind == "planner":
            objective = task.get("objective", "")
            plan = [
                {"step": 1, "action": "inspect workspace",
                 "tool": "workspace"},
                {"step": 2, "action": "git status",
                 "tool": "git"},
                {"step": 3, "action": "route research",
                 "tool": "routing"},
                {"step": 4, "action": "delegate to "
                 "specialists", "tool": "agents"},
                {"step": 5, "action": "verify + report",
                 "tool": "reports"},
            ]
            run._step("plan_produced",
                      detail=[p["action"]
                              for p in plan])
            run.checkpoint()
            run.result = {"plan": plan,
                          "objective": objective}
        elif kind == "researcher":
            query = task.get("query", "")
            mem = self.runtimes.get("memory")
            ev = self.runtimes.get("evidence")
            findings = {
                "memory": [r["text"][:200]
                           for r in (mem.recall(
                               query, limit=5)
                               if mem else [])],
                "evidence": [r["observation"][:200]
                             for r in (ev.list(limit=5)
                                       if ev else [])],
            }
            run._step("local_sources_searched",
                      detail=list(findings))
            run.checkpoint()
            browser = self.runtimes.get("browser")
            if browser and task.get("url"):
                sess = browser.open_session()
                nav = browser.navigate(
                    sess["session_id"], task["url"])
                if "error" not in nav:
                    ext = browser.extract(
                        sess["session_id"])
                    findings["web"] = {
                        "title": ext.get("title"),
                        "text_head": ext.get(
                            "text", "")[:400]}
                    run._step("web_source_extracted",
                              detail=ext.get("title"))
                else:
                    findings["web"] = \
                        {"error": nav.get("error")}
                    run._step("web_source_failed",
                              detail=nav.get("error"))
                run.checkpoint()
            run.result = {"findings": findings}
        elif kind == "coding_agent":
            ws = self.runtimes.get("workspace")
            if ws is None:
                raise RuntimeError(
                    "workspace runtime unavailable")
            path = task.get("path", "")
            content = task.get("content", "")
            old = ws.read(path)
            before = old.get("content")
            run._step("file_inspected",
                      detail=path,
                      bytes=len(before or ""))
            run.checkpoint()
            w = ws.write(path, content)
            run._step("file_written",
                      detail=path, sha=w.get("sha256"))
            run.checkpoint()
            art = self.runtimes.get("artifacts")
            if art:
                art.record("code", content,
                           task_id=run.task_id,
                           run_id=run.run_id,
                           agent="coding_agent",
                           meta={"path": path})
            test_result = None
            if task.get("run_tests"):
                term = self.runtimes.get("terminal")
                if term:
                    res = term.run_sync(
                        "python",
                        "-m unittest discover -s tests "
                        "-v",
                        workdir=task.get(
                            "workdir", "."),
                        timeout=180)
                    test_result = {
                        "exit_code": res.get(
                            "exit_code"),
                        "tail": (res.get("stdout", "") +
                                 res.get(
                                     "stderr", "")
                                 )[-600:]}
                    run._step("tests_ran",
                              detail=res.get(
                                  "exit_code"))
                    run.checkpoint()
            run.result = {
                "path": path, "written": True,
                "sha256": w.get("sha256"),
                "test_result": test_result}
        elif kind == "terminal_agent":
            term = self.runtimes.get("terminal")
            if term is None:
                raise RuntimeError(
                    "terminal runtime unavailable")
            shell = task.get("shell", "powershell")
            command = task.get("command", "")
            workdir = task.get("workdir", ".")
            timeout = int(task.get("timeout", 60))
            started = term.start(
                shell, command, workdir, timeout,
                confirm_dangerous=task.get(
                    "confirm_dangerous", False))
            if started.get("blocked"):
                run.result = {"blocked": started}
                return
            sid = started["session_id"]
            run.result = {"session_id": sid,
                          "state": "observing"}
            run._step("command_started",
                      detail=command[:200],
                      session=sid)
            # checkpointed observation loop: pause/stop of
            # this run REALLY stops the process (the run
            # result carries the session id from the start)
            deadline = time.time() + timeout
            while time.time() < deadline:
                run.checkpoint()
                s = term.get(sid)
                if s.get("state") in ("completed",
                                      "cancelled"):
                    break
                time.sleep(0.5)
            final = term.get(sid)
            run._step("command_finished",
                      detail="exit=%s" %
                             final.get("exit_code"))
            ev = self.runtimes.get("evidence")
            output = "$ %s\n%s\n%s" % (
                command, final.get("stdout", ""),
                final.get("stderr", ""))
            if ev:
                ev.record(
                    "command_output", output,
                    task_id=run.task_id,
                    source="terminal:" + sid,
                    confidence=0.9)
            art = self.runtimes.get("artifacts")
            if art:
                art.record(
                    "log", content=output,
                    task_id=run.task_id,
                    run_id=run.run_id,
                    agent="terminal_agent",
                    meta={"session_id": sid,
                          "exit_code":
                          final.get("exit_code")})
            run.result = {
                "session_id": sid,
                "exit_code": final.get("exit_code"),
                "stdout": final.get("stdout", "")[:5000],
                "stderr": final.get("stderr", "")[:2000],
                "timed_out": final.get("timed_out")}
        elif kind == "browser_agent":
            browser = self.runtimes.get("browser")
            if browser is None:
                raise RuntimeError(
                    "browser runtime unavailable")
            url = task.get("url", "")
            sess = browser.open_session()
            nav = browser.navigate(
                sess["session_id"], url)
            run._step("navigated",
                      detail=nav.get("title") or
                      nav.get("error", ""))
            run.checkpoint()
            if "error" not in nav:
                ext = browser.extract(
                    sess["session_id"])
                run._step("extracted",
                          detail=ext.get("title"))
                run.checkpoint()
                ev = self.runtimes.get("evidence")
                if ev:
                    ev.record(
                        "source_document",
                        ext.get("text", "")[:5000],
                        task_id=run.task_id,
                        source=url,
                        confidence=0.8)
                art = self.runtimes.get("artifacts")
                if art:
                    art.record(
                        "note",
                        ext.get("text", "")[:20000],
                        task_id=run.task_id,
                        run_id=run.run_id,
                        agent="browser_agent",
                        meta={"url": url})
                run.result = {
                    "url": nav.get("url"),
                    "title": ext.get("title"),
                    "text_head": ext.get("text",
                                         "")[:1000],
                    "links": len(ext.get(
                        "links", []))}
            else:
                run.result = {"error": nav.get("error")}
        elif kind == "security_researcher":
            target = self.targets.get(
                task.get("target_id", ""))
            if target is None:
                raise ValueError("unknown target")
            r = route_target(
                dict(target),
                task.get("vulnerability_class", ""))
            run._step("route_chosen",
                      detail=r["chosen"])
            run.checkpoint()
            for cap in ("research.execute",):
                self.permissions.system.require(
                    cap, scope=target["target_id"])
            hyp = self.register_hypothesis(
                "On %s, %s experiments expose a "
                "violation of the target's security "
                "property (%s)"
                % (target["product"],
                   r["chosen"]["engine"],
                   task.get("vulnerability_class",
                            "generic")),
                target_id=target["target_id"],
                engine=r["chosen"]["engine"],
                params={})
            run._step("hypothesis_registered",
                      detail=hyp["hypothesis_id"])
            run.checkpoint()
            rec = self.run_experiment(
                hyp["hypothesis_id"])
            run._step("experiment_ran",
                      detail=rec.get("disposition"))
            run.checkpoint()
            run.result = {
                "hypothesis_id":
                    hyp["hypothesis_id"],
                "disposition":
                    rec.get("disposition"),
                "experiment_id":
                    rec.get("experiment_id")}
        elif kind == "recovery_agent":
            store = self.runtimes.get("tasks")
            if store is None:
                raise RuntimeError(
                    "task store unavailable")
            tid = task.get("task_id")
            t = store.get(tid) if tid else None
            if t is None:
                raise ValueError(
                    "unknown or missing task_id")
            if t.data["state"] != "recovering":
                raise ValueError(
                    "task is not in recovery "
                    "(state=%s)"
                    % t.data["state"])
            cp = (t.data["checkpoints"][-1]
                  if t.data["checkpoints"]
                  else None)
            t.transition("running",
                         "resumed by recovery agent")
            run._step("task_resumed",
                      detail=t.data["task_id"],
                      last_checkpoint=cp and
                      cp["label"])
            run.checkpoint()
            run.result = {"task_id": tid,
                          "resumed": True,
                          "last_checkpoint":
                          cp and cp["label"]}
        elif kind in ("firmware_analyst", "network_researcher",
                      "fuzzing_researcher",
                      "method_researcher",
                      "reproduction_agent",
                      "artifact_analyst"):
            # engine-backed specialists: route through the
            # engine registry with honest availability
            engine_name = {
                "firmware_analyst": "hydra",
                "network_researcher": "seek",
                "fuzzing_researcher": "cider",
                "method_researcher": "frontier",
            }.get(kind, "veritas")
            engine = self.registry.get(engine_name)
            run._step("engine_selected",
                      detail=engine_name,
                      available=engine.available())
            run.checkpoint()
            if not engine.available():
                run.result = {
                    "error": "engine %s unavailable"
                             % engine_name}
                return
            self.permissions.system.require(
                "engine." + engine_name)
            exp_id = "EX-agent-%s" % \
                engine_name
            res = engine.execute(
                exp_id, task, task, {})
            run._step("engine_executed",
                      detail=res.summary[:200])
            run.checkpoint()
            run.result = {
                "engine": engine_name,
                "disposition": res.disposition,
                "summary": res.summary,
                "evidence": res.evidence}
        else:
            raise ValueError(
                f"agent kind {kind!r} has no execution")

    # ------------------------------------------------ run controls
    def agent_run_get(self, run_id: str) -> dict | None:
        entry = self.agent_runs.get(run_id)
        return entry["run"].inspect() if entry else None

    def agent_run_pause(self, run_id: str) -> dict:
        entry = self.agent_runs.get(run_id)
        if entry is None:
            return {"error": "unknown run"}
        run = entry["run"]
        if run.state != "RUNNING":
            return {"run_id": run_id,
                    "state": run.state,
                    "note": "run not active; pause has no "
                            "effect (recorded honestly)"}
        run.pause()
        self.journal.append("agent_paused",
                            run_id=run_id)
        return {"run_id": run_id, "state": "PAUSED"}

    def agent_run_resume(self, run_id: str) -> dict:
        entry = self.agent_runs.get(run_id)
        if entry is None:
            return {"error": "unknown run"}
        run = entry["run"]
        if run.state != "PAUSED":
            return {"run_id": run_id,
                    "state": run.state,
                    "note": "run not paused"}
        run.resume()
        self.journal.append("agent_resumed",
                            run_id=run_id)
        return {"run_id": run_id, "state": "RUNNING"}

    def agent_run_stop(self, run_id: str) -> dict:
        entry = self.agent_runs.get(run_id)
        if entry is None:
            return {"error": "unknown run"}
        run = entry["run"]
        run.stop()
        # a terminal_agent run REALLY stops its process
        if run.agent_kind == "terminal_agent" and \
                run.result and \
                run.result.get("session_id"):
            term = self.runtimes.get("terminal")
            if term:
                term.stop(run.result["session_id"])
        self.journal.append("agent_stopped",
                            run_id=run_id)
        return {"run_id": run_id,
                "state": "STOPPED"}

    def agent_run_redirect(self, run_id: str,
                           new_task: dict) -> dict:
        entry = self.agent_runs.get(run_id)
        if entry is None:
            return {"error": "unknown run"}
        run = entry["run"]
        if run.state in ("DONE", "STOPPED", "FAILED"):
            return {"run_id": run_id,
                    "state": run.state,
                    "note": "run finished; redirect "
                            "requires a new run"}
        run.redirect(new_task)
        self.journal.append("agent_redirected",
                            run_id=run_id)
        return {"run_id": run_id, "redirected": True}

    def agent_run_events(self, run_id: str) -> dict:
        entry = self.agent_runs.get(run_id)
        if entry is None:
            return {"error": "unknown run"}
        return {"run_id": run_id,
                "events": entry["run"].steps}

    def agent_run_checkpoints(self, run_id: str) -> dict:
        entry = self.agent_runs.get(run_id)
        if entry is None:
            return {"error": "unknown run"}
        run = entry["run"]
        return {"run_id": run_id,
                "checkpoints": [s for s in run.steps
                                if s.get("step") ==
                                "checkpoint"]}

    def _task_event(self, task_id, kind, detail,
                    **fields):
        store = self.runtimes.get("tasks")
        t = store.get(task_id) if store else None
        if t is not None:
            t.event(kind, detail, **fields)

    def agent_status(self) -> list:
        return [{"run_id": r["run"].run_id,
                 "agent": r["run"].agent_kind,
                 "task_id": r["run"].task_id,
                 "state": r["run"].state,
                 "steps": len(r["run"].steps)}
                for r in self.agent_runs.values()]

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
