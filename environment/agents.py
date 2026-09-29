"""Multi-agent specialists (master prompt section 8).

Each agent has identity, purpose, capabilities, authorization
requirements, allowed tools, inputs, outputs, provenance, resource
limits, and stop conditions. Agents are pausable, resumable,
stoppable, inspectable, and redirectable: every run is a step
checkpoint record with a control flag consulted between steps.

Multi-model review (section 29): for important findings the review
pipeline is researcher -> independent reviewer -> falsification
reviewer -> evidence adjudicator. With no provider configured the
roles run LOCAL deterministic policies (reported honestly as
LOCAL - the system never pretends a model reviewed anything);
with a bound provider the role calls the OpenAI-compatible
endpoint. VERITAS controls state transitions either way - models
never vote to create truth."""
from __future__ import annotations

import json
import time
import urllib.request


# ------------------------------------------------------- agent registry

class AgentSpec(dict):
    @classmethod
    def make(cls, kind, purpose, allowed_tools,
             authorization=("experimental_execution",),
             inputs=(), outputs=(),
             resource_limits=None, stop_conditions=None):
        return cls(
            kind=kind, purpose=purpose,
            allowed_tools=list(allowed_tools),
            authorization_requirements=list(authorization),
            inputs=list(inputs), outputs=list(outputs),
            resource_limits=resource_limits or
            {"max_steps": 40, "max_seconds": 600},
            stop_conditions=stop_conditions or
            ["max_steps exceeded", "stop requested",
             "scope exceeded"],
        )


SPECIALISTS = {
    "coordinator": AgentSpec.make(
        "coordinator",
        "understand the objective, verify scope, recall "
        "memory, and delegate (the task-level brain)",
        allowed_tools=("targets", "routing", "memory"),
        authorization=(),
        inputs=("objective",),
        outputs=("plan", "delegation")),
    "planner": AgentSpec.make(
        "planner",
        "produce an ordered, inspectable plan for a task",
        allowed_tools=("targets", "routing"),
        authorization=(),
        inputs=("objective",),
        outputs=("plan",)),
    "researcher": AgentSpec.make(
        "researcher",
        "search memory, evidence, and (authorized) the web",
        allowed_tools=("memory", "evidence", "browser"),
        authorization=("browser.read",
                      "browser.navigate"),
        inputs=("query",),
        outputs=("findings",)),
    "coding_agent": AgentSpec.make(
        "coding_agent",
        "inspect and modify authorized files, run tests",
        allowed_tools=("workspace", "terminal"),
        authorization=("filesystem.read",
                      "filesystem.write",
                      "terminal.execute"),
        inputs=("path", "content", "run_tests"),
        outputs=("patch", "test_result")),
    "terminal_agent": AgentSpec.make(
        "terminal_agent",
        "execute authorized commands with live streaming "
        "and checkpointed observation",
        allowed_tools=("terminal",),
        authorization=("terminal.execute",),
        inputs=("shell", "command", "workdir"),
        outputs=("command_output",)),
    "browser_agent": AgentSpec.make(
        "browser_agent",
        "navigate, extract, and record web research within "
        "authorization",
        allowed_tools=("browser",),
        authorization=("browser.read",
                      "browser.navigate"),
        inputs=("url",),
        outputs=("extraction",)),
    "security_researcher": AgentSpec.make(
        "security_researcher",
        "run the VERITAS research loop on a target through "
        "the engine adapters",
        allowed_tools=("targets", "engines", "evidence"),
        authorization=("research.execute",),
        inputs=("target_id", "vulnerability_class"),
        outputs=("disposition",)),
    "recovery_agent": AgentSpec.make(
        "recovery_agent",
        "resume interrupted/recovering tasks from their "
        "last checkpoint",
        allowed_tools=("tasks",),
        authorization=(),
        inputs=("task_id",),
        outputs=("resumed",)),
    "hypothesis_generator": AgentSpec.make(
        "hypothesis_generator",
        "generate falsifiable hypotheses from a target's "
        "research plan (section 19 questions)",
        allowed_tools=("targets",),
        authorization=(),
        inputs=("target_id",),
        outputs=("hypothesis",)),
    "experiment_designer": AgentSpec.make(
        "experiment_designer",
        "rank experiments and design the minimal-impact plan "
        "(engine, template, controls, capabilities)",
        allowed_tools=("targets", "routing"),
        authorization=(),
        inputs=("hypothesis",),
        outputs=("experiment_plan",)),
    "hypothesis_challenger": AgentSpec.make(
        "hypothesis_challenger",
        "attack the hypothesis: enumerate alternate/"
        "environmental/tooling explanations and demand the "
        "falsifiers for each",
        allowed_tools=(),
        authorization=(),
        inputs=("hypothesis", "evidence"),
        outputs=("challenge_list",)),
    "evidence_reviewer": AgentSpec.make(
        "evidence_reviewer",
        "audit the evidence objects against the five-state "
        "matrix (PROVEN/CORROBORATED/INFERRED)",
        allowed_tools=("evidence",),
        authorization=(),
        inputs=("experiment",),
        outputs=("evidence_matrix",)),
    "reproduction_agent": AgentSpec.make(
        "reproduction_agent",
        "independently reproduce the experiment result and "
        "characterize variance",
        allowed_tools=("engines",),
        authorization=("research.execute",),
        inputs=("experiment",),
        outputs=("reproduction_record",)),
    "report_writer": AgentSpec.make(
        "report_writer",
        "produce the full disclosure-grade report; never "
        "exaggerate impact; list what was NOT demonstrated",
        allowed_tools=("journal",),
        authorization=(),
        inputs=("experiment", "review_pipeline"),
        outputs=("report",)),
    "artifact_analyst": AgentSpec.make(
        "artifact_analyst",
        "inventory and verify research artifacts (hashes, "
        "provenance)",
        allowed_tools=("workspace", "artifacts"),
        authorization=("filesystem.read",),
        inputs=("artifacts",),
        outputs=("artifact_inventory",)),
    "firmware_analyst": AgentSpec.make(
        "firmware_analyst",
        "route firmware/kernel questions to HYDRA; keep all "
        "output STATIC_CANDIDATE",
        allowed_tools=("hydra",),
        authorization=("filesystem.execute",
                       "research.execute"),
        inputs=("kernelcache_artifact",),
        outputs=("static_candidates",)),
    "network_researcher": AgentSpec.make(
        "network_researcher",
        "route authorized endpoint/protocol experiments to "
        "SEEK within exact scope",
        allowed_tools=("seek",),
        authorization=("network.request",
                       "research.execute"),
        inputs=("authorized_scope",),
        outputs=("observation",)),
    "fuzzing_researcher": AgentSpec.make(
        "fuzzing_researcher",
        "route fuzzing/invariant experiments to CIDER",
        allowed_tools=("cider",),
        authorization=("research.execute",),
        inputs=("hypothesis",),
        outputs=("engine_result",)),
    "method_researcher": AgentSpec.make(
        "method_researcher",
        "route method-invention requests to Frontier when "
        "existing methods are insufficient",
        allowed_tools=("frontier",),
        authorization=("research.execute",),
        inputs=("method_question",),
        outputs=("method_result",)),
}

REVIEW_PIPELINE = ("researcher", "independent_reviewer",
                   "falsification_reviewer",
                   "evidence_adjudicator")


# ------------------------------------------------------- agent runs

class AgentRun:
    """One inspectable, controllable specialist execution."""

    def __init__(self, agent_kind, task, journal=None,
                 run_id=None, task_id=None,
                 model_route=None):
        self.spec = SPECIALISTS[agent_kind]
        self.agent_kind = agent_kind
        self.task = task
        self.journal = journal
        self.run_id = run_id or \
            f"run-{agent_kind[:3]}-{int(time.time() *
                                        1000) % 10**9:09d}"
        self.task_id = task_id
        self.model_route = model_route or {
            "mode": "LOCAL"}
        self.steps: list[dict] = []
        self.state = "READY"    # READY/RUNNING/PAUSED/DONE/
                                # FAILED/STOPPED
        self._control = "run"
        self.started = None
        self.result = None

    # -- control surface (pausable/resumable/stoppable)
    def pause(self):
        self._control = "pause"

    def resume(self):
        if self.state == "PAUSED":
            self._control = "run"
            self.state = "RUNNING"

    def stop(self):
        self._control = "stop"

    def redirect(self, new_task):
        self.task = new_task
        self._step("redirected", detail=new_task)

    def _step(self, action, detail=None, **fields):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                   time.gmtime()),
               "agent": self.agent_kind, "step": action}
        if detail is not None:
            rec["detail"] = str(detail)[:200]
        rec.update(fields)
        self.steps.append(rec)
        if self.journal:
            self.journal.append("agent_step", **rec)

    def checkpoint(self):
        """Consult the control flag between steps; records a
        real checkpoint entry."""
        self._step("checkpoint")
        if self._control == "stop":
            self.state = "STOPPED"
            raise _AgentStopped()
        if self._control == "pause":
            self.state = "PAUSED"
            raise _AgentPaused()
        limits = self.spec["resource_limits"]
        if len(self.steps) >= limits["max_steps"]:
            self.state = "STOPPED"
            raise _AgentStopped("max_steps exceeded")

    def inspect(self) -> dict:
        return {"run_id": self.run_id,
                "agent": self.agent_kind,
                "purpose": self.spec["purpose"],
                "state": self.state,
                "steps": self.steps,
                "task": self.task,
                "task_id": self.task_id,
                "model_route": self.model_route,
                "checkpoints": [s for s in self.steps
                                if s.get("step") ==
                                "checkpoint"],
                "result": self.result}


class _AgentStopped(Exception):
    pass


class _AgentPaused(Exception):
    pass


# ------------------------------------------------------- LOCAL policies

def _local_challenges(hypothesis: dict) -> list[dict]:
    """The falsifier checklist (section 22) as deterministic
    challenges - every alternate explanation class gets an
    explicit falsifier demand."""
    classes = (
        "negative control missing",
        "environmental explanation",
        "tooling artifact",
        "timing explanation",
        "cache/reuse explanation",
        "version-specific explanation",
        "parser ambiguity",
        "ambient-activity attribution (differential control)",
    )
    return [{"class": c,
             "demanded_evidence":
                 "a recorded control or measurement that "
                 "eliminates this explanation"}
            for c in classes]


def _local_evidence_matrix(experiment: dict) -> dict:
    """Five-state partition of an experiment record (the SEEK
    discipline absorbed in VERITAS wave 5)."""
    ev = experiment.get("evidence") or []
    controls = experiment.get("negative_controls_pass")
    reproduced = experiment.get("reproduced")
    proven = len(ev) + (1 if controls else 0) + \
        (1 if reproduced else 0)
    return {
        "PROVEN": min(proven, 4),
        "CORROBORATED": 1 if reproduced else 0,
        "INFERRED": 1,
        "UNTESTED": 0 if ev else 1,
    }


# ------------------------------------------------------- model routing

class ModelRoleRouter:
    """Role -> provider binding with an honest LOCAL fallback."""

    def __init__(self, provider_store):
        self.store = provider_store

    def call(self, role: str, prompt: str,
             payload: dict) -> dict:
        if self.store is None:
            return {"role": role, "mode": "LOCAL",
                    "verdict": None,
                    "note": "no provider store; LOCAL "
                            "deterministic policy applied"}
        binding = self.store.config["role_bindings"].get(role)
        if binding is None:
            return {"role": role, "mode": "LOCAL",
                    "verdict": None,
                    "note": "no provider bound; LOCAL "
                            "deterministic policy applied"}
        provider = self.store.config["providers"].get(
            binding["provider"])
        key = self.store.get_api_key(binding["provider"])
        if provider is None or key is None:
            return {"role": role, "mode": "LOCAL",
                    "verdict": None,
                    "note": "provider configured but key "
                            "missing; LOCAL policy applied"}
        body = json.dumps({
            "model": binding["model_id"],
            "messages": [
                {"role": "system",
                 "content": "You are the %s in a security-"
                             "research review pipeline. Respond "
                             "with strict JSON: {verdict, "
                             "claims, counterarguments, "
                             "missing_evidence, "
                             "next_experiment}." % role},
                {"role": "user",
                 "content": prompt + "\n\n" +
                            json.dumps(payload)[:8000]},
            ],
        }).encode()
        req = urllib.request.Request(
            provider["base_url"] + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read().decode())
            return {"role": role, "mode": "remote",
                    "verdict": resp["choices"][0][
                        "message"]["content"]}
        except Exception as e:
            return {"role": role, "mode": "LOCAL",
                    "verdict": None,
                    "note": f"provider call failed ({e!r}); "
                            "LOCAL policy applied"}


# ------------------------------------------------------- review pipeline

class ReviewPipeline:
    """researcher -> independent reviewer -> falsification
    reviewer -> evidence adjudicator. VERITAS controls the state
    transition: the adjudicator's disposition is computed from
    the recorded gates, never from a model vote."""

    def __init__(self, provider_store, journal=None):
        self.router = ModelRoleRouter(provider_store)
        self.journal = journal

    def run(self, experiment: dict) -> dict:
        out = {"pipeline": list(REVIEW_PIPELINE),
               "stages": []}
        hyp = {"claim": experiment.get("summary", ""),
               "gates": {
                   "controls": experiment.get(
                       "negative_controls_pass"),
                   "reproduced": experiment.get("reproduced")}}
        # 1. researcher: state the claim
        s1 = self.router.call("researcher",
                              "State the research claim and "
                              "its evidence.", hyp)
        # 2. independent reviewer (LOCAL policy: structural
        #    evidence audit)
        matrix = _local_evidence_matrix(experiment)
        remote2 = self.router.call(
            "independent_reviewer",
            "Audit the evidence independently.", matrix)
        # 3. falsification reviewer (LOCAL policy: the
        #    challenge checklist)
        challenges = _local_challenges(hyp)
        remote3 = self.router.call(
            "falsification_reviewer",
            "Attack the claim with alternate explanations.",
            {"claim": hyp["claim"],
             "challenges": challenges})
        # 4. evidence adjudicator: VERITAS decides from gates
        controls = bool(experiment.get(
            "negative_controls_pass"))
        reproduced = bool(experiment.get("reproduced"))
        evidence = bool(experiment.get("evidence"))
        if evidence and controls and reproduced:
            verdict = "SUPPORTED"
        elif not evidence:
            verdict = "INCONCLUSIVE"
        elif experiment.get("disposition") == "BLOCKED":
            verdict = "BLOCKED"
        else:
            verdict = "INCONCLUSIVE"
        out["stages"] = [
            {"role": "researcher", "mode": s1["mode"],
             "note": s1.get("note")},
            {"role": "independent_reviewer",
             "mode": remote2["mode"],
             "evidence_matrix": matrix,
             "note": remote2.get("note")},
            {"role": "falsification_reviewer",
             "mode": remote3["mode"],
             "challenge_classes": [c["class"] for c in
                                   challenges],
             "note": remote3.get("note")},
            {"role": "evidence_adjudicator",
             "mode": "LOCAL-VERITAS",
             "verdict": verdict,
             "basis": "recorded gates: evidence=%s "
                      "controls=%s reproduced=%s"
                      % (evidence, controls, reproduced)},
        ]
        out["verdict"] = verdict
        if self.journal:
            self.journal.append("review_pipeline", **{
                "stages": [
                    {"role": s["role"], "mode": s["mode"]}
                    for s in out["stages"]],
                "verdict": verdict})
        return out


def review_report_notes(pipeline: dict) -> list:
    """What the pipeline recorded for the report's limitations
    and falsification sections."""
    fals = next(s for s in pipeline["stages"]
                if s["role"] == "falsification_reviewer")
    return fals.get("challenge_classes", [])
