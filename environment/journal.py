"""Environment-level provenance: a tamper-evident hash-chained
journal recording every major state transition (session start,
authorization decisions, experiment dispatch, evidence, gate
verdicts, dispositions). Mirrors the VERITAS engine's journal
discipline; never silently modifies historical records."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


class Journal:
    def __init__(self, path):
        self.path = Path(path)
        self.head = None
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                self.head = rec["hash"]

    @staticmethod
    def _record_hash(rec: dict, prev: str | None) -> str:
        payload = {k: rec[k] for k in sorted(rec)
                   if k != "hash"}
        payload["prev"] = prev or ""
        blob = json.dumps(payload, sort_keys=True,
                          separators=(",", ":"))
        return hashlib.sha256(blob.encode()).hexdigest()[:40]

    def append(self, action: str, **fields) -> dict:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                time.gmtime()),
            "action": action,
            **fields,
        }
        rec["prev"] = self.head
        rec["hash"] = self._record_hash(rec, self.head)
        self.head = rec["hash"]
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec

    def entries(self, limit: int | None = None) -> list:
        out = []
        if not self.path.exists():
            return out
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out[-limit:] if limit else out

    def verify(self) -> dict:
        """Fail-closed chain verification."""
        prev = None
        n = 0
        problems = []
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    if rec.get("prev") != prev:
                        problems.append(
                            {"index": n,
                             "problem": "prev-mismatch"})
                    if self._record_hash(rec, prev) != rec["hash"]:
                        problems.append(
                            {"index": n,
                             "problem": "hash-mismatch"})
                    prev = rec["hash"]
                    n += 1
        if prev != self.head:
            problems.append({"problem": "head-mismatch"})
        return {"entries": n, "problems": problems,
                "head": self.head,
                "valid": not problems}
