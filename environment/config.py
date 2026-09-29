"""Environment configuration: paths, engine locations, provider
store. Everything local-first; nothing here ever contains secrets
(keys live in the OS credential store via providers.py)."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_ENGINE_PATHS = {
    "veritas": r"C:\Users\SINAN\veritas",
    "cider": None,   # resolved from the study clones or operator set
    "frontier": None,
    "hydra": None,
    "seek": None,
}
_STUDY_ROOT = (Path(os.environ.get("TEMP", ".")) / "opencode")


class Config:
    """Runtime configuration for the local environment."""

    def __init__(self, root: str | None = None):
        self.root = Path(root or os.environ.get(
            "VERITAS_ENV_ROOT", Path.home() / "veritas-env"))
        self.workspace = self.root / "workspace"
        self.journal_path = self.workspace / "journal.jsonl"
        self.grants_path = self.workspace / "grants.json"
        self.providers_path = self.workspace / "providers.json"
        self.engine_workspaces = self.workspace / "engines"
        self.engine_paths: dict[str, str | None] = dict(
            DEFAULT_ENGINE_PATHS)

    def resolve_engine_paths(self) -> dict[str, str | None]:
        """Best-effort resolution of sibling engine repositories.
        Operators can pin paths via VERITAS_ENV_ENGINES (JSON) or
        per-engine env vars; unresolved engines stay None and
        their adapters report unavailable honestly."""
        pinned = os.environ.get("VERITAS_ENV_ENGINES")
        if pinned:
            try:
                self.engine_paths.update(json.loads(pinned))
            except json.JSONDecodeError:
                pass
        for name in self.engine_paths:
            env_var = f"VERITAS_ENV_{name.upper()}_PATH"
            if os.environ.get(env_var):
                self.engine_paths[name] = os.environ[env_var]
        if self.engine_paths.get("cider") is None:
            cand = _STUDY_ROOT / "study-cider"
            if cand.is_dir():
                self.engine_paths["cider"] = str(cand)
        if self.engine_paths.get("frontier") is None:
            cand = _STUDY_ROOT / "study-frontier"
            if cand.is_dir():
                self.engine_paths["frontier"] = str(cand)
        if self.engine_paths.get("hydra") is None:
            cand = _STUDY_ROOT / "study-hydra"
            if cand.is_dir():
                self.engine_paths["hydra"] = str(cand)
        if self.engine_paths.get("seek") is None:
            cand = _STUDY_ROOT / "study-seek"
            if cand.is_dir():
                self.engine_paths["seek"] = str(cand)
        return self.engine_paths

    def ensure_dirs(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.engine_workspaces.mkdir(parents=True, exist_ok=True)
