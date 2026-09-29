"""Local persistent memory with bounded, relevant retrieval.

Separate stores: session, task, project, persistent (user-
approved), research. Secrets never enter memory (the writer
redacts obvious key/token shapes). The user can inspect and
remove any entry. Retrieval is keyword-relevance bounded - the
full history is never injected into model calls."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

KINDS = ("session", "task", "project", "persistent",
         "research")

MAX_PER_KIND = 500

_SECRET = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|Bearer\s+[A-Za-z0-9._-]{8,}|"
    r"api[_-]?key\s*[:=]\s*\S+|"
    r"password\s*[:=]\s*\S+)", re.I)


def redact(text: str) -> str:
    return _SECRET.sub("[REDACTED]", text)


class MemoryStore:
    def __init__(self, root: Path, journal=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.journal = journal
        self._data: dict[str, list[dict]] = \
            {k: [] for k in KINDS}
        self._load()

    def _path(self, kind: str) -> Path:
        return self.root / f"memory-{kind}.json"

    def _load(self):
        for kind in KINDS:
            p = self._path(kind)
            if p.exists():
                try:
                    self._data[kind] = json.loads(
                        p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    self._data[kind] = []

    def _save(self, kind: str):
        p = self._path(kind)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            self._data[kind], indent=1), encoding="utf-8")
        tmp.replace(p)

    # ------------------------------------------------ write
    def remember(self, kind: str, text: str,
                 task_id: str | None = None,
                 key: str = "") -> dict:
        if kind not in KINDS:
            raise ValueError(
                f"unknown memory kind {kind!r}")
        text = redact(text)
        rec = {"id": f"mem-{kind[:2]}-"
                     f"{int(time.time()*1000)%10**9:09d}",
               "kind": kind, "text": text,
               "task_id": task_id, "key": key,
               "ts": time.strftime(
                   "%Y-%m-%dT%H:%M:%SZ",
                   time.gmtime())}
        self._data[kind].append(rec)
        if len(self._data[kind]) > MAX_PER_KIND:
            self._data[kind] = \
                self._data[kind][-MAX_PER_KIND // 2:]
        self._save(kind)
        if self.journal:
            self.journal.append("memory_written",
                                kind=kind,
                                task_id=task_id)
        return rec

    # ------------------------------------------------ retrieval
    def recall(self, query: str = "",
               kind: str | None = None,
               task_id: str | None = None,
               limit: int = 10) -> list:
        """Bounded keyword-relevance retrieval."""
        words = [w.lower() for w in
                 re.findall(r"\w{3,}", query)]
        pools = [self._data[kind]] if kind in KINDS \
            else [self._data[k] for k in KINDS]
        scored = []
        for pool in pools:
            for rec in pool:
                if task_id and \
                        rec.get("task_id") != task_id:
                    continue
                text = (rec["text"] + " " +
                        rec.get("key", "")).lower()
                score = sum(1 for w in words
                            if w in text)
                if not words or score > 0:
                    scored.append((score, rec))
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in
                scored[:limit]]

    # ------------------------------------------------ management
    def inspect(self, kind: str | None = None) -> dict:
        if kind:
            return {kind: self._data.get(kind, [])}
        return {k: len(v)
                for k, v in self._data.items()}

    def remove(self, memory_id: str) -> dict:
        for kind in KINDS:
            before = len(self._data[kind])
            self._data[kind] = [r for r in
                                self._data[kind]
                                if r["id"] != memory_id]
            if len(self._data[kind]) < before:
                self._save(kind)
                if self.journal:
                    self.journal.append(
                        "memory_removed",
                        memory_id=memory_id)
                return {"removed": memory_id}
        return {"error": "not found"}

    def clear_task(self, task_id: str) -> int:
        n = 0
        for kind in KINDS:
            before = len(self._data[kind])
            self._data[kind] = [
                r for r in self._data[kind]
                if r.get("task_id") != task_id]
            n += before - len(self._data[kind])
            if before != len(self._data[kind]):
                self._save(kind)
        return n
