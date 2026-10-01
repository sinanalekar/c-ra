"""Abort + steer tests: the chat turn cooperatively aborts
between intents and consumes steering text queued mid-turn."""
import tempfile
import threading
import time
import unittest

from environment.app import Environment
from environment.chat import ChatEngine


def make_env(tmp):
    env = Environment(tmp)
    for cap in ("terminal.execute", "git.read",
                "research.execute", "engine.cider",
                "filesystem.read", "filesystem.write"):
        env.capabilities.grant(cap, "allow_session")
    return env


class TestAbortSteer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = make_env(self.tmp)
        self.chat = ChatEngine(self.env)
        self.task = self.env.taskstore.create(
            "abort/steer test")

    def test_steer_consumed_within_turn(self):
        tid = self.task.data["task_id"]
        # queue a steer BEFORE the turn starts (processed
        # between the turn's intents)
        t = self.env.taskstore.get(tid)
        t.data["steer_queue"] = [
            "also run print('steered-ran')"]
        self.env.taskstore._persist(t)
        out = self.chat.turn(
            tid, "run print('first')")
        reply = out["assistant"]["content"]
        self.assertIn("Steered mid-turn", reply)
        # the steer actually executed
        term_cards = [a for a in out["activity"]
                      if a["type"] == "terminal"]
        outputs = " ".join(
            (a.get("output") or "") for a in
            term_cards)
        self.assertIn("steered-ran", outputs)
        # the queue is drained
        t2 = self.env.taskstore.get(tid)
        self.assertEqual(
            t2.data.get("steer_queue", []), [])

    def test_abort_between_intents(self):
        tid = self.task.data["task_id"]
        result = {}

        def runner():
            result["out"] = self.chat.turn(
                tid,
                "run print('a') and then show git "
                "status and then research the "
                "WebKit target")

        t = threading.Thread(target=runner)
        t.start()
        # abort lands while the turn is running
        time.sleep(0.4)
        self.chat.env.orchestrator  # touch
        task = self.env.taskstore.get(tid)
        try:
            task.transition("cancelled",
                             "aborted by user")
        except Exception:
            pass
        t.join(timeout=30)
        self.assertFalse(t.is_alive())
        reply = result["out"]["assistant"]["content"]
        self.assertIn("Turn aborted", reply)
        # work before the abort still recorded
        self.assertTrue(any(
            a["type"] == "terminal"
            for a in result["out"]["activity"]))

    def test_abort_endpoint_and_reopen(self):
        from fastapi.testclient import TestClient
        from environment.app import create_app
        client = TestClient(create_app(self.env))
        tid = self.task.data["task_id"]
        r = client.post(f"/api/tasks/{tid}/abort",
                        json={})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["aborted"])
        # a new turn reopens the task
        out = self.chat.turn(tid, "hello")
        task = self.env.taskstore.get(tid)
        self.assertEqual(task.data["state"],
                         "running")

    def test_steer_endpoint(self):
        from fastapi.testclient import TestClient
        from environment.app import create_app
        client = TestClient(create_app(self.env))
        tid = self.task.data["task_id"]
        r = client.post(
            f"/api/tasks/{tid}/steer",
            json={"text": "check the logs again"})
        self.assertEqual(r.status_code, 200)
        task = self.env.taskstore.get(tid)
        self.assertIn("check the logs again",
                      task.data["steer_queue"])


if __name__ == "__main__":
    unittest.main()
