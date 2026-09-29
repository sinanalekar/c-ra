"""Git runtime: controlled local Git operations with safety
gates. Never silently pushes, deletes branches, resets
destructive changes, or discards user modifications.

All operations pass the central capability system:
git.read for status/diff/log/branches, git.write for
add/commit/restore/stash/merge/checkout, git.push for fetch/
pull/push (push is high-risk: needs explicit confirm)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .capabilities import AuthorizationError

SAFE_LOCAL = ("status", "diff", "log", "branch", "show",
              "rev-parse", "ls-files", "remote", "config",
              "--get", "stash" " list")


class GitRuntime:
    def __init__(self, capabilities, journal=None):
        self.capabilities = capabilities
        self.journal = journal

    # ------------------------------------------------ plumbing
    def _git(self, repo: str, args: list,
             check: bool = True) -> subprocess.CompletedProcess:
        p = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120)
        if check and p.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed: "
                f"{p.stderr.strip()[:400]}")
        return p

    def discover(self, path: str) -> dict:
        """Repository discovery: is `path` inside a work tree?"""
        p = subprocess.run(
            ["git", "-C", str(path), "rev-parse",
             "--show-toplevel"],
            capture_output=True, text=True, timeout=30)
        if p.returncode == 0:
            return {"is_repo": True,
                    "root": p.stdout.strip()}
        return {"is_repo": False, "root": None}

    def _require_read(self, repo: str):
        d = self.capabilities.authorize(
            "git.read", scope=str(repo))
        if not d["allowed"]:
            raise AuthorizationError(d["reason"])

    def _require_write(self, repo: str):
        d = self.capabilities.authorize(
            "git.write", scope=str(repo))
        if not d["allowed"]:
            raise AuthorizationError(d["reason"])

    # ------------------------------------------------ read ops
    def status(self, repo: str) -> dict:
        self._require_read(repo)
        p = self._git(repo, ["status", "--porcelain=v1", "-b"])
        out = {"raw": p.stdout, "branches": [], "changes": []}
        for line in p.stdout.splitlines():
            if line.startswith("##"):
                out["branch_line"] = line
                parts = line[3:].split("...")
                out["branch"] = parts[0].split(" ")[0]
            else:
                out["changes"].append({
                    "index": line[:1].strip(),
                    "worktree": line[1:2].strip(),
                    "path": line[3:]})
        return out

    def diff(self, repo: str, staged: bool = False,
             pathspec: str = "") -> dict:
        self._require_read(repo)
        args = ["diff"]
        if staged:
            args.append("--cached")
        args += ["--", pathspec] if pathspec else []
        p = self._git(repo, args)
        return {"diff": p.stdout}

    def log(self, repo: str, limit: int = 30) -> dict:
        self._require_read(repo)
        p = self._git(repo, ["log", f"-{limit}",
                            "--pretty=format:%h %ad %an %s",
                            "--date=short"])
        return {"commits": p.stdout.splitlines()}

    def branches(self, repo: str) -> dict:
        self._require_read(repo)
        p = self._git(repo, ["branch", "--list",
                             "--format=%(refname:short) "
                             "%(objectname:short) "
                             "%(HEAD)"])
        out = []
        for line in p.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                out.append({"name": parts[0],
                             "sha": parts[1],
                             "current": parts[-1] == "*"})
        return {"branches": out}

    def remotes(self, repo: str) -> dict:
        self._require_read(repo)
        p = self._git(repo, ["remote", "-v"])
        return {"remotes": p.stdout.splitlines()}

    # ------------------------------------------------ write ops
    def add(self, repo: str, paths: list) -> dict:
        self._require_write(repo)
        self._git(repo, ["add", "--", *paths])
        self._journal("git_add", repo=str(repo),
                      paths=paths[:10])
        return {"added": paths}

    def commit(self, repo: str, message: str) -> dict:
        self._require_write(repo)
        p = self._git(repo, ["commit", "-m", message])
        sha = self._git(repo, ["rev-parse", "HEAD"])
        self._journal("git_commit", repo=str(repo),
                      sha=sha.stdout.strip()[:12])
        return {"commit": p.stdout.strip()[:400],
                "sha": sha.stdout.strip()[:12]}

    def checkout(self, repo: str, ref: str) -> dict:
        """Switch branch / checkout. Refusing to discard local
        modifications: refuses checkout when the work tree is
        dirty unless force is confirmed."""
        self._require_write(repo)
        p = self._git(repo, ["status", "--porcelain"],
                      check=True)
        if p.stdout.strip():
            raise RuntimeError(
                "work tree has modifications; commit or "
                "stash first (CYR@ never discards user "
                "changes silently)")
        self._git(repo, ["checkout", ref])
        self._journal("git_checkout", repo=str(repo), ref=ref)
        return {"checked_out": ref}

    def restore(self, repo: str, paths: list) -> dict:
        """Discard local modifications - high-risk equivalent:
        requires the user's explicit list; never runs against
        the whole tree implicitly."""
        self._require_write(repo)
        d = self.capabilities.authorize(
            "filesystem.delete", scope=str(repo),
            confirm_high_risk=True)
        if not d["allowed"]:
            raise AuthorizationError(d["reason"])
        self._git(repo, ["restore", "--", *paths])
        self._journal("git_restore", repo=str(repo),
                      paths=paths[:10])
        return {"restored": paths}

    def stash(self, repo: str, pop: bool = False) -> dict:
        self._require_write(repo)
        args = ["stash"] + (["pop"] if pop else [])
        p = self._git(repo, args)
        return {"output": p.stdout.strip()[:400]}

    def merge(self, repo: str, ref: str) -> dict:
        self._require_write(repo)
        p = self._git(repo, ["merge", "--no-edit", ref],
                      check=False)
        ok = p.returncode == 0
        self._journal("git_merge", repo=str(repo), ref=ref,
                      ok=ok)
        return {"merged": ok,
                "output": (p.stdout + p.stderr).strip()[:600]}

    # ------------------------------------------------ remote ops
    def fetch(self, repo: str) -> dict:
        d = self.capabilities.authorize(
            "git.push", scope=str(repo))
        if not d["allowed"]:
            raise AuthorizationError(d["reason"])
        p = self._git(repo, ["fetch", "--all"], check=False)
        return {"fetched": p.returncode == 0,
                "output": (p.stdout + p.stderr).strip()[:400]}

    def pull(self, repo: str) -> dict:
        d = self.capabilities.authorize(
            "git.push", scope=str(repo))
        if not d["allowed"]:
            raise AuthorizationError(d["reason"])
        p = self._git(repo, ["pull", "--ff-only"],
                      check=False)
        ok = p.returncode == 0
        self._journal("git_pull", repo=str(repo), ok=ok)
        return {"pulled": ok,
                "output": (p.stdout + p.stderr).strip()[:400]}

    def push(self, repo: str, remote: str = "origin",
             branch: str = "",
             confirm: bool = False) -> dict:
        """Push is HIGH-RISK: requires the git.push grant AND an
        explicit confirmation for THIS push."""
        d = self.capabilities.authorize(
            "git.push", scope=str(repo),
            confirm_high_risk=confirm)
        if not d["allowed"]:
            raise AuthorizationError(d["reason"])
        args = ["push", remote] + ([branch] if branch else [])
        p = self._git(repo, args, check=False)
        ok = p.returncode == 0
        self._journal("git_push", repo=str(repo),
                      remote=remote, ok=ok)
        return {"pushed": ok,
                "output": (p.stdout + p.stderr).strip()[:400]}

    def _journal(self, action: str, **fields):
        if self.journal:
            self.journal.append(action, **fields)
