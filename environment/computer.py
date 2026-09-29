"""Computer-use abstraction: authorized local application
interaction.

What actually works here today (Windows, via real processes):
- launch applications (computer.interact; every launch is
  audited)
- read the screen state honestly: capability reported, but
  keyboard/mouse injection is NOT implemented - reported
  unavailable, never faked.

Everything passes the central capability system. Nothing grants
itself unrestricted control."""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .capabilities import AuthorizationError

LAUNCHABLE_HINTS = {
    "notepad": "notepad.exe",
    "calc": "calc.exe",
    "explorer": "explorer.exe",
}


class ComputerRuntime:
    def __init__(self, capabilities, journal=None):
        self.capabilities = capabilities
        self.journal = journal
        self._actions: list[dict] = []

    def capability_status(self) -> dict:
        return {
            "launch_applications": True,
            "inspect_processes": True,
            "keyboard_input": False,
            "mouse_input": False,
            "screenshots": False,
            "window_focusing": False,
            "ui_interaction": False,
            "note": "keyboard/mouse injection and screen "
                    "capture are not implemented; reported "
                    "unavailable - never faked",
        }

    # ------------------------------------------------ launch
    def launch(self, app: str, args: str = "",
               confirm: bool = False) -> dict:
        """Launch an application. Requires computer.interact
        (high-risk): the caller must pass the user's explicit
        confirmation - the runtime never self-confirms."""
        d = self.capabilities.authorize(
            "computer.interact", scope=app,
            confirm_high_risk=confirm)
        if not d["allowed"]:
            raise AuthorizationError(d["reason"])
        exe = LAUNCHABLE_HINTS.get(app.lower(), app)
        argv = [exe] + ([args] if args else [])
        try:
            proc = subprocess.Popen(argv)
        except OSError as e:
            self._journal("computer_launch_failed",
                          app=app, error=repr(e)[:200])
            return {"error": f"failed to launch {app}: {e}"}
        rec = {"app": app, "pid": proc.pid,
               "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                   time.gmtime())}
        self._actions.append(rec)
        self._journal("computer_launched", app=app,
                      pid=proc.pid)
        return rec

    # ------------------------------------------------ inspect
    def processes(self, name_filter: str = "") -> list:
        """Authorized process listing (computer.read)."""
        d = self.capabilities.authorize("computer.read")
        if not d["allowed"]:
            raise AuthorizationError(d["reason"])
        out = []
        for line in subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process | Select-Object "
                 "ProcessName, Id | "
                 "ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=60
        ).stdout.splitlines():
            out.append(line.strip())
        try:
            import json
            data = json.loads("".join(out) or "[]")
            procs = [{"name": p["ProcessName"],
                      "pid": p["Id"]}
                     for p in (data if isinstance(
                         data, list) else [data])]
            if name_filter:
                procs = [p for p in procs
                         if name_filter.lower()
                         in p["name"].lower()]
            self._journal("computer_processes_listed",
                          count=len(procs))
            return procs[:500]
        except Exception:
            return []

    # ------------------------------------------------ honest gaps
    def keyboard(self, text: str) -> dict:
        self._journal("computer_input_unavailable",
                      kind="keyboard")
        return {"error": "keyboard input not implemented; "
                         "reported honestly"}

    def mouse(self, action: str) -> dict:
        self._journal("computer_input_unavailable",
                      kind="mouse")
        return {"error": "mouse input not implemented; "
                         "reported honestly"}

    def screenshot(self, path: str = "") -> dict:
        self._journal("computer_input_unavailable",
                      kind="screenshot")
        return {"error": "screen capture not implemented; "
                         "reported honestly"}

    def actions(self) -> list:
        return list(self._actions)

    def _journal(self, action: str, **fields):
        if self.journal:
            self.journal.append(action, **fields)
