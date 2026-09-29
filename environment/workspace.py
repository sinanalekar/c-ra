"""Workspace manager: permission-gated local file operations
(read/write/create/delete/search/rename), each mediated by the
least-privilege layer."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


class WorkspaceError(RuntimeError):
    pass


class Workspace:
    """All paths are confined to the workspace root - path
    traversal attempts are rejected, not sandbox-escaped."""

    def __init__(self, root, permissions, journal=None):
        self.root = Path(root).resolve()
        self.permissions = permissions
        self.journal = journal

    def _resolve(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if not str(p).startswith(str(self.root)):
            raise WorkspaceError(
                f"path escapes workspace: {rel!r}")
        return p

    @staticmethod
    def _sha(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(
                    lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:32]

    def read(self, rel: str) -> dict:
        self.permissions.require("workspace_read")
        p = self._resolve(rel)
        if not p.is_file():
            return {"error": "not found"}
        return {"path": rel, "content": p.read_text(
            encoding="utf-8", errors="replace")}

    def write(self, rel: str, content: str) -> dict:
        self.permissions.require("workspace_write")
        p = self._resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        if self.journal:
            self.journal.append(
                "workspace_write", path=rel,
                sha256=self._sha(p))
        return {"path": rel, "written": True,
                "sha256": self._sha(p)}

    def create(self, rel: str, content: str = "") -> dict:
        return self.write(rel, content)

    def delete(self, rel: str) -> dict:
        self.permissions.require("file_delete")
        p = self._resolve(rel)
        if p.is_file():
            p.unlink()
            if self.journal:
                self.journal.append(
                    "workspace_delete", path=rel)
            return {"path": rel, "deleted": True}
        return {"error": "not found"}

    def rename(self, src: str, dst: str) -> dict:
        self.permissions.require("workspace_write")
        s = self._resolve(src)
        d = self._resolve(dst)
        s.rename(d)
        return {"src": src, "dst": dst, "renamed": True}

    def search(self, query: str, sub: str = "") -> list:
        self.permissions.require("workspace_read")
        base = self._resolve(sub) if sub else self.root
        out = []
        q = query.lower()
        for p in base.rglob("*"):
            if p.is_file():
                try:
                    if q in p.read_text(
                            encoding="utf-8",
                            errors="ignore").lower():
                        out.append(str(
                            p.relative_to(
                                self.root)).replace(
                            "\\", "/"))
                except OSError:
                    continue
        return out[:100]

    def tree(self, sub: str = "") -> list:
        self.permissions.require("workspace_read")
        base = self._resolve(sub) if sub else self.root
        out = []
        for p in sorted(base.rglob("*")):
            rel = str(p.relative_to(self.root))
            out.append({
                "path": rel.replace("\\", "/"),
                "dir": p.is_dir(),
                "size": (p.stat().st_size
                         if p.is_file() else None),
            })
            if len(out) >= 500:
                break
        return out
