"""Common research-engine interface (master prompt section 9).

Every engine adapter implements the same protocol: name, version,
capabilities, inputs, outputs, experiment_types,
authorization_requirements, risk_level, and the
execute/validate/reproduce/collect_evidence/export_provenance
methods. Future engines register without rewriting the
orchestrator.

Honesty rules (section 47) apply to every adapter: if the engine
repository is missing, the adapter reports `available=False` and
raises EngineUnavailable - it never fabricates results."""
from __future__ import annotations


class EngineUnavailable(RuntimeError):
    """Raised when an engine repository is not present/importable.
    Reported honestly - never worked around with fake output."""


class EngineResult:
    """Normalized result of one engine experiment run."""

    def __init__(self, engine: str, experiment_id: str,
                 disposition: str, evidence: list,
                 controls: list, summary: str,
                 artifacts: list | None = None):
        self.engine = engine
        self.experiment_id = experiment_id
        # SUPPORTED / REFUTED / INCONCLUSIVE / BLOCKED
        self.disposition = disposition
        self.evidence = evidence      # list[dict] evidence objects
        self.controls = controls      # list[dict] negative controls
        self.summary = summary
        self.artifacts = artifacts or []

    def as_dict(self):
        return {
            "engine": self.engine,
            "experiment_id": self.experiment_id,
            "disposition": self.disposition,
            "summary": self.summary,
            "evidence": self.evidence,
            "controls": self.controls,
            "artifacts": self.artifacts,
        }


class ResearchEngine:
    """The adapter contract. Subclasses fill in the engine
    specifics; the orchestrator only ever talks to this
    interface."""

    name: str = "abstract"
    version: str = "unknown"
    capabilities: tuple = ()
    inputs: tuple = ()
    outputs: tuple = ()
    experiment_types: tuple = ()
    authorization_requirements: tuple = ()
    risk_level: str = "low"

    def available(self) -> bool:
        raise NotImplementedError

    def describe(self) -> dict:
        return {
            "name": self.name, "version": self.version,
            "available": self.available(),
            "capabilities": list(self.capabilities),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "experiment_types": list(self.experiment_types),
            "authorization_requirements":
                list(self.authorization_requirements),
            "risk_level": self.risk_level,
        }

    def validate(self, experiment_id: str) -> dict:
        raise NotImplementedError

    def execute(self, experiment_id: str, hypothesis: dict,
                params: dict, ctx: dict) -> EngineResult:
        raise NotImplementedError

    def reproduce(self, experiment_id: str, ctx: dict):
        raise NotImplementedError

    def collect_evidence(self, experiment_id: str) -> list:
        raise NotImplementedError

    def export_provenance(self, experiment_id: str) -> dict:
        raise NotImplementedError


class EngineRegistry:
    def __init__(self):
        self._engines: dict[str, ResearchEngine] = {}

    def register(self, engine: ResearchEngine):
        self._engines[engine.name] = engine

    def get(self, name: str) -> ResearchEngine:
        if name not in self._engines:
            raise KeyError(f"engine {name!r} not registered")
        return self._engines[name]

    def all(self) -> dict:
        return dict(self._engines)

    def describe_all(self) -> list:
        return [e.describe()
                for e in self._engines.values()]
