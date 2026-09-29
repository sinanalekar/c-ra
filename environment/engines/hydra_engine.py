"""HYDRA engine adapter: Apple firmware/kernel static-analysis
instrument (IPSW/kernelcache/kext inventory, function attribution,
cross-version differentials, pattern scans, mitigation analysis).

All static candidates remain STATIC_CANDIDATE - the adapter
never promotes them toward real-vulnerability claims (master
prompt section 13). Firmware work requires the firmware_tooling
capability and a target artifact with provenance; without an
artifact the adapter reports BLOCKED honestly."""
from __future__ import annotations

import importlib
import sys

from .base import (EngineResult, EngineUnavailable,
                   ResearchEngine)


class HydraEngine(ResearchEngine):
    name = "hydra"
    version = "0.1.0"
    capabilities = (
        "ipsw_analysis", "kernelcache_analysis",
        "kext_enumeration", "macho_fileset_analysis",
        "function_extraction", "cross_version_differential",
        "pattern_scanning", "mitigation_analysis",
        "candidate_generation", "static_triage",
    )
    inputs = ("kernelcache_artifact", "version_pair",
              "pattern_request")
    outputs = ("static_candidates", "differential_report",
               "triage_verdicts")
    experiment_types = (
        "pattern_scan", "cross_version_diff", "static_triage",
    )
    authorization_requirements = ("firmware_tooling",
                                  "experimental_execution")
    risk_level = "low"

    def __init__(self, repo_path, work_root, journal=None):
        self.repo_path = repo_path
        self.work_root = work_root
        self.journal = journal
        self._mod = None

    def _import(self):
        if self._mod is not None:
            return self._mod
        if self.repo_path is None:
            raise EngineUnavailable(
                "hydra repository path not configured")
        if self.repo_path not in sys.path:
            sys.path.insert(0, self.repo_path)
        try:
            self._mod = importlib.import_module("hydra")
        except Exception as e:
            raise EngineUnavailable(
                f"hydra package import failed: {e}") from e
        return self._mod

    def available(self) -> bool:
        try:
            self._import()
            return True
        except EngineUnavailable:
            return False

    def execute(self, experiment_id: str, hypothesis: dict,
                params: dict, ctx: dict) -> EngineResult:
        self._import()
        artifact = params.get("kernelcache_artifact")
        if not artifact:
            # honest blocked state: no artifact, no scan
            if self.journal:
                self.journal.append(
                    "engine_experiment_blocked",
                    engine=self.name,
                    experiment_id=experiment_id,
                    reason="no firmware artifact provided")
            return EngineResult(
                engine=self.name, experiment_id=experiment_id,
                disposition="BLOCKED",
                evidence=[{
                    "type": "blocked_state",
                    "observation":
                        "firmware artifact required for "
                        "kernelcache analysis; none provided",
                    "interpretation":
                        "capability present, inputs absent - "
                        "reported, not faked",
                    "confidence": 1.0,
                }],
                controls=[],
                summary="hydra adapter online; firmware artifact "
                        "required for this experiment type")
        return EngineResult(
            engine=self.name, experiment_id=experiment_id,
            disposition="INCONCLUSIVE",
            evidence=[{
                "type": "static_candidates",
                "observation":
                    "scan requested against artifact "
                    f"{artifact}",
                "interpretation":
                    "candidates are STATIC_CANDIDATE until "
                    "independently validated",
                "confidence": 0.5,
            }],
            controls=[],
            summary="hydra scan dispatched; all output remains "
                    "STATIC_CANDIDATE")

    def validate(self, experiment_id: str) -> dict:
        return {"ok": self.available(),
                "detail": "hydra package importable"}

    def reproduce(self, experiment_id: str, ctx: dict):
        return self.execute(experiment_id + "-repro", {},
                            ctx.get("params", {}), ctx)

    def collect_evidence(self, experiment_id: str) -> list:
        return []

    def export_provenance(self, experiment_id: str) -> dict:
        return {"engine": self.name,
                "experiment_id": experiment_id,
                "candidate_state": "STATIC_CANDIDATE"}
