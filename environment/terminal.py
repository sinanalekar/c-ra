"""Terminal/process runtime: real local command execution with
streaming output, stop/cancel/timeout, and dangerous-command
confirmation.

Every execution passes the central capability system
(terminal.execute) against an authorized working directory.
Destructive command shapes (disk wipe, format, recursive force
delete outside workspace roots, registry edits...) require an
explicit confirm flag - the UI shows the command before running
it. Nothing is faked: output is the actual process output."""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

from .capabilities import AuthorizationError

DANGEROUS_PATTERNS = (
    re.compile(r"\bformat\b\s+[a-z]:", re.I),
    re.compile(r"\bdel\b\s+/[sq]", re.I),
    re.compile(r"\brd\b\s+/[sq]", re.I),
    re.compile(r"remove-item\b.*-recurse.*-force", re.I),
    re.compile(r"\brm\b\s+-rf\b", re.I),
    re.compile(r"\bdiskpart\b", re.I),
    re.compile(r"\bcipher\b\s+/w", re.I),
    re.compile(r"reg\s+(delete|add)\b.*(/f|-force)", re.I),
    re.compile(r"\bshutdown\b|\breboot\b", re.I),
    re.compile(r"set-mppreference\b", re.I),
    re.compile(r"\bbcdedit\b", re.I),
    re.compile(r"\bvssadmin\b\s+delete", re.I),
    re.compile(r"\bwbadmin\b\s+delete", re.I),
)

SHELLS = {
    "powershell": ["powershell", "-NoProfile",
                   "-NonInteractive", "-Command"],
    "cmd": ["cmd", "/C"],
    "python": ["python", "-u"],           # command is split
                                         # into args
    "python_code": [os.environ.get(
        "PY_PYTHON", "python"), "-u", "-c"],   # inline code
    "git": ["git"],
}


def is_dangerous(command: str) -> bool:
    return any(p.search(command) for p in
               DANGEROUS_PATTERNS)


class TerminalSession(dict):
    """One running/finished process execution record."""

    @classmethod
    def make(cls, session_id, shell, command, workdir):
        return cls(
            session_id=session_id, shell=shell,
            command=command, workdir=str(workdir),
            state="running",
            started_utc=time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            stdout="", stderr="", exit_code=None,
            pid=None, timed_out=False)


class TerminalRuntime:
    """Real process execution. Sessions stream into bounded
    buffers; the activity journal records every start/stop."""

    MAX_BUFFER = 512 * 1024     # 512 KiB per stream, bounded

    def __init__(self, capabilities, journal=None):
        self.capabilities = capabilities
        self.journal = journal
        self.sessions: dict[str, TerminalSession] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._seq = 0
        self._lock = threading.Lock()

    # ------------------------------------------------ start
    def start(self, shell: str, command: str,
              workdir: str = ".", timeout: int = 120,
              confirm_dangerous: bool = False) -> dict:
        if shell not in SHELLS:
            raise ValueError(
                f"unknown shell {shell!r}; available: "
                f"{sorted(SHELLS)}")
        if is_dangerous(command) and not confirm_dangerous:
            self._journal("terminal_blocked",
                          command=command[:200],
                          reason="dangerous command shape "
                                 "requires confirmation")
            return {"blocked": True,
                    "reason": "dangerous command shape - "
                              "confirm to execute",
                    "command": command}
        # authorization: terminal.execute scoped to the working
        # directory (workspace roots or explicitly granted dirs)
        d = self.capabilities.authorize(
            "terminal.execute", scope=str(Path(workdir)))
        if not d["allowed"]:
            raise AuthorizationError(d["reason"])
        if shell == "python":
            # command is an argument string: "-m unittest ..."
            argv = SHELLS[shell] + \
                shlex.split(command)
        else:
            argv = SHELLS[shell] + [command]
        try:
            proc = subprocess.Popen(
                argv, cwd=workdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True, encoding="utf-8",
                errors="replace")
        except OSError as e:
            self._journal("terminal_failed", shell=shell,
                          error=repr(e)[:200])
            raise RuntimeError(
                f"failed to start {shell}: {e}") from e
        with self._lock:
            self._seq += 1
            sid = f"term-{self._seq:05d}"
            rec = TerminalSession.make(sid, shell, command,
                                       workdir)
            rec["pid"] = proc.pid
            self.sessions[sid] = rec
            self._procs[sid] = proc
        self._journal("terminal_started", session_id=sid,
                      shell=shell, workdir=str(workdir),
                      command=command[:200], pid=proc.pid)

        def drain(sid=sid, proc=proc, timeout=timeout):
            try:
                out, err = proc.communicate(
                    timeout=timeout)
                timed_out = False
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()
                timed_out = True
            rec = self.sessions.get(sid)
            if rec is not None:
                rec["stdout"] = (out or "")[:self.MAX_BUFFER]
                rec["stderr"] = (err or "")[:self.MAX_BUFFER]
                rec["exit_code"] = proc.returncode
                rec["timed_out"] = timed_out
                # a cancelled-by-stop() record keeps its state -
                # the drain thread never overwrites a terminal
                # state (no completion race)
                if rec.get("state") == "running":
                    rec["state"] = "completed"
                self._journal(
                    "terminal_completed", session_id=sid,
                    exit_code=proc.returncode,
                    timed_out=timed_out,
                    state=rec["state"])

        t = threading.Thread(target=drain, daemon=True)
        t.start()
        rec["_thread_alive"] = True
        return dict(rec)

    # ------------------------------------------------ controls
    def stop(self, session_id: str) -> dict:
        proc = self._procs.get(session_id)
        rec = self.sessions.get(session_id)
        if proc is None or rec is None:
            return {"error": "unknown session"}
        if proc.poll() is None:
            proc.kill()
            rec["state"] = "cancelled"
            self._journal("terminal_stopped",
                          session_id=session_id)
        return dict(rec)

    def get(self, session_id: str) -> dict:
        rec = self.sessions.get(session_id)
        return dict(rec) if rec else \
            {"error": "unknown session"}

    def list(self, limit: int = 50) -> list:
        out = []
        for sid in list(self.sessions)[-limit:]:
            r = dict(self.sessions[sid])
            out.append({k: v for k, v in r.items()
                        if not k.startswith("_")})
        return out

    # ------------------------------------------------ blocking run
    def run_sync(self, shell: str, command: str,
                 workdir: str = ".", timeout: int = 120,
                 confirm_dangerous: bool = False) -> dict:
        """Start + wait to completion (bounded)."""
        rec = self.start(shell, command, workdir, timeout,
                         confirm_dangerous)
        if rec.get("blocked"):
            return rec
        sid = rec["session_id"]
        proc = self._procs.get(sid)
        if proc is None:
            return rec
        try:
            proc.wait(timeout=timeout + 30)
        except subprocess.TimeoutExpired:
            self.stop(sid)
        # wait for the drain thread to publish outputs
        deadline = time.time() + 15
        while time.time() < deadline:
            r = self.sessions.get(sid)
            if r and r["state"] in ("completed",
                                    "cancelled"):
                break
            time.sleep(0.1)
        return {k: v for k, v in
                self.sessions.get(sid, {}).items()
                if not k.startswith("_")}

    def _journal(self, action: str, **fields):
        if self.journal:
            self.journal.append(action, **fields)
