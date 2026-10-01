"""Local backend: FastAPI app binding the whole environment.

Security posture (master prompt section 3): binds to the loopback
interface ONLY - no network exposure of backend functionality;
the desktop shell talks to it over local IPC (localhost HTTP for
the vertical slice, Tauri sidecar IPC for the packaged shell)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .version import PRODUCT_NAME, \
    VERSION as __version__
from .config import Config
from .journal import Journal
from .permissions import (CAPABILITIES, AuthorizationError,
                          PermissionSystem)
from .providers import ProviderStore
from .targets import (APPLE_SERVICE_CLASSES, CATEGORIES,
                      TargetUniverse)
from .workspace import Workspace, WorkspaceError
from .engines import build_registry
from .orchestrator import Orchestrator


class Environment:
    """Composition root: one object wiring config, journal, the
    central capability system, providers, engines, targets,
    workspace, the tool runtimes (terminal/git/browser/
    computer), the durable task store, memory, artifacts,
    evidence, and the orchestrator."""

    def __init__(self, root: str | None = None):
        self.config = Config(root)
        self.config.ensure_dirs()
        self.journal = Journal(self.config.journal_path)
        self.permissions = PermissionSystem(
            self.config.grants_path, self.journal)
        self.capabilities = self.permissions.system
        self.providers = ProviderStore(
            self.config.providers_path, self.journal)
        self.registry = build_registry(self.config,
                                       self.journal)
        self.targets = TargetUniverse()
        self.workspace = Workspace(
            self.config.workspace, self.permissions,
            self.journal)
        from .terminal import TerminalRuntime
        from .gitops import GitRuntime
        from .browser import BrowserRuntime
        from .computer import ComputerRuntime
        from .tasks import TaskStore
        from .memory import MemoryStore
        from .artifacts import ArtifactStore
        from .evidence import EvidenceStore
        self.terminal = TerminalRuntime(
            self.capabilities, self.journal)
        self.git = GitRuntime(
            self.capabilities, self.journal)
        self.browser = BrowserRuntime(
            self.capabilities, self.journal)
        self.computer = ComputerRuntime(
            self.capabilities, self.journal)
        self.taskstore = TaskStore(
            self.config.workspace, self.journal)
        n_loaded = self.taskstore.load()
        recovered = self.taskstore.recover()
        self.memory = MemoryStore(
            self.config.workspace, self.journal)
        self.artifacts = ArtifactStore(
            self.config.workspace, self.journal)
        self.evidence = EvidenceStore(
            self.config.workspace, self.journal)
        runtimes = {
            "workspace": self.workspace,
            "terminal": self.terminal,
            "git": self.git,
            "browser": self.browser,
            "computer": self.computer,
            "tasks": self.taskstore,
            "memory": self.memory,
            "artifacts": self.artifacts,
            "evidence": self.evidence,
        }
        self.orchestrator = Orchestrator(
            self.config, self.registry, self.permissions,
            self.journal, self.targets,
            provider_store=self.providers,
            runtimes=runtimes)
        self.journal.append("session_started",
                            engines=[
                                e["name"] for e in
                                self.registry.describe_all()
                                if e["available"]],
                            tasks_loaded=n_loaded,
                            tasks_recovered=len(
                                recovered["recovered"]))
        # provider discovery runs in the background once the
        # server listens (see environment.server) - the API is
        # never blocked behind catalog fetches
        self.discovery = None
        # Reinitialize subsystem (differential sync with the
        # research ecosystem)
        from .reinit import ReinitEngine
        self.reinit = ReinitEngine(
            self.config.workspace, self.journal)
        try:
            import environment
            self.reinit.cfg.set_cyr_path(
                str(Path(__file__).resolve()
                    .parent.parent))
        except Exception:
            pass
        # first-run defaults: the standard local working set is
        # granted for the session so the app works out of the
        # box (recorded in the journal; revocable in Settings;
        # destructive capabilities still require confirmation)
        if not any(self.capabilities.grants.values()):
            from .capabilities import \
                DEFAULT_GRANTS
            for cap in DEFAULT_GRANTS:
                self.capabilities.grant(
                    cap, "allow_session",
                    actor="first-run default")
            self.journal.append(
                "first_run_default_grants",
                capabilities=list(
                    DEFAULT_GRANTS))


class TargetQuery(BaseModel):
    query: str = ""
    category: str | None = None


class HypothesisSpec(BaseModel):
    claim: str
    target_id: str
    engine: str
    falsification: str = ""
    params: dict = {}


class ExperimentSpec(BaseModel):
    params: dict = {}


class PathSpec(BaseModel):
    path: str
    content: str = ""


class SearchSpec(BaseModel):
    query: str
    sub: str = ""


class GrantSpec(BaseModel):
    capability: str
    scope: str = "*"


class ProviderSpec(BaseModel):
    spec: dict


class RoleSpec(BaseModel):
    role: str
    provider: str
    model_id: str


class AgentTask(BaseModel):
    kind: str
    task: dict


class RouteSpec(BaseModel):
    target_id: str
    vulnerability_class: str = ""


def create_app(env: Environment | None = None) -> FastAPI:
    env = env or Environment()
    app = FastAPI(
        title=PRODUCT_NAME,
        version=__version__,
        docs_url="/api/docs",
    )
    app.state.env = env

    # CORS: the packaged Tauri shell serves the UI from
    # tauri://localhost / http://tauri.localhost while the API
    # binds 127.0.0.1:8765 - cross-origin, so the browser
    # preflights every request. Allow exactly the local shell
    # + dev origins (never arbitrary external sites).
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "tauri://localhost",
            "http://tauri.localhost",
            "http://localhost:5175",
            "http://127.0.0.1:5175",
        ],
        allow_methods=["GET", "POST", "DELETE",
                       "PUT", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    # ------------------------------------------------ session
    @app.get("/api/status")
    def status():
        return {
            "session": "active",
            "engines": env.registry.describe_all(),
            "providers": env.providers.status(),
            "authorization": env.permissions.status(),
            "coverage": env.targets.coverage_report(),
            "journal": env.journal.verify(),
        }

    # ------------------------------------------------ engines
    @app.get("/api/engines")
    def engines():
        return env.registry.describe_all()

    @app.get("/api/engines/{name}/validate")
    def engine_validate(name: str):
        try:
            eng = env.registry.get(name)
        except KeyError:
            raise HTTPException(404, "unknown engine")
        return eng.validate(name)

    # ------------------------------------------------ targets

    @app.post("/api/targets/search")
    def targets_search(q: TargetQuery):
        return env.targets.search(q.query, q.category)

    @app.get("/api/targets/{target_id}")
    def target_get(target_id: str):
        t = env.targets.get(target_id)
        if t is None:
            raise HTTPException(404, "unknown target")
        return {"target": dict(t),
                "research_plan": env.targets.for_target(
                    target_id)}

    @app.get("/api/targets/categories")
    def target_categories():
        return {"categories": CATEGORIES,
                "service_classes":
                    list(APPLE_SERVICE_CLASSES)}

    # ----------------------------------------------- hypotheses

    @app.post("/api/hypotheses")
    def hypothesis_register(spec: HypothesisSpec):
        if env.targets.get(spec.target_id) is None:
            raise HTTPException(404, "unknown target")
        try:
            env.registry.get(spec.engine)
        except KeyError:
            raise HTTPException(404, "unknown engine")
        rec = env.orchestrator.register_hypothesis(
            spec.claim, spec.target_id, spec.engine,
            spec.falsification, spec.params)
        return rec


    @app.post("/api/hypotheses/{hid}/run")
    def hypothesis_run(hid: str, spec: ExperimentSpec):
        try:
            rec = env.orchestrator.run_experiment(
                hid, spec.params)
        except AuthorizationError as e:
            raise HTTPException(403, str(e))
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    @app.get("/api/research/status")
    def research_status():
        return env.orchestrator.status()

    # ------------------------------------------------ reports
    @app.post("/api/experiments/{exp_id}/report")
    def experiment_report(exp_id: str):
        rec = env.orchestrator.generate_report(exp_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        return rec

    @app.get("/api/experiments/{exp_id}/report.md")
    def experiment_report_md(exp_id: str):
        rec = env.orchestrator.generate_report(exp_id)
        if "error" in rec:
            raise HTTPException(404, rec["error"])
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(rec["markdown"])

    # ------------------------------------------------ routing

    @app.post("/api/targets/route")
    def target_route(spec: RouteSpec):
        t = env.targets.get(spec.target_id)
        if t is None:
            raise HTTPException(404, "unknown target")
        from environment.routing import route
        return route(dict(t), spec.vulnerability_class)

    # ----------------------------------------------- workspace

    @app.post("/api/workspace/tree")
    def ws_tree(spec: PathSpec):
        try:
            return env.workspace.tree(spec.path)
        except (WorkspaceError, AuthorizationError) as e:
            raise HTTPException(403, str(e))

    @app.post("/api/workspace/read")
    def ws_read(spec: PathSpec):
        try:
            return env.workspace.read(spec.path)
        except (WorkspaceError, AuthorizationError) as e:
            raise HTTPException(403, str(e))

    @app.post("/api/workspace/write")
    def ws_write(spec: PathSpec):
        try:
            return env.workspace.write(spec.path,
                                       spec.content)
        except (WorkspaceError, AuthorizationError) as e:
            raise HTTPException(403, str(e))

    @app.post("/api/workspace/delete")
    def ws_delete(spec: PathSpec):
        try:
            return env.workspace.delete(spec.path)
        except (WorkspaceError, AuthorizationError) as e:
            raise HTTPException(403, str(e))


    @app.post("/api/workspace/search")
    def ws_search(spec: SearchSpec):
        try:
            return {"matches": env.workspace.search(
                spec.query, spec.sub)}
        except (WorkspaceError, AuthorizationError) as e:
            raise HTTPException(403, str(e))

    # --------------------------------------------- permissions

    @app.post("/api/authorization/grant")
    def auth_grant(spec: GrantSpec):
        try:
            return env.permissions.grant(
                spec.capability, spec.scope)
        except AuthorizationError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/authorization/revoke")
    def auth_revoke(spec: GrantSpec):
        return env.permissions.revoke(spec.capability)

    @app.get("/api/authorization")
    def auth_status():
        return {"capabilities": list(CAPABILITIES),
                "status": env.permissions.status()}

    # ----------------------------------------------- providers

    @app.post("/api/providers")
    def provider_add(p: ProviderSpec):
        try:
            return env.providers.add_provider(p.spec)
        except ValueError as e:
            raise HTTPException(400, str(e))


    @app.post("/api/providers/roles")
    def provider_role(r: RoleSpec):
        try:
            return env.providers.bind_role(
                r.role, r.provider, r.model_id)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/providers")
    def provider_status():
        return env.providers.status()

    # ------------------------------------------------ journal
    @app.get("/api/journal")
    def journal_entries(limit: int = 100):
        return env.journal.entries(limit)

    @app.get("/api/journal/verify")
    def journal_verify():
        return env.journal.verify()

    @app.get("/api/coverage")
    def coverage():
        return env.targets.coverage_report()

    # ---- runtime endpoints (tasks, terminal, git, browser,
    #      computer, capabilities, memory, artifacts, evidence,
    #      agent run controls, model routes)
    from .api_runtime import register_runtime_endpoints
    register_runtime_endpoints(app, env)
    return app
