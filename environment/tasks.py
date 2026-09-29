"""Long-running task engine: durable tasks, checkpoints,
pause/resume/stop/redirect, and restart recovery.

Task states: queued | planning | running | waiting_for_user |
paused | blocked | recovering | completed | failed | cancelled.

Persistence: every state transition, event, and checkpoint is
written to disk (tasks/<id>.json + events/<id>.jsonl) BEFORE it
is reported, so closing the UI never destroys task state. On
boot, `recover()` marks interrupted running tasks as
`recovering` with their last checkpoint - the Recovery Agent can
resume them."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


STATES = ("queued", "planning", "running",
          "waiting_for_user", "paused", "blocked",
          "recovering", "completed", "failed",
          "cancelled")


class TaskError(RuntimeError):
    pass


class Task:
    """One durable task record."""

    def __init__(self, task_id: str, objective: str,
                 store: "TaskStore", workspace: str = "*"):
        self.store = store
        self.data = {
            "task_id": task_id,
            "objective": objective,
            "workspace": workspace,
            "state": "queued",
            "created_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updated_utc": self.data_ts(),
            "plan": [],
            "steps": [],
            "current_step": None,
            "checkpoints": [],
            "artifacts": [],
            "events": [],
            "model_override": None,
            "agents": [],
            "parent": None,
            "error": None,
        }

    @staticmethod
    def data_ts():
        return time.strftime("%Y-%m-%dT%H:%M:%SZ",
                             time.gmtime())

    # ------------------------------------------------ transitions
    VALID = {
        "queued": {"planning", "running", "cancelled"},
        "planning": {"running", "cancelled", "failed"},
        "running": {"paused", "waiting_for_user", "blocked",
                    "completed", "failed", "cancelled"},
        "waiting_for_user": {"running", "paused",
                             "cancelled"},
        "paused": {"running", "cancelled"},
        "blocked": {"running", "cancelled", "failed"},
        "recovering": {"running", "paused", "cancelled",
                       "failed"},
        "completed": set(),
        "failed": {"recovering"},
        "cancelled": set(),
    }

    def transition(self, new_state: str, reason: str = ""):
        if new_state not in STATES:
            raise TaskError(f"unknown state {new_state!r}")
        allowed = self.VALID.get(self.data["state"], set())
        if new_state not in allowed:
            raise TaskError(
                f"invalid transition "
                f"{self.data['state']} -> {new_state}")
        self.data["state"] = new_state
        self.data["updated_utc"] = self.data_ts()
        if reason:
            self.data["error"] = reason
        self.store._persist(self)
        self.store._journal(
            "task_transition",
            task_id=self.data["task_id"],
            state=new_state, reason=reason[:200])

    def event(self, kind: str, detail: str = "", **fields):
        rec = {"ts": self.data_ts(), "kind": kind,
               "detail": str(detail)[:500]}
        rec.update(fields)
        self.data["events"].append(rec)
        if len(self.data["events"]) > 2000:
            self.data["events"] = \
                self.data["events"][-1000:]
        self.store._persist(self)
        self.store._journal("task_event",
                            task_id=self.data["task_id"],
                            kind=kind)

    def checkpoint(self, label: str, payload: dict) -> dict:
        rec = {"ts": self.data_ts(), "label": label,
               "payload": payload}
        self.data["checkpoints"].append(rec)
        if len(self.data["checkpoints"]) > 100:
            self.data["checkpoints"] = \
                self.data["checkpoints"][-50:]
        self.store._persist(self)
        self.store._journal(
            "task_checkpoint",
            task_id=self.data["task_id"], label=label)
        return rec

    def artifact(self, artifact_id: str) -> None:
        self.data["artifacts"].append(artifact_id)
        self.store._persist(self)

    def as_dict(self) -> dict:
        return dict(self.data)


class TaskStore:
    """Durable task persistence + recovery."""

    def __init__(self, root: Path, journal=None):
        self.root = Path(root)
        self.tasks_dir = self.root / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.journal = journal
        self.tasks: dict[str, Task] = {}
        self._seq = 0
        self._lock = threading.Lock()

    # ------------------------------------------------ lifecycle
    def create(self, objective: str,
               workspace: str = "*") -> Task:
        with self._lock:
            self._seq += 1
            tid = f"task-{time.strftime('%Y%m%d')}-" \
                  f"{self._seq:04d}"
            t = Task(tid, objective, self, workspace)
            self.tasks[tid] = t
            self._persist(t)
            self._journal("task_created", task_id=tid,
                          objective=objective[:200])
            return t

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def list(self, limit: int = 100) -> list:
        return [t.as_dict()
                for _, t in
                sorted(self.tasks.items())[-limit:]]

    # ------------------------------------------------ recovery
    def recover(self) -> dict:
        """Boot-time recovery: tasks persisted as running/
        planning/waiting_for_user from a previous session are
        marked `recovering` with their last checkpoint noted -
        never silently completed."""
        recovered = []
        for tid, t in self.tasks.items():
            if t.data["state"] in ("running", "planning",
                                   "waiting_for_user"):
                was = t.data["state"]
                t.data["state"] = "recovering"
                t.data["updated_utc"] = Task.data_ts()
                t.data["error"] = (
                    "interrupted by restart; last checkpoint: "
                    + (t.data["checkpoints"][-1]["label"]
                       if t.data["checkpoints"]
                       else "none"))
                self._persist(t)
                self._journal("task_recovered", task_id=tid,
                              was=was)
                recovered.append({"task_id": tid, "was": was})
        return {"recovered": recovered,
                "total": len(self.tasks)}

    def load(self) -> int:
        """Load persisted tasks from disk (start of session)."""
        n = 0
        for p in sorted(
                self.tasks_dir.glob("task-*.json")):
            try:
                data = json.loads(
                    p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            tid = data.get("task_id")
            if not tid:
                continue
            t = Task(tid, data.get("objective", ""),
                     self, data.get("workspace", "*"))
            t.data = data
            self.tasks[tid] = t
            try:
                seq = int(tid.split("-")[-1])
                self._seq = max(self._seq, seq)
            except ValueError:
                pass
            n += 1
        return n

    # ------------------------------------------------ persistence
    def _persist(self, task: Task):
        self.tasks_dir.mkdir(parents=True,
                             exist_ok=True)
        path = self.tasks_dir / \
            f"{task.data['task_id']}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            task.data, indent=1, sort_keys=True),
            encoding="utf-8")
        tmp.replace(path)     # atomic-ish durability

    def _journal(self, action: str, **fields):
        if self.journal:
            self.journal.append(action, **fields)
