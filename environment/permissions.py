"""Backward-compatible facade over the central capability
system. The pre-CYR@ permission names (workspace_read,
experimental_execution, ...) keep working - every call flows
through environment.capabilities.CapabilitySystem so there is
exactly ONE authorization ledger. New code should call the
capability system directly with the canonical capability
names."""
from __future__ import annotations

from .capabilities import (CAPABILITIES as _CANONICAL,
                           ALIASES, AuthorizationError,
                           CapabilitySystem)

# the legacy surface (tests + the research orchestrator use it)
CAPABILITIES = tuple(ALIASES) + tuple(_CANONICAL)
HIGH_RISK = {"destructive_operations", "device_access",
             "packet_capture"}


class PermissionSystem:
    """Facade: grants/checks in legacy names map onto the
    canonical ledger (see ALIASES)."""

    def __init__(self, grants_path, journal=None):
        self.system = CapabilitySystem(grants_path, journal)
        self.journal = journal

    # -------------------------------------------------- facade
    def grant(self, capability: str, scope: str = "*",
              actor: str = "operator") -> dict:
        return self.system.grant(capability, "allow_session",
                                 scope, actor=actor)

    def grant_workspace(self, capability: str, path: str,
                        actor: str = "operator") -> dict:
        return self.system.grant(capability,
                                 "allow_workspace", path,
                                 actor=actor)

    def revoke(self, capability: str) -> dict:
        return self.system.revoke(capability)

    def check(self, capability: str, scope: str = "*",
              confirm_high_risk: bool = False) -> bool:
        # legacy high-risk policy runs here; the canonical set's
        # own confirmation requirement is then satisfied by
        # construction (this facade has already enforced its
        # stricter-for-legacy-names gate)
        if capability in HIGH_RISK and not confirm_high_risk:
            self._deny_legacy(capability, scope)
            return False
        d = self.system.authorize(capability, scope, None,
                                  confirm_high_risk=True)
        return d["allowed"]

    def require(self, capability: str, scope: str = "*",
                confirm_high_risk: bool = False):
        if capability in HIGH_RISK and not confirm_high_risk:
            self._deny_legacy(capability, scope)
            raise AuthorizationError(
                f"missing confirmation: {capability} is "
                f"high-risk")
        return self.system.require(capability, scope, None,
                                   confirm_high_risk=True)

    def _deny_legacy(self, capability: str, scope: str):
        if self.journal:
            self.journal.append(
                "authorization_denied",
                capability=capability, scope=scope,
                reason="high-risk confirmation required "
                       "(legacy policy)")

    def status(self) -> dict:
        st = self.system.status()
        granted = {g["capability"]
                   for caps in self.system.grants.values()
                   for g in caps
                   if g["mode"] != "deny"}
        return {
            "capabilities": {
                c: (ALIASES.get(c, c) in granted)
                for c in ALIASES},
            "deny_by_default": True,
            "central_ledger": st,
        }
