"""Central capability/authorization layer (the ONE system every
sensitive tool must pass through).

Capabilities: filesystem.*, terminal.execute, process.spawn,
git.*, browser.*, computer.*, network.request, research.execute,
engine.*.

Grant modes: deny | allow_once | allow_task | allow_workspace |
allow_session.

- allow_once is consumed on first use.
- allow_task is bound to a task id (durable task or run id).
- allow_workspace is bound to a path prefix.
- allow_session lasts for the backend process lifetime.
- an explicit deny grant overrides any allow.

High-risk capabilities additionally require a confirm flag on
each authorize() call. Every decision is journaled (with
redaction - never capability arguments that could carry
secrets). No tool can bypass this layer: the terminal, git,
browser, computer, workspace, and research subsystems all call
authorize() before acting."""
from __future__ import annotations

import json
import time
from pathlib import Path

CAPABILITIES = (
    "filesystem.read", "filesystem.write",
    "filesystem.delete", "filesystem.execute",
    "terminal.execute", "process.spawn",
    "git.read", "git.write", "git.push",
    "browser.read", "browser.navigate", "browser.interact",
    "browser.download", "browser.upload",
    "computer.read", "computer.interact",
    "network.request", "research.execute",
    "engine.veritas", "engine.cider", "engine.seek",
    "engine.hydra", "engine.frontier",
)

MODES = ("deny", "allow_once", "allow_task",
         "allow_workspace", "allow_session")

HIGH_RISK = ("filesystem.delete", "computer.interact",
             "browser.download", "browser.upload",
             "git.push")

# legacy aliases (the pre-CYR@ permission names kept working so
# existing callers and tests flow through the same ledger)
ALIASES = {
    "workspace_read": "filesystem.read",
    "workspace_write": "filesystem.write",
    "file_delete": "filesystem.delete",
    "terminal": "terminal.execute",
    "git_write": "git.write",
    "network": "network.request",
    "device_access": "computer.interact",
    "firmware_tooling": "filesystem.execute",
    "packet_capture": "network.request",
    "experimental_execution": "research.execute",
    "destructive_operations": "filesystem.delete",
}


def canonical(capability: str) -> str:
    return ALIASES.get(capability, capability)


def _is_valid(capability: str) -> bool:
    return canonical(capability) in CAPABILITIES


class AuthorizationError(PermissionError):
    pass


class Decision(dict):
    @classmethod
    def deny(cls, reason: str) -> "Decision":
        return cls(allowed=False, reason=reason, mode=None,
                   grant_id=None)

    @classmethod
    def allow(cls, mode: str, grant_id: str) -> "Decision":
        return cls(allowed=True, reason="", mode=mode,
                    grant_id=grant_id)


class CapabilitySystem:
    """The central authorization engine. All sensitive tools
    construct this once (or receive it) and call authorize()."""

    def __init__(self, store_path, journal=None):
        self.path = Path(store_path)
        self.journal = journal
        self.grants: dict[str, list[dict]] = {}
        self._seq = 0
        self._load()

    # ------------------------------------------------ persistence
    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(
                    self.path.read_text(encoding="utf-8"))
                self.grants = data.get("grants", {})
                self._seq = data.get("seq", 0)
            except (json.JSONDecodeError, OSError):
                self.grants = {}
                self._seq = 0

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(
            {"schema": "cyra_capabilities_v1",
             "seq": self._seq, "grants": self.grants},
            indent=1, sort_keys=True), encoding="utf-8")

    # ------------------------------------------------ grants
    def grant(self, capability: str,
              mode: str = "allow_session", scope: str = "*",
              task_id: str | None = None,
              actor: str = "operator") -> dict:
        cap = canonical(capability)
        if not _is_valid(cap):
            raise AuthorizationError(
                f"unknown capability {capability!r}")
        if mode not in MODES:
            raise AuthorizationError(
                f"unknown mode {mode!r}")
        if mode == "allow_task" and not task_id:
            raise AuthorizationError(
                "allow_task requires a task_id")
        if mode == "allow_workspace" and scope == "*":
            raise AuthorizationError(
                "allow_workspace requires a concrete path "
                "scope")
        self._seq += 1
        gid = f"grant-{self._seq:05d}"
        rec = {
            "grant_id": gid, "capability": cap, "mode": mode,
            "scope": scope, "task_id": task_id,
            "actor": actor,
            "granted_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.grants.setdefault(cap, []).append(rec)
        self._save()
        self._journal("authorization_granted",
                      capability=cap, mode=mode, scope=scope,
                      grant_id=gid, actor=actor)
        return {"grant_id": gid, "capability": cap,
                "mode": mode, "scope": scope}

    def revoke(self, capability: str,
               grant_id: str | None = None) -> dict:
        cap = canonical(capability)
        if grant_id:
            self.grants[cap] = [g for g in
                                self.grants.get(cap, [])
                                if g["grant_id"] != grant_id]
        else:
            self.grants.pop(cap, None)
        self._save()
        self._journal("authorization_revoked", capability=cap,
                      grant_id=grant_id)
        return {"capability": cap, "revoked": True}

    def revoke_scope(self, scope: str) -> int:
        """Revoke every grant tied to a workspace path."""
        n = 0
        for cap in list(self.grants):
            keep = []
            for g in self.grants[cap]:
                if g["scope"] == scope:
                    n += 1
                else:
                    keep.append(g)
            if keep:
                self.grants[cap] = keep
            else:
                self.grants.pop(cap, None)
        self._save()
        return n

    # ------------------------------------------------ decisions
    @staticmethod
    def _scope_matches(grant_scope: str, scope: str) -> bool:
        if grant_scope == "*":
            return True
        if not scope or scope == "*":
            return False
        gs = str(Path(grant_scope)).rstrip("\\/").lower()
        ss = str(Path(scope)).rstrip("\\/").lower()
        return ss == gs or ss.startswith(gs + "\\")

    def authorize(self, capability: str, scope: str = "*",
                  task_id: str | None = None,
                  confirm_high_risk: bool = False) -> Decision:
        cap = canonical(capability)
        if not _is_valid(cap):
            self._journal("authorization_denied",
                          capability=capability,
                          reason="unknown capability")
            return Decision.deny("unknown capability")
        entries = self.grants.get(cap, [])
        # explicit deny wins over everything
        for g in entries:
            if g["mode"] == "deny":
                self._journal("authorization_denied",
                              capability=cap,
                              reason="explicit deny grant")
                return Decision.deny("explicitly denied")
        best = None
        for g in entries:
            if g["mode"] == "deny":
                continue
            if not self._scope_matches(g["scope"], scope):
                continue
            if g["mode"] == "allow_task" and \
                    g["task_id"] != task_id:
                continue
            if best is None or \
                    MODES.index(g["mode"]) > \
                    MODES.index(best["mode"]):
                best = g
        if best is None:
            self._journal("authorization_denied",
                          capability=cap, scope=scope,
                          reason="no matching grant")
            return Decision.deny(
                f"missing authorization: {cap} "
                f"(scope {scope!r})")
        if cap in HIGH_RISK and not confirm_high_risk:
            self._journal("authorization_denied",
                          capability=cap, scope=scope,
                          reason="high-risk confirmation "
                                 "required")
            return Decision.deny(
                f"{cap} is high-risk: explicit confirmation "
                f"required for this operation")
        if best["mode"] == "allow_once":
            # consume the one-shot grant
            self.grants[cap] = [x for x in
                                self.grants.get(cap, [])
                                if x["grant_id"] !=
                                best["grant_id"]]
            self._save()
        self._journal("authorization_allowed",
                      capability=cap, scope=scope,
                      mode=best["mode"],
                      grant_id=best["grant_id"])
        return Decision.allow(best["mode"],
                              best["grant_id"])

    def require(self, capability: str, scope: str = "*",
                task_id: str | None = None,
                confirm_high_risk: bool = False) -> Decision:
        d = self.authorize(capability, scope, task_id,
                           confirm_high_risk)
        if not d["allowed"]:
            raise AuthorizationError(d["reason"])
        return d

    # ------------------------------------------------ status
    def status(self) -> dict:
        return {
            "capabilities": list(CAPABILITIES),
            "modes": list(MODES),
            "high_risk": list(HIGH_RISK),
            "grants": [
                {k: v for k, v in g.items()}
                for caps in self.grants.values()
                for g in caps],
            "deny_by_default": True,
        }

    def _journal(self, action: str, **fields):
        if self.journal:
            self.journal.append(action, **fields)
