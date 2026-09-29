"""Evidence system: evidence as a first-class data model with
IDs, provenance, timestamps, hashes, relationships, confidence,
and reproduction status. Independent review and falsification
consume these records. Never stores secrets (redacted)."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from .memory import redact

EVIDENCE_TYPES = (
    "observation", "command_output", "source_document",
    "screenshot", "trace", "reproduction",
    "experiment_result", "log", "file_hash",
    "code_location", "negative_control",
)

STATES = ("OBSERVED", "CORROBORATED", "SUPPORTED",
          "REPRODUCED", "VALIDATED")


class EvidenceStore:
    def __init__(self, root: Path, journal=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / \
            "evidence-index.json"
        self.journal = journal
        self._index: list[dict] = []
        self._load()

    def _load(self):
        if self.index_path.exists():
            try:
                data = json.loads(
                    self.index_path.read_text(
                        encoding="utf-8"))
                self._index = data.get("evidence", [])
            except (json.JSONDecodeError, OSError):
                self._index = []

    def _save(self):
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"evidence": self._index[-5000:]},
            indent=1), encoding="utf-8")
        tmp.replace(self.index_path)

    @staticmethod
    def _sha(text: str) -> str:
        return hashlib.sha256(
            text.encode("utf-8")).hexdigest()[:32]

    def record(self, evidence_type: str,
               observation: str, task_id: str | None = None,
               source: str = "",
               confidence: float = 0.5,
               relates_to: list | None = None,
               meta: dict | None = None) -> dict:
        if evidence_type not in EVIDENCE_TYPES:
            raise ValueError(
                f"unknown evidence type "
                f"{evidence_type!r}")
        eid = "ev-%s" % self._sha(
            observation + str(time.time()))[:16]
        rec = {
            "evidence_id": eid,
            "type": evidence_type,
            "observation": redact(observation)[:10000],
            "source": redact(source)[:300],
            "task_id": task_id,
            "ts": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sha256": self._sha(observation),
            "confidence": confidence,
            "state": "OBSERVED",
            "reproduction_status": "not_reproduced",
            "relates_to": relates_to or [],
            "meta": meta or {},
        }
        self._index.append(rec)
        self._save()
        if self.journal:
            self.journal.append("evidence_recorded",
                                evidence_id=eid,
                                type=evidence_type,
                                task_id=task_id)
        return rec

    def corroborate(self, evidence_id: str) -> dict:
        return self._promote(evidence_id,
                             "CORROBORATED")

    def mark_reproduced(self, evidence_id: str) -> dict:
        rec = self._promote(evidence_id, "REPRODUCED")
        if "error" not in rec:
            rec["reproduction_status"] = "reproduced"
        return rec

    def _promote(self, evidence_id: str, state: str) -> dict:
        order = {s: i for i, s in
                 enumerate(STATES)}
        for rec in self._index:
            if rec["evidence_id"] == evidence_id:
                if order[state] < order[
                        rec["state"]]:
                    return {"error": "cannot demote "
                                      "evidence state"}
                rec["state"] = state
                self._save()
                if self.journal:
                    self.journal.append(
                        "evidence_promoted",
                        evidence_id=evidence_id,
                        state=state)
                return dict(rec)
        return {"error": "unknown evidence"}

    def get(self, evidence_id: str) -> dict | None:
        for rec in self._index:
            if rec["evidence_id"] == evidence_id:
                return dict(rec)
        return None

    def list(self, task_id: str | None = None,
             evidence_type: str | None = None,
             limit: int = 100) -> list:
        out = [dict(r) for r in self._index
               if (task_id is None or
                   r["task_id"] == task_id) and
               (evidence_type is None or
                r["type"] == evidence_type)]
        return out[-limit:]

    def stats(self) -> dict:
        by_state: dict[str, int] = {}
        for r in self._index:
            by_state[r["state"]] = \
                by_state.get(r["state"], 0) + 1
        return {"total": len(self._index),
                "by_state": by_state,
                "monotonic_states": list(STATES)}
