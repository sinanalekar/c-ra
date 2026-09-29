"""Engine registry wiring: all five sibling systems as
first-class research engines."""
from __future__ import annotations

from .base import EngineRegistry
from .veritas_engine import VeritasEngine
from .cider_engine import CiderEngine
from .frontier_engine import FrontierEngine
from .hydra_engine import HydraEngine
from .seek_engine import SeekEngine


def build_registry(config, journal=None) -> EngineRegistry:
    """Instantiate and register every engine adapter with the
    resolved repository paths. Unresolved engines stay registered
    and report available=False (honest, inspectable)."""
    paths = config.resolve_engine_paths()
    config.ensure_dirs()
    reg = EngineRegistry()
    reg.register(VeritasEngine(
        paths.get("veritas"),
        str(config.engine_workspaces), journal))
    reg.register(CiderEngine(
        paths.get("cider"),
        str(config.engine_workspaces), journal))
    reg.register(FrontierEngine(
        paths.get("frontier"),
        str(config.engine_workspaces), journal))
    reg.register(HydraEngine(
        paths.get("hydra"),
        str(config.engine_workspaces), journal))
    reg.register(SeekEngine(
        paths.get("seek"),
        str(config.engine_workspaces), journal))
    return reg
