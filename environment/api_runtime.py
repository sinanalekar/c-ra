"""Runtime API endpoints: tasks, terminal, git, browser,
computer, files, capabilities, memory, artifacts, evidence, and
agent run controls. Registered onto the FastAPI app by
app.create_app. Every sensitive operation flows through the
central capability system - no endpoint bypasses it."""
from __future__ import annotations

import json

from fastapi import HTTPException
from pydantic import BaseModel


# ------------------------------------------------ request models

class TaskCreate(BaseModel):
    objective: str
    workspace: str = "*"


class TaskRedirect(BaseModel):
    objective: str


class TerminalStart(BaseModel):
    shell: str
    command: str
    workdir: str = "."
    timeout: int = 120
    confirm_dangerous: bool = False


class GitOp(BaseModel):
    repo: str
    pathspec: str = ""


class GitAdd(BaseModel):
    repo: str
    paths: list


class GitCommit(BaseModel):
    repo: str
    message: str


class GitCheckout(BaseModel):
    repo: str
    ref: str


class GitRestore(BaseModel):
    repo: str
    paths: list


class GitPush(BaseModel):
    repo: str
    remote: str = "origin"
    branch: str = ""
    confirm: bool = False


class GitMerge(BaseModel):
    repo: str
    ref: str


class BrowserNavigate(BaseModel):
    url: str


class BrowserAction(BaseModel):
    action: str            # click | type | press | scroll
    selector: str = ""
    text: str = ""
    confirm: bool = False


class ComputerLaunch(BaseModel):
    app: str
    args: str = ""
    confirm: bool = False


class CapabilityGrant(BaseModel):
    capability: str
    mode: str = "allow_session"
    scope: str = "*"
    task_id: str | None = None


class MemoryWrite(BaseModel):
    kind: str
    text: str
    task_id: str | None = None
    key: str = ""


class MemoryQuery(BaseModel):
    query: str
    kind: str | None = None
    task_id: str | None = None
    limit: int = 10


class ArtifactRecord(BaseModel):
    type: str
    content: str = ""
    path: str | None = None
    task_id: str | None = None
    meta: dict = {}


class EvidenceRecord(BaseModel):
    type: str
    observation: str
    task_id: str | None = None
    source: str = ""
    confidence: float = 0.5


class ChatTurn(BaseModel):
    task_id: str
    text: str
    model: dict | None = None      # {"provider", "model_id"}
    set_task_model: bool = True


class ModelSelection(BaseModel):
    task_id: str | None = None   # path wins when provided
    model: dict | None = None    # null = LOCAL mode


class ProviderWithKey(BaseModel):
    spec: dict
    api_key: str = ""
    models: list = []              # model ids for the picker


class AgentRunRequest(BaseModel):
    kind: str
    task: dict
    task_id: str | None = None
    model_override: dict | None = None


class AgentRedirect(BaseModel):
    task: dict


def _auth_fail(e: Exception):
    raise HTTPException(403, str(e))


def register_runtime_endpoints(app, env):
    journal = env.journal
    orch = env.orchestrator

    # ================================================ chat
    from .chat import ChatEngine
    chat = ChatEngine(env)

    @app.post("/api/chat")
    def chat_turn(spec: ChatTurn):
        """One user message -> one turn: real tool execution +
        model-composed or LOCAL reply."""
        t = env.taskstore.get(spec.task_id)
        if t is None:
            raise HTTPException(404, "unknown task")
        if spec.set_task_model and spec.model is not None:
            t.data["model"] = spec.model
            env.taskstore._persist(t)
        out = chat.turn(spec.task_id, spec.text,
                        spec.model)
        if "error" in out:
            raise HTTPException(404, out["error"])
        return out

    @app.get("/api/chat/{task_id}/messages")
    def chat_messages(task_id: str):
        return {"task_id": task_id,
                "messages": chat.store.messages(
                    task_id)}

    @app.post("/api/tasks/{task_id}/model")
    def set_task_model(task_id: str,
                       spec: ModelSelection):
        t = env.taskstore.get(task_id)
        if t is None:
            raise HTTPException(404, "unknown task")
        t.data["model"] = spec.model
        env.taskstore._persist(t)
        journal.append("task_model_set",
                       task_id=task_id,
                       model=spec.model)
        return {"task_id": task_id,
                "model": spec.model}

    @app.get("/api/models/list")
    def models_list():
        """The model picker data: LOCAL + every configured
        provider's model ids + role bindings."""
        providers = []
        for name, spec in \
                env.providers.config[
                    "providers"].items():
            providers.append({
                "name": name,
                "base_url": spec["base_url"],
                "disabled": bool(
                    spec.get("disabled")),
                "has_key": bool(
                    env.providers.get_api_key(
                        name)),
                "models": spec.get("model_ids"
                                   ) or [],
            })
        return {
            "local_mode": True,
            "providers": providers,
            "role_bindings":
                env.providers.role_status(),
        }

    class ProviderTest(BaseModel):
        name: str

    @app.post("/api/providers/test")
    def provider_test(spec: ProviderTest):
        p = env.providers.config[
            "providers"].get(spec.name)
        if p is None:
            raise HTTPException(
                404, "unknown provider")
        key = env.providers.get_api_key(
            spec.name)
        if not key:
            return {"ok": False,
                    "reason": "no API key stored"}
        try:
            req = __import__(
                "urllib.request",
                fromlist=["x"]).Request(
                p["base_url"] + "/models",
                headers={
                    "Authorization":
                        "Bearer " + key})
            with __import__(
                    "urllib.request",
                    fromlist=["x"]).urlopen(
                        req, timeout=20) as r:
                data = json.loads(
                    r.read().decode())
            models = [m.get("id")
                      for m in data.get(
                          "data", [])
                      if isinstance(m, dict)]
            return {"ok": True,
                    "models": models[:200]}
        except Exception as e:
            return {"ok": False,
                    "reason": repr(e)[:200]}

    @app.post("/api/providers/with_key")
    def provider_with_key(spec: ProviderWithKey):
        """Add a provider with its API key: the key goes to
        the OS credential store immediately and is never
        persisted in any config file, journal, or log."""
        try:
            env.providers.add_provider(
                spec.spec)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if spec.api_key:
            if spec.spec.get("model_ids") is None:
                spec.spec["model_ids"] = \
                    spec.models
            rec = env.providers.store_api_key(
                spec.spec["name"], spec.api_key)
            if not rec.get("stored"):
                raise HTTPException(
                    400, rec.get("reason",
                                 "key storage "
                                 "refused"))
        # record the picker-visible model ids in the provider
        if spec.models:
            env.providers.config["providers"][
                spec.spec["name"]][
                "model_ids"] = spec.models
            env.providers._save()
        return {"provider": spec.spec["name"],
                "configured": True,
                "has_key": bool(
                    env.providers.get_api_key(
                        spec.spec["name"]))}

    # ================================================ tasks
    @app.post("/api/tasks")
    def task_create(spec: TaskCreate):
        t = env.taskstore.create(spec.objective,
                                 spec.workspace)
        t.event("task_created",
                objective=spec.objective)
        return t.as_dict()

    @app.get("/api/tasks")
    def task_list(limit: int = 100):
        return env.taskstore.list(limit)

    @app.get("/api/tasks/{task_id}")
    def task_get(task_id: str):
        t = env.taskstore.get(task_id)
        if t is None:
            raise HTTPException(404, "unknown task")
        return t.as_dict()

    @app.post("/api/tasks/{task_id}/pause")
    def task_pause(task_id: str):
        t = env.taskstore.get(task_id)
        if t is None:
            raise HTTPException(404, "unknown task")
        try:
            t.transition("paused", "paused by user")
            t.event("paused")
        except Exception as e:
            raise HTTPException(400, str(e))
        return {"task_id": task_id, "state": "paused"}

    @app.post("/api/tasks/{task_id}/resume")
    def task_resume(task_id: str):
        t = env.taskstore.get(task_id)
        if t is None:
            raise HTTPException(404, "unknown task")
        try:
            t.transition("running",
                         "resumed by user")
            t.event("resumed")
        except Exception as e:
            raise HTTPException(400, str(e))
        return {"task_id": task_id, "state": "running"}

    @app.post("/api/tasks/{task_id}/stop")
    def task_stop(task_id: str):
        t = env.taskstore.get(task_id)
        if t is None:
            raise HTTPException(404, "unknown task")
        try:
            t.transition("cancelled", "stopped by user")
            t.event("stopped")
        except Exception as e:
            raise HTTPException(400, str(e))
        return {"task_id": task_id,
                "state": "cancelled"}

    @app.post("/api/tasks/{task_id}/redirect")
    def task_redirect(task_id: str,
                      spec: TaskRedirect):
        t = env.taskstore.get(task_id)
        if t is None:
            raise HTTPException(404, "unknown task")
        t.data["objective"] = spec.objective
        t.event("redirected", objective=spec.objective)
        env.taskstore._persist(t)
        return {"task_id": task_id,
                "objective": spec.objective}

    @app.get("/api/tasks/{task_id}/events")
    def task_events(task_id: str):
        t = env.taskstore.get(task_id)
        if t is None:
            raise HTTPException(404, "unknown task")
        return {"task_id": task_id,
                "events": t.data["events"][-200:]}

    @app.get("/api/tasks/{task_id}/checkpoints")
    def task_checkpoints(task_id: str):
        t = env.taskstore.get(task_id)
        if t is None:
            raise HTTPException(404, "unknown task")
        return {"task_id": task_id,
                "checkpoints": t.data["checkpoints"]}

    @app.post("/api/tasks/{task_id}/agents")
    def task_run_agent(task_id: str,
                       spec: AgentRunRequest):
        t = env.taskstore.get(task_id)
        if t is None:
            raise HTTPException(404, "unknown task")
        # delegated work IS running work: transition the task
        # (queued -> running; planning -> running;
        #  paused -> running; recovering -> running)
        if t.data["state"] in ("queued", "planning",
                               "paused",
                               "recovering"):
            t.transition(
                "running",
                "agent work started: " + spec.kind)
        t.event("agent_started", spec.kind,
                agent=spec.kind)
        out = orch.run_agent(
            spec.kind, spec.task, parent_task_id=task_id,
            model_override=spec.model_override)
        if out.get("run_id"):
            t.data["agents"].append(out["run_id"])
            # a real task-level checkpoint of the delegated work
            t.checkpoint(
                "agent:" + spec.kind,
                {"run_id": out["run_id"],
                 "state": out["state"]})
            env.taskstore._persist(t)
        return out

    # ================================================ terminal
    @app.post("/api/terminal")
    def terminal_start(spec: TerminalStart):
        try:
            rec = env.terminal.start(
                spec.shell, spec.command, spec.workdir,
                spec.timeout,
                confirm_dangerous=
                spec.confirm_dangerous)
        except PermissionError as e:
            _auth_fail(e)
        except (RuntimeError, ValueError) as e:
            raise HTTPException(400, str(e))
        return rec

    @app.get("/api/terminal")
    def terminal_list(limit: int = 50):
        return env.terminal.list(limit)

    @app.get("/api/terminal/{session_id}")
    def terminal_get(session_id: str):
        rec = env.terminal.get(session_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    @app.post("/api/terminal/{session_id}/stop")
    def terminal_stop(session_id: str):
        rec = env.terminal.stop(session_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    # ================================================ git
    @app.post("/api/git/discover")
    def git_discover(op: GitOp):
        return env.git.discover(op.repo)

    @app.post("/api/git/status")
    def git_status(op: GitOp):
        try:
            return env.git.status(op.repo)
        except PermissionError as e:
            _auth_fail(e)

    @app.post("/api/git/diff")
    def git_diff(op: GitOp):
        try:
            return env.git.diff(op.repo,
                                pathspec=op.pathspec)
        except PermissionError as e:
            _auth_fail(e)

    @app.post("/api/git/log")
    def git_log(op: GitOp):
        try:
            return env.git.log(op.repo)
        except PermissionError as e:
            _auth_fail(e)

    @app.post("/api/git/branches")
    def git_branches(op: GitOp):
        try:
            return env.git.branches(op.repo)
        except PermissionError as e:
            _auth_fail(e)

    @app.post("/api/git/remotes")
    def git_remotes(op: GitOp):
        try:
            return env.git.remotes(op.repo)
        except PermissionError as e:
            _auth_fail(e)

    @app.post("/api/git/add")
    def git_add(op: GitAdd):
        try:
            return env.git.add(op.repo, op.paths)
        except PermissionError as e:
            _auth_fail(e)
        except RuntimeError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/git/commit")
    def git_commit(op: GitCommit):
        try:
            return env.git.commit(op.repo, op.message)
        except PermissionError as e:
            _auth_fail(e)
        except RuntimeError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/git/checkout")
    def git_checkout(op: GitCheckout):
        try:
            return env.git.checkout(op.repo, op.ref)
        except PermissionError as e:
            _auth_fail(e)
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/git/restore")
    def git_restore(op: GitRestore):
        try:
            return env.git.restore(op.repo, op.paths)
        except PermissionError as e:
            _auth_fail(e)
        except RuntimeError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/git/merge")
    def git_merge(op: GitMerge):
        try:
            return env.git.merge(op.repo, op.ref)
        except PermissionError as e:
            _auth_fail(e)

    @app.post("/api/git/pull")
    def git_pull(op: GitOp):
        try:
            return env.git.pull(op.repo)
        except PermissionError as e:
            _auth_fail(e)

    @app.post("/api/git/push")
    def git_push(op: GitPush):
        try:
            return env.git.push(op.repo, op.remote,
                                op.branch, op.confirm)
        except PermissionError as e:
            raise HTTPException(403, str(e))

    # ================================================ browser
    @app.get("/api/browser/status")
    def browser_status():
        return env.browser.capability_status()

    @app.post("/api/browser/sessions")
    def browser_open():
        return env.browser.open_session()

    @app.get("/api/browser/sessions/{session_id}")
    def browser_get(session_id: str):
        rec = env.browser.get(session_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    @app.post("/api/browser/sessions/{session_id}/navigate")
    def browser_navigate(session_id: str,
                         spec: BrowserNavigate):
        rec = env.browser.navigate(session_id,
                                   spec.url)
        if rec.get("error"):
            raise HTTPException(400, rec["error"])
        return rec

    @app.post(
        "/api/browser/sessions/{session_id}/extract")
    def browser_extract(session_id: str):
        rec = env.browser.extract(session_id)
        if rec.get("error"):
            raise HTTPException(400, rec["error"])
        return rec

    @app.post(
        "/api/browser/sessions/{session_id}/actions")
    def browser_action(session_id: str,
                       spec: BrowserAction):
        # real interaction when the playwright engine is
        # present; honest 501 otherwise
        rec = env.browser.interact(
            session_id, spec.action, spec.selector,
            spec.text, spec.confirm)
        if rec.get("error"):
            raise HTTPException(501, rec["error"])
        return rec

    # ================================================ computer
    @app.get("/api/computer/status")
    def computer_status():
        return env.computer.capability_status()

    @app.post("/api/computer/launch")
    def computer_launch(spec: ComputerLaunch):
        try:
            return env.computer.launch(
                spec.app, spec.args, spec.confirm)
        except PermissionError as e:
            _auth_fail(e)

    @app.get("/api/computer/processes")
    def computer_processes(name: str = ""):
        try:
            return env.computer.processes(name)
        except PermissionError as e:
            _auth_fail(e)

    # ============================================ capabilities
    @app.get("/api/permissions")
    def permissions_status():
        return env.capabilities.status()

    @app.post("/api/permissions/grant")
    def permissions_grant(spec: CapabilityGrant):
        try:
            return env.capabilities.grant(
                spec.capability, spec.mode, spec.scope,
                task_id=spec.task_id)
        except PermissionError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/permissions/revoke")
    def permissions_revoke(spec: CapabilityGrant):
        return env.capabilities.revoke(spec.capability)

    # ================================================ memory
    @app.post("/api/memory")
    def memory_write(spec: MemoryWrite):
        try:
            return env.memory.remember(
                spec.kind, spec.text, spec.task_id,
                spec.key)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/memory/recall")
    def memory_recall(spec: MemoryQuery):
        return {"results": env.memory.recall(
            spec.query, spec.kind, spec.task_id,
            spec.limit)}

    @app.get("/api/memory")
    def memory_inspect(kind: str | None = None):
        return env.memory.inspect(kind)

    @app.delete("/api/memory/{memory_id}")
    def memory_remove(memory_id: str):
        rec = env.memory.remove(memory_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    # ================================================ artifacts
    @app.get("/api/artifacts")
    def artifacts_list(type: str | None = None,
                       task_id: str | None = None,
                       limit: int = 100):
        return env.artifacts.list(type, task_id, limit)

    @app.post("/api/artifacts")
    def artifacts_record(spec: ArtifactRecord):
        try:
            return env.artifacts.record(
                spec.type, spec.content, spec.path,
                task_id=spec.task_id, meta=spec.meta)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/artifacts/{artifact_id}")
    def artifacts_get(artifact_id: str):
        rec = env.artifacts.read_content(artifact_id)
        if rec.get("error"):
            raise HTTPException(404, rec["error"])
        return rec

    # ================================================ evidence
    @app.get("/api/evidence")
    def evidence_list(task_id: str | None = None,
                      type: str | None = None,
                      limit: int = 100):
        return env.evidence.list(task_id, type, limit)

    @app.get("/api/evidence/stats")
    def evidence_stats():
        return env.evidence.stats()

    @app.post("/api/evidence")
    def evidence_record(spec: EvidenceRecord):
        try:
            return env.evidence.record(
                spec.type, spec.observation,
                spec.task_id, spec.source,
                spec.confidence)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/evidence/{evidence_id}/corroborate")
    def evidence_corroborate(evidence_id: str):
        rec = env.evidence.corroborate(evidence_id)
        if "error" in rec:
            raise HTTPException(400, rec["error"])
        return rec

    @app.post(
        "/api/evidence/{evidence_id}/mark_reproduced")
    def evidence_reproduced(evidence_id: str):
        rec = env.evidence.mark_reproduced(evidence_id)
        if "error" in rec:
            raise HTTPException(400, rec["error"])
        return rec

    # ================================================ agents
    @app.post("/api/agents/run")
    def agent_run(spec: AgentRunRequest):
        return orch.run_agent(
            spec.kind, spec.task,
            parent_task_id=spec.task_id,
            model_override=spec.model_override)

    @app.get("/api/agents")
    def agent_list():
        return orch.agent_status()

    @app.get("/api/agents/specs")
    def agent_specs():
        from .agents import SPECIALISTS
        return [dict(s) for s in
                SPECIALISTS.values()]

    @app.get("/api/agents/{run_id}")
    def agent_get(run_id: str):
        rec = orch.agent_run_get(run_id)
        if rec is None:
            raise HTTPException(404, "unknown run")
        return rec

    @app.post("/api/agents/{run_id}/pause")
    def agent_pause(run_id: str):
        rec = orch.agent_run_pause(run_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    @app.post("/api/agents/{run_id}/resume")
    def agent_resume(run_id: str):
        rec = orch.agent_run_resume(run_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    @app.post("/api/agents/{run_id}/stop")
    def agent_stop(run_id: str):
        rec = orch.agent_run_stop(run_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    @app.post("/api/agents/{run_id}/redirect")
    def agent_redirect(run_id: str,
                       spec: AgentRedirect):
        rec = orch.agent_run_redirect(run_id,
                                      spec.task)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    @app.get("/api/agents/{run_id}/events")
    def agent_events(run_id: str):
        rec = orch.agent_run_events(run_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    @app.get("/api/agents/{run_id}/checkpoints")
    def agent_checkpoints(run_id: str):
        rec = orch.agent_run_checkpoints(run_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    # ================================================ models
    @app.get("/api/models")
    def models_routes():
        routes = {}
        for role in ("coordinator", "planner",
                     "reasoning", "coding", "research",
                     "browser", "terminal", "reviewer",
                     "independent_reviewer",
                     "falsification_reviewer",
                     "report_writer",
                     "security_researcher"):
            routes[role] = \
                env.providers.resolve_role(role)
        return {"roles": routes,
                "providers": env.providers.status()}
