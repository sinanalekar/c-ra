"""Model/provider system: an OpenCode-like provider abstraction.

Providers are configurable per role (coordinator, reasoning, coding,
research, independent reviewer, falsification reviewer). The
environment is model-agnostic: with no provider configured it runs
in LOCAL mode (deterministic engines do the work; model roles are
reported as unconfigured - never faked). API keys are stored in the
OS credential store via `keyring` when available; keys never enter
Git, journals, or reports."""
from __future__ import annotations

import json
import time
from pathlib import Path

ROLES = ("coordinator", "reasoning", "coding", "research",
         "independent_reviewer", "falsification_reviewer")

PROVIDER_SCHEMA_FIELDS = (
    "name", "base_url", "api_format", "auth", "model_ids",
    "context_size", "capabilities", "reasoning", "tools", "vision",
    "streaming", "cost_metadata", "rate_limits",
)


class ProviderStore:
    def __init__(self, path, journal=None):
        self.path = Path(path)
        self.journal = journal
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                self.config = json.load(f)
        else:
            self.config = {"providers": {},
                           "role_bindings": {}}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=1, sort_keys=True)

    # -------------------------------------------------- secrets
    @staticmethod
    def _keyring():
        try:
            import keyring
            return keyring
        except Exception:
            return None

    @classmethod
    def store_api_key(cls, provider: str, key: str) -> dict:
        """Store an API key in the OS credential store. Fallback:
        an explicit error - never a plaintext file."""
        kr = cls._keyring()
        if kr is None:
            return {"stored": False,
                    "reason": "keyring unavailable - install the "
                              "keyring package for OS credential "
                              "storage; plaintext storage refused"}
        kr.set_password("veritas-environment", provider, key)
        return {"stored": True, "backend": "os-credential-store"}

    @classmethod
    def get_api_key(cls, provider: str) -> str | None:
        kr = cls._keyring()
        if kr is None:
            return None
        return kr.get_password("veritas-environment", provider)

    # -------------------------------------------------- config
    def add_provider(self, spec: dict) -> dict:
        missing = [f for f in ("name", "base_url", "api_format")
                   if f not in spec]
        if missing:
            raise ValueError(
                f"provider spec missing fields: {missing}")
        if not spec["base_url"].startswith("https://"):
            raise ValueError("base_url must be https")
        name = spec["name"]
        spec = {k: spec.get(k) for k in PROVIDER_SCHEMA_FIELDS}
        self.config["providers"][name] = spec
        self._save()
        if self.journal:
            self.journal.append("provider_configured",
                                provider=name,
                                base_url=spec["base_url"],
                                has_key=bool(
                                    self.get_api_key(name)))
        return {"provider": name, "configured": True}

    def bind_role(self, role: str, provider: str,
                  model_id: str) -> dict:
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        if provider not in self.config["providers"]:
            raise ValueError(
                f"provider {provider!r} not configured")
        self.config["role_bindings"][role] = {
            "provider": provider, "model_id": model_id}
        self._save()
        return {"role": role, "provider": provider,
                "model_id": model_id}

    def role_status(self) -> dict:
        out = {}
        for role in ROLES:
            b = self.config["role_bindings"].get(role)
            out[role] = ({"provider": b["provider"],
                          "model_id": b["model_id"]}
                         if b else
                         {"provider": "LOCAL (unconfigured)",
                          "model_id": None})
        return out

    def status(self) -> dict:
        return {
            "providers": sorted(self.config["providers"]),
            "roles": self.role_status(),
            "note": "LOCAL mode: deterministic engines execute; "
                    "model roles are reported, never faked",
        }
