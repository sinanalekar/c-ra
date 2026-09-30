"""Chat engine tests: the primary CYR@ experience - one user
message -> real tool execution -> honest reply composition,
message persistence, and model routing."""
import tempfile
import unittest
from pathlib import Path

from environment.app import Environment
from environment.chat import ChatEngine, ChatStore


def make_env(tmp):
    env = Environment(tmp)
    for cap in ("terminal.execute", "git.read",
                "filesystem.read", "filesystem.write",
                "research.execute", "engine.cider"):
        env.capabilities.grant(cap, "allow_session")
    return env


class TestChatEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = make_env(self.tmp)
        self.chat = ChatEngine(self.env)
        self.task = self.env.taskstore.create(
            "chat test task")

    def _turn(self, text):
        return self.chat.turn(
            self.task.data["task_id"], text)

    def test_terminal_intent_executes_for_real(self):
        out = self._turn('run print("hello-chat")')
        self.assertEqual(len(out["user"]["content"]),
                         len('run print("hello-chat")'))
        reply = out["assistant"]["content"]
        self.assertIn("exit 0", reply)
        # the terminal card carries REAL output
        cards = out["activity"]
        term = [c for c in cards
                if c["type"] == "terminal"]
        self.assertTrue(term)
        self.assertIn("hello-chat",
                      term[0]["output"])

    def test_permission_request_card_not_silent(self):
        self.env.capabilities.revoke("terminal.execute")
        out = self._turn("run echo hi")
        perm = [c for c in out["activity"]
                if c["type"] == "permission_request"]
        self.assertTrue(perm)
        self.assertEqual(
            perm[0]["capability"],
            "terminal.execute")
        self.assertIn("authorization",
                      out["assistant"]["content"])

    def test_git_intent_real_status(self):
        out = self._turn("show git status")
        cards = [c for c in out["activity"]
                 if c["type"] == "git_status"]
        self.assertTrue(cards)
        self.assertIn("git card",
                      out["assistant"]["content"])

    def test_messages_persist_across_engine_instances(self):
        self._turn("run print('persist-me')")
        store2 = ChatStore(
            Path(self.tmp) / "workspace")
        msgs = store2.messages(
            self.task.data["task_id"])
        roles = [m["role"] for m in msgs]
        self.assertEqual(roles,
                         ["user", "assistant"])

    def test_security_intent_runs_research_loop(self):
        out = self._turn(
            "research the WebKit target")
        cards = [c for c in out["activity"]
                 if c["type"] == "research"]
        self.assertTrue(cards)
        self.assertIn(cards[0]["disposition"],
                      ("SUPPORTED", "REFUTED",
                       "INCONCLUSIVE", "BLOCKED"))

    def test_local_mode_is_labeled(self):
        out = self._turn("what can you do")
        self.assertEqual(out["assistant"]["mode"],
                         "LOCAL")
        self.assertIn("LOCAL mode",
                      out["assistant"]["content"])

    def test_task_model_binding(self):
        tid = self.task.data["task_id"]
        self.chat.turn(tid, "hello",
                       model={"provider": "none",
                              "model_id": "m0"})
        task = self.env.taskstore.get(tid)
        self.assertEqual(
            task.data["model"]["model_id"], "m0")
        # unconfigured provider -> honest LOCAL fallback
        out = self.chat.turn(tid, "hello again")
        self.assertEqual(out["assistant"]["mode"],
                         "LOCAL")

    def test_unknown_task(self):
        out = self.chat.turn("task-nope", "hi")
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
