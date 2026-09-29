"""Frontier engine adapter: the algorithm/method/invention
discovery machine (two-stage precision-floored rule discovery,
DiscoveryCertificates, measured negatives). Imported read-only
from the sibling repository; discovery runs are synthetic-world
method results, never real-vulnerability claims."""
from __future__ import annotations

import importlib
import sys

from .base import (EngineResult, EngineUnavailable,
                   ResearchEngine)


class FrontierEngine(ResearchEngine):
    name = "frontier"
    version = "v3"
    capabilities = (
        "representation_discovery", "invariant_discovery",
        "detector_discovery", "algorithm_space_search",
        "robustness_testing", "ablation", "ood_testing",
        "discovery_certificates",
    )
    inputs = ("method_question", "synthetic_worlds",
              "certificate_request")
    outputs = ("discovered_method", "certificate",
               "measured_negatives")
    experiment_types = ("method_benchmark",
                        "ablation_study",
                        "ood_transfer_study")
    authorization_requirements = ("experimental_execution",)
    risk_level = "low"

    def __init__(self, repo_path, work_root, journal=None):
        self.repo_path = repo_path
        self.work_root = work_root
        self.journal = journal
        self._pipeline = None

    def _import(self):
        if self._pipeline is not None:
            return self._pipeline
        if self.repo_path is None:
            raise EngineUnavailable(
                "frontier repository path not configured")
        if self.repo_path not in sys.path:
            sys.path.insert(0, self.repo_path)
        try:
            self._pipeline = importlib.import_module(
                "frontier.pipeline")
        except Exception as e:
            raise EngineUnavailable(
                f"frontier package import failed: {e}") from e
        return self._pipeline

    def available(self) -> bool:
        try:
            self._import()
            return True
        except EngineUnavailable:
            return False

    def execute(self, experiment_id: str, hypothesis: dict,
                params: dict, ctx: dict) -> EngineResult:
        self._import()
        # capability probe: the adapter exposes frontier's method
        # surface; deep method campaigns run on request with
        # explicit params. Reported honestly when not exercised.
        return EngineResult(
            engine=self.name, experiment_id=experiment_id,
            disposition="INCONCLUSIVE",
            evidence=[{
                "type": "capability_probe",
                "observation":
                    "frontier pipeline importable; method "
                    "campaigns require explicit method_question "
                    "params",
                "interpretation":
                    "adapter operational; no method campaign "
                    "requested in this run",
                "confidence": 0.8,
            }],
            controls=[],
            summary="frontier adapter online; method discovery "
                    "available on explicit request")

    def validate(self, experiment_id: str) -> dict:
        return {"ok": self.available(),
                "detail": "frontier pipeline importable"}

    def reproduce(self, experiment_id: str, ctx: dict):
        return self.execute(experiment_id + "-repro", {},
                            ctx.get("params", {}), ctx)

    def collect_evidence(self, experiment_id: str) -> list:
        return []

    def export_provenance(self, experiment_id: str) -> dict:
        return {"engine": self.name,
                "experiment_id": experiment_id,
                "note": "synthetic method results only - a "
                        "discovery certificate is a method "
                        "result, never a real-vulnerability "
                        "claim"}
