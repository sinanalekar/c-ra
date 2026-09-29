"""Least-privilege authorization layer. Deny by default; grants
are explicit, inspectable, and never silently expanded. Every
meaningful experiment passes: identify target -> verify
authorization -> verify capability -> verify safety limits ->
execute -> record."""
from __future__ import annotations

import json
import time
from pathlib import Path

CAPABILITIES = (
    "workspace_read", "workspace_write", "file_delete",
    "terminal", "git_write", "network", "device_access",
    "firmware_tooling", "packet_capture", "experimental_execution",
    "destructive_operations",
)

# capabilities that additionally require an explicit per-operation
# confirmation even when granted
HIGH_RISK = {"destructive_operations", "device_access",
             "packet_capture"}


class AuthorizationError(PermissionError):
    pass


class PermissionSystem:
    def __init__(self, grants_path, journal=None):
        self.path = Path(grants_path)
        self.journal = journal
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self.grants = json.load(f)
        else:
            self.grants = {"capabilities": {}}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.grants, f, indent=1, sort_keys=True)

    def grant(self, capability: str, scope: str = "*",
              actor: str = "operator") -> dict:
        if capability not in CAPABILITIES:
            raise AuthorizationError(
                f"unknown capability {capability!r}")
        caps = self.grants["capabilities"]
        caps.setdefault(capability, []).append({
            "scope": scope, "actor": actor,
            "granted_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        self._save()
        if self.journal:
            self.journal.append("authorization_granted",
                                capability=capability,
                                scope=scope, actor=actor)
        return {"capability": capability, "scope": scope,
                "granted": True}

    def revoke(self, capability: str) -> dict:
        self.grants["capabilities"].pop(capability, None)
        self._save()
        if self.journal:
            self.journal.append("authorization_revoked",
                                capability=capability)
        return {"capability": capability, "granted": False}

    def check(self, capability: str, scope: str = "*",
              confirm_high_risk: bool = False) -> bool:
        entries = self.grants["capabilities"].get(capability, [])
        allowed = any(e["scope"] in ("*", scope)
                     for e in entries)
        if allowed and capability in HIGH_RISK and \
                not confirm_high_risk:
            return False
        return allowed

    def require(self, capability: str, scope: str = "*",
                confirm_high_risk: bool = False):
        if not self.check(capability, scope, confirm_high_risk):
            if self.journal:
                self.journal.append(
                    "authorization_denied",
                    capability=capability, scope=scope)
            raise AuthorizationError(
                f"missing authorization: {capability} "
                f"(scope {scope!r})")

    def status(self) -> dict:
        return {
            "capabilities": {
                c: bool(v) for c, v in
                self.grants["capabilities"].items()},
            "deny_by_default": True,
        }
