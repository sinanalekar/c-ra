"""Unified artifact system: files, patches, diffs, reports,
logs, experiment results, evidence bundles, generated code,
test results. Every artifact carries an ID, type, content/path
reference, provenance (task/run/agent), timestamp, and a
content hash."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

TYPES = ("file", "patch", "diff", "report", "screenshot",
         "log", "note", "experiment_result", "evidence_bundle",
         "code", "test_result")


class ArtifactStore:
    def __init__(self, root: Path, journal=None):
        self.root = Path(root)
        self.content_dir = self.root / "artifacts"
        self.content_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "artifacts-index.json"
        self.journal = journal
        self._index: list[dict] = []
        self._seq = 0
        self._load()

    def _load(self):
        if self.index_path.exists():
            try:
                data = json.loads(
                    self.index_path.read_text(
                        encoding="utf-8"))
                self._index = data.get("artifacts", [])
                self._seq = data.get("seq", 0)
            except (json.JSONDecodeError, OSError):
                self._index = []

    def _save(self):
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"seq": self._seq,
             "artifacts": self._index[-2000:]},
            indent=1), encoding="utf-8")
        tmp.replace(self.index_path)

    @staticmethod
    def _sha(blob: bytes) -> str:
        return hashlib.sha256(blob).hexdigest()[:32]

    def record(self, artifact_type: str, content: str = "",
               path: str | None = None,
               task_id: str | None = None,
               run_id: str | None = None,
               agent: str | None = None,
               meta: dict | None = None) -> dict:
        if artifact_type not in TYPES:
            raise ValueError(
                f"unknown artifact type {artifact_type!r}")
        self._seq += 1
        aid = f"art-{self._seq:05d}"
        blob = b""
        if path is not None:
            p = Path(path)
            if p.is_file():
                blob = p.read_bytes()
        else:
            blob = content.encode("utf-8")
            # store content-addressed
            cpath = self.content_dir / \
                f"{aid}-{artifact_type}.txt"
            cpath.write_text(content, encoding="utf-8")
            path = str(cpath)
        rec = {
            "artifact_id": aid, "type": artifact_type,
            "path": path, "task_id": task_id,
            "run_id": run_id, "agent": agent,
            "sha256": self._sha(blob),
            "bytes": len(blob),
            "created_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "meta": meta or {},
        }
        self._index.append(rec)
        self._save()
        if self.journal:
            self.journal.append("artifact_recorded",
                                artifact_id=aid,
                                type=artifact_type,
                                sha256=rec["sha256"],
                                task_id=task_id)
        return rec

    def get(self, artifact_id: str) -> dict | None:
        for r in self._index:
            if r["artifact_id"] == artifact_id:
                return dict(r)
        return None

    def read_content(self, artifact_id: str) -> dict:
        rec = self.get(artifact_id)
        if rec is None:
            return {"error": "unknown artifact"}
        p = Path(rec["path"])
        if not p.is_file():
            return {"error": "content file missing"}
        blob = p.read_bytes()
        integrity = self._sha(blob) == rec["sha256"]
        return {"artifact": rec, "integrity": integrity,
                "content": blob.decode(
                    "utf-8", errors="replace")[:200000]}

    def list(self, artifact_type: str | None = None,
             task_id: str | None = None,
             limit: int = 100) -> list:
        out = [dict(r) for r in self._index
               if (artifact_type is None or
                   r["type"] == artifact_type) and
               (task_id is None or
                r["task_id"] == task_id)]
        return out[-limit:]
