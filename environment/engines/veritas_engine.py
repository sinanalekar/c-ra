"""VERITAS engine adapter: the coordinator's own research engine
(hypothesis ledger, evidence grading, falsification batteries,
hash-chained provenance). Runs in-process against the sibling
veritas repository (read-only: the adapter never writes into the
engine repository; experiments run inside the environment's own
workspace)."""
from __future__ import annotations

import importlib
import json
import sys

from .base import (EngineResult, EngineUnavailable,
                   ResearchEngine)


class VeritasEngine(ResearchEngine):
    name = "veritas"
    version = "2.3"
    capabilities = (
        "hypothesis_ledger", "evidence_grading",
        "falsification_batteries", "provenance_journal",
        "blind_spot_audit", "invention_certificates",
        "causal_counterfactual",
    )
    inputs = ("hypothesis", "target", "experiment_plan")
    outputs = ("finding_candidates", "evidence", "journal")
    experiment_types = (
        "stateworld_experiment", "dialectic_battery",
        "blindspot_demo", "invention_benchmark",
    )
    authorization_requirements = ("experimental_execution",)
    risk_level = "low"

    def __init__(self, repo_path, work_root, journal=None):
        self.repo_path = repo_path
        self.work_root = work_root
        self.journal = journal
        self._veritas = None

    def _import(self):
        if self._veritas is not None:
            return self._veritas
        if self.repo_path is None:
            raise EngineUnavailable(
                "veritas repository path not configured")
        if self.repo_path not in sys.path:
            sys.path.insert(0, self.repo_path)
        try:
            self._veritas = importlib.import_module("veritas")
        except Exception as e:
            raise EngineUnavailable(
                f"veritas package import failed: {e}") from e
        return self._veritas

    def available(self) -> bool:
        try:
            self._import()
            return True
        except EngineUnavailable:
            return False

    def execute(self, experiment_id: str, hypothesis: dict,
                params: dict, ctx: dict) -> EngineResult:
        v = self._import()
        # an in-process falsification/closure experiment on the
        # authoritative state worlds (no writes into the repo)
        blindspots = importlib.import_module(
            "veritas.blindspots")
        demo = blindspots.demonstrate_blindspot(
            seed=params.get("seed", 7))
        evidence = [{
            "type": "measurement",
            "observation": {
                "ground_truth_violations":
                    demo["ground_truth_violations"],
                "battery_blind": demo["battery_blind"],
                "closure_ba": demo["closure_ba"],
            },
            "interpretation":
                "blind spot demonstrated against ground truth; "
                "closure instrument sees the class",
            "confidence": 0.95,
        }]
        controls = [{
            "type": "negative_control",
            "observation": "battery verdicts recorded per "
                          "instrument (cannot-consume/blind)",
            "passed": demo["battery_blind"],
        }]
        disposition = ("SUPPORTED"
                       if demo["verdict"] ==
                       "BLIND_SPOT_DEMONSTRATED_AND_CLOSABLE"
                       else "INCONCLUSIVE")
        result = EngineResult(
            engine=self.name, experiment_id=experiment_id,
            disposition=disposition, evidence=evidence,
            controls=controls,
            summary=f"{demo['world']}: {demo['verdict']} "
                    f"(closure BA {demo['closure_ba']})",
        )
        if self.journal:
            self.journal.append(
                "engine_experiment",
                engine=self.name, experiment_id=experiment_id,
                disposition=disposition,
                summary=result.summary)
        return result

    def reproduce(self, experiment_id: str, ctx: dict):
        params = ctx.get("params", {})
        fresh = self.execute(
            experiment_id + "-repro",
            {}, {**params, "seed": params.get("seed", 7) + 1},
            ctx)
        return fresh

    def collect_evidence(self, experiment_id: str) -> list:
        return []

    def export_provenance(self, experiment_id: str) -> dict:
        v = self._import()
        out = {}
        ws = self.repo_path + "/workspace"
        try:
            with open(ws + "/HEAD", encoding="utf-8") as f:
                out["veritas_journal_head"] = f.read().strip()
        except OSError:
            out["veritas_journal_head"] = None
        out["engine_version"] = v.__version__
        return out

    def validate(self, experiment_id: str) -> dict:
        return {"ok": self.available(),
                "detail": "veritas package importable"}
