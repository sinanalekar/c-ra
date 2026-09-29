"""SEEK engine adapter: the empirical/network/application evidence
instrument. SEEK's live research operates as a journaled daemon
with real-world observations; this adapter bridges to its session
journal and exposes its capability map. Network experiments stay
behind the `network` capability and exact scope; without
authorization and a live SEEK session the adapter reports its
state honestly."""
from __future__ import annotations

import json
from pathlib import Path

from .base import (EngineResult, EngineUnavailable,
                   ResearchEngine)

SEEK_METHOD_LAWS = (
    "differential attribution (canary controls vs ambient "
    "baseline scans - T65)",
    "five-state evidence matrix (PROVEN/CORROBORATED/INFERRED)",
    "exhaustion accounting with stop conditions (T115)",
    "honest impact downgrades (T91->T92)",
)


class SeekEngine(ResearchEngine):
    name = "seek"
    version = "journal-bridge"
    capabilities = (
        "endpoint_testing", "protocol_experiments",
        "http_differential_testing", "auth_boundary_testing",
        "parser_behavior", "request_smuggling_research",
        "evidence_capture", "session_journal_bridge",
    )
    inputs = ("authorized_scope", "target_endpoints",
              "session_journal")
    outputs = ("observations", "evidence_matrix",
               "honest_negatives")
    experiment_types = (
        "http_differential", "auth_boundary_probe",
        "protocol_experiment",
    )
    authorization_requirements = ("network",
                                  "experimental_execution")
    risk_level = "medium"

    def __init__(self, repo_path, work_root, journal=None):
        self.repo_path = repo_path
        self.work_root = work_root
        self.journal = journal

    def available(self) -> bool:
        return self.repo_path is not None

    def _session_journal(self) -> list:
        """Bridge to SEEK's committed session journal (read-only,
        provenance-preserving)."""
        if self.repo_path is None:
            return []
        jroot = Path(self.repo_path)
        candidates = [
            jroot / "research" / "windows_app" /
            "EVIDENCE_MATRIX.json",
            jroot / "SESSION_JOURNAL.md",
        ]
        out = []
        for c in candidates:
            if c.exists():
                out.append({"source": str(c), "exists": True})
        return out

    def execute(self, experiment_id: str, hypothesis: dict,
                params: dict, ctx: dict) -> EngineResult:
        if "network" not in ctx.get("granted", []):
            if self.journal:
                self.journal.append(
                    "engine_experiment_blocked",
                    engine=self.name,
                    experiment_id=experiment_id,
                    reason="network capability not granted")
            return EngineResult(
                engine=self.name, experiment_id=experiment_id,
                disposition="BLOCKED",
                evidence=[{
                    "type": "blocked_state",
                    "observation":
                        "network experiments require the "
                        "`network` capability and exact "
                        "authorized scope; not granted",
                    "interpretation":
                        "blocked honestly - no probe attempted",
                    "confidence": 1.0,
                }],
                controls=[],
                summary="seek adapter online; network capability "
                        "required for live experiments")
        return EngineResult(
            engine=self.name, experiment_id=experiment_id,
            disposition="INCONCLUSIVE",
            evidence=[{
                "type": "journal_bridge",
                "observation":
                    "seek session journals and evidence matrices "
                    "bridged read-only: "
                    f"{self._session_journal()}",
                "interpretation":
                    "external real-world observations owned by "
                    "SEEK provenance; method laws absorbed: "
                    + "; ".join(SEEK_METHOD_LAWS),
                "confidence": 0.9,
            }],
            controls=[],
            summary="seek journals bridged; live network research "
                    "requires exact scope + operator session")

    def validate(self, experiment_id: str) -> dict:
        return {"ok": self.available(),
                "detail": "seek repository present; journal bridge "
                          "ready"}

    def reproduce(self, experiment_id: str, ctx: dict):
        return self.execute(experiment_id + "-repro", {},
                            ctx.get("params", {}), ctx)

    def collect_evidence(self, experiment_id: str) -> list:
        return self._session_journal()

    def export_provenance(self, experiment_id: str) -> dict:
        return {"engine": self.name,
                "experiment_id": experiment_id,
                "external_ownership":
                    "real-world observations remain owned by "
                    "SEEK's own provenance; never re-claimed"}
