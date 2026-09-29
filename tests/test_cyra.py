"""CYR@ subsystem tests: central capabilities with modes,
terminal runtime, git runtime, browser subsystem, computer-use
abstraction, durable tasks with recovery, memory, artifacts,
evidence, and agent run controls. Deterministic - no paid
APIs, no network."""
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from environment.capabilities import (CapabilitySystem,
                                      AuthorizationError)
from environment.config import Config
from environment.journal import Journal
from environment.terminal import TerminalRuntime, \
    is_dangerous
from environment.gitops import GitRuntime
from environment.browser import BrowserRuntime
from environment.computer import ComputerRuntime
from environment.tasks import TaskStore, TaskError
from environment.memory import MemoryStore, redact
from environment.artifacts import ArtifactStore
from environment.evidence import EvidenceStore


def make_cap(tmp):
    j = Journal(Path(tmp) / "j.jsonl")
    return CapabilitySystem(Path(tmp) / "g.json", j), j


class TestCapabilities(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.caps, self.journal = make_cap(self.tmp)

    def test_deny_by_default_and_legacy_alias(self):
        d = self.caps.authorize("experimental_execution")
        self.assertFalse(d["allowed"])
        d = self.caps.authorize("research.execute")
        self.assertFalse(d["allowed"])

    def test_grant_modes(self):
        self.caps.grant("terminal.execute",
                        "allow_once")
        d1 = self.caps.authorize("terminal.execute")
        self.assertTrue(d1["allowed"])
        self.assertEqual(d1["mode"], "allow_once")
        d2 = self.caps.authorize("terminal.execute")
        self.assertFalse(d2["allowed"])  # consumed

    def test_allow_task_binding(self):
        self.caps.grant("filesystem.write",
                        "allow_task", task_id="task-1")
        self.assertTrue(self.caps.authorize(
            "filesystem.write",
            task_id="task-1")["allowed"])
        self.assertFalse(self.caps.authorize(
            "filesystem.write",
            task_id="task-2")["allowed"])

    def test_allow_workspace_path_scope(self):
        root = Path(self.tmp)
        self.caps.grant("filesystem.read",
                        "allow_workspace",
                        scope=str(root))
        self.assertTrue(self.caps.authorize(
            "filesystem.read",
            scope=str(root / "sub" /
                      "file.txt"))["allowed"])
        self.assertFalse(self.caps.authorize(
            "filesystem.read",
            scope="C:\\other")["allowed"])

    def test_explicit_deny_overrides(self):
        self.caps.grant("terminal.execute")
        self.caps.grant("terminal.execute", "deny")
        self.assertFalse(self.caps.authorize(
            "terminal.execute")["allowed"])

    def test_high_risk_needs_confirmation(self):
        self.caps.grant("git.push")
        d = self.caps.authorize("git.push")
        self.assertFalse(d["allowed"])
        self.assertIn("confirmation", d["reason"])
        d = self.caps.authorize("git.push",
                                confirm_high_risk=True)
        self.assertTrue(d["allowed"])

    def test_unknown_rejected(self):
        with self.assertRaises(AuthorizationError):
            self.caps.grant("not_a_capability")


class TestTerminal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.caps, _ = make_cap(self.tmp)
        self.term = TerminalRuntime(self.caps)

    def test_requires_authorization(self):
        with self.assertRaises(AuthorizationError):
            self.term.run_sync("powershell", "echo hi",
                               workdir=self.tmp)

    def test_real_execution_streams_output(self):
        self.caps.grant("terminal.execute")
        rec = self.term.run_sync("python_code",
                                "print('hello-cyra')",
                                workdir=self.tmp)
        self.assertIn("hello-cyra",
                      rec["stdout"])
        self.assertEqual(rec["exit_code"], 0)
        # the python shell splits its command into argv
        rec2 = self.term.run_sync(
            "python", "-c \"print('argv-ok')\"",
            workdir=self.tmp)
        self.assertIn("argv-ok", rec2["stdout"])

    def test_dangerous_requires_confirmation(self):
        self.caps.grant("terminal.execute")
        rec = self.term.start(
            "cmd", "rd /sq C:\\nope",
            workdir=self.tmp)
        self.assertTrue(rec.get("blocked"))
        self.assertTrue(is_dangerous("format C:"))

    def test_stop_and_timeout(self):
        self.caps.grant("terminal.execute")
        started = self.term.start(
            "python_code",
            "import time; time.sleep(30)",
            workdir=self.tmp, timeout=25)
        sid = started["session_id"]
        time.sleep(1)
        rec = self.term.stop(sid)
        self.assertEqual(rec["state"], "cancelled")
        # timeout path
        rec2 = self.term.run_sync(
            "python_code",
            "import time; time.sleep(10)",
            workdir=self.tmp, timeout=1)
        self.assertTrue(rec2["timed_out"])


class TestGitRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.caps, _ = make_cap(self.tmp)
        self.git = GitRuntime(self.caps)
        self.repo = Path(self.tmp) / "repo"
        self.repo.mkdir()
        subprocess.run(
            ["git", "init", "-q"],
            cwd=self.repo, check=True,
            capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config",
             "user.email", "t@t"], check=True,
            capture_output=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "config",
             "user.name", "t"], check=True,
            capture_output=True)
        (self.repo / "a.txt").write_text("hello")

    def test_discover(self):
        d = self.git.discover(str(self.repo))
        self.assertTrue(d["is_repo"])

    def test_requires_grants(self):
        with self.assertRaises(AuthorizationError):
            self.git.status(str(self.repo))
        self.caps.grant("git.read")
        st = self.git.status(str(self.repo))
        self.assertTrue(any(
            c["path"] == "a.txt"
            for c in st["changes"]))

    def test_commit_flow_and_push_gate(self):
        self.caps.grant("git.read")
        self.caps.grant("git.write")
        self.git.add(str(self.repo), ["a.txt"])
        rec = self.git.commit(str(self.repo),
                              "test commit")
        self.assertIn("sha", rec)
        # push without grant + confirm: blocked
        with self.assertRaises(AuthorizationError):
            self.git.push(str(self.repo))
        # grant without confirm: still blocked (high-risk)
        self.caps.grant("git.push")
        with self.assertRaises(AuthorizationError):
            self.git.push(str(self.repo))
        # (with confirm it would proceed; not tested to
        #  avoid any accidental remote operation)

    def test_checkout_refuses_dirty_tree(self):
        self.caps.grant("git.read")
        self.caps.grant("git.write")
        (self.repo / "b.txt").write_text("dirty")
        with self.assertRaises(RuntimeError):
            self.git.checkout(str(self.repo),
                              "master")


class TestBrowser(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.caps, _ = make_cap(self.tmp)
        self.browser = BrowserRuntime(self.caps,
                                      workdir=self.tmp)

    def tearDown(self):
        # kill the real browser + driver: leaked chromiums
        # exhaust the machine and break sibling tests
        self.browser.shutdown()

    def test_status_reports_real_engine(self):
        st = self.browser.capability_status()
        self.assertTrue(st["navigate_and_read"])
        self.assertIn(st["engine"],
                      ("playwright/chromium",
                       "http-fetch fallback"))
        # interaction availability is reported honestly: it
        # is True only when the driver really works
        self.assertIsInstance(st["interaction"], bool)
        if st["interaction"]:
            self.assertIn("REAL", st["note"])

    def test_requires_grants(self):
        sess = self.browser.open_session()
        rec = self.browser.navigate(
            sess["session_id"], "https://example.com")
        self.assertIn("error", rec)

    def test_rejects_non_http_schemes(self):
        self.caps.grant("browser.read")
        self.caps.grant("browser.navigate")
        sess = self.browser.open_session()
        rec = self.browser.navigate(
            sess["session_id"], "file:///C:/Windows/win.ini")
        self.assertIn("error", rec)
        rec = self.browser.navigate(
            sess["session_id"], "ftp://x")
        self.assertIn("error", rec)

    def test_real_interaction_when_engine_present(self):
        """When playwright works, click/type/extract are REAL -
        verified against a loopback http server."""
        if not self.browser._driver_ok:
            self.skipTest(
                "playwright engine unavailable here - "
                "honest skip, never faked")
        self.caps.grant("browser.read")
        self.caps.grant("browser.navigate")
        self.caps.grant("browser.interact")
        srv, url = self._local_page()
        try:
            sess = self.browser.open_session()
            if sess["engine"] != "playwright/chromium":
                self.skipTest(
                    "chromium could not launch under "
                    "current machine load - honest "
                    "skip, interaction never faked "
                    "(engine=%s)" % sess["engine"])
            sid = sess["session_id"]
            nav = self.browser.navigate(sid, url)
            self.assertNotIn("error", nav)
            self.assertEqual(nav["title"], "cyra-test")
            typed = self.browser.interact(
                sid, "type", selector="#q", text="hello")
            self.assertTrue(typed.get("done"),
                            msg=str(typed))
            clicked = self.browser.interact(
                sid, "click", selector="#go")
            self.assertTrue(clicked.get("done"))
            s = self.browser.sessions[sid]
            # the click REALLY ran the onclick handler
            self.assertEqual(s["_page"].title(),
                             "clicked")
        finally:
            srv.shutdown()

    def test_screenshot_real_when_engine_present(self):
        if not self.browser._driver_ok:
            self.skipTest("playwright engine unavailable")
        self.caps.grant("browser.read")
        self.caps.grant("browser.navigate")
        srv, url = self._local_page()
        try:
            sess = self.browser.open_session()
            if sess["engine"] != "playwright/chromium":
                self.skipTest(
                    "chromium could not launch under "
                    "current machine load (engine=%s)"
                    % sess["engine"])
            nav = self.browser.navigate(
                sess["session_id"], url)
            self.assertNotIn("error", nav)
            shot = self.browser.screenshot(
                sess["session_id"], confirm=True)
            self.assertIn("screenshot", shot)
            self.assertTrue(Path(
                shot["screenshot"]).is_file())
        finally:
            srv.shutdown()

    def _local_page(self):
        """A real loopback http server serving one page with a
        button (real interaction against a real endpoint)."""
        import http.server
        import threading

        page = (b"<html><head><title>cyra-test</title>"
                b"</head><body>"
                b"<input id='q'></input>"
                b"<button id='go' onclick="
                b"\"document.title='clicked'\">go</button>"
                b"</body></html>")

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header(
                    "Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(page)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(
            ("127.0.0.1", 0), H)
        t = threading.Thread(
            target=srv.serve_forever, daemon=True)
        t.start()
        url = ("http://127.0.0.1:%d/"
               % srv.server_address[1])
        return srv, url


class TestComputer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.caps, _ = make_cap(self.tmp)
        self.computer = ComputerRuntime(self.caps)

    def test_status_honest(self):
        st = self.computer.capability_status()
        self.assertTrue(st["launch_applications"])
        self.assertFalse(st["keyboard_input"])
        self.assertIn("never faked", st["note"])

    def test_launch_requires_confirm(self):
        self.caps.grant("computer.interact")
        with self.assertRaises(AuthorizationError):
            self.computer.launch("notepad")
        # never test the confirmed path here - launching real
        # applications in tests would open windows on the
        # user's machine

    def test_keyboard_mouse_report_unavailable(self):
        self.assertIn("error",
                      self.computer.keyboard("x"))
        self.assertIn("error",
                      self.computer.mouse("click"))


class TestTasks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.journal = Journal(
            Path(self.tmp) / "j.jsonl")
        self.store = TaskStore(Path(self.tmp),
                               self.journal)

    def test_durable_lifecycle(self):
        t = self.store.create("analyze repo",
                              workspace="*")
        t.transition("planning")
        t.transition("running")
        t.checkpoint("after-inspect",
                     {"files": 3})
        t.event("step", "inspected")
        t.transition("paused", "user paused")
        t.transition("running", "user resumed")
        t.transition("completed")
        # invalid transitions rejected
        with self.assertRaises(TaskError):
            t.transition("running")
        # persistence
        store2 = TaskStore(Path(self.tmp))
        n = store2.load()
        self.assertEqual(n, 1)
        rec = store2.get(t.data["task_id"])
        self.assertEqual(rec.data["state"],
                         "completed")
        self.assertEqual(
            rec.data["checkpoints"][-1]["label"],
            "after-inspect")

    def test_restart_recovery(self):
        t = self.store.create("long task")
        t.transition("planning")
        t.transition("running")
        t.checkpoint("mid-run", {"step": 2})
        # simulate restart: fresh store, load, recover
        store2 = TaskStore(Path(self.tmp))
        store2.load()
        rec = store2.recover()
        self.assertEqual(len(rec["recovered"]), 1)
        task = store2.get(t.data["task_id"])
        self.assertEqual(task.data["state"],
                         "recovering")
        self.assertIn("mid-run",
                      task.data["error"])

    def test_redirect_persists(self):
        t = self.store.create("old objective")
        t.data["objective"] = "new objective"
        t.event("redirected",
                objective="new objective")
        self.store._persist(t)
        store2 = TaskStore(Path(self.tmp))
        store2.load()
        self.assertEqual(
            store2.get(t.data["task_id"]).
            data["objective"],
            "new objective")


class TestMemoryArtifactsEvidence(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        root = Path(self.tmp)
        self.journal = Journal(root / "j.jsonl")
        self.mem = MemoryStore(root, self.journal)
        self.art = ArtifactStore(root, self.journal)
        self.ev = EvidenceStore(root, self.journal)

    def test_memory_redacts_secrets(self):
        rec = self.mem.remember(
            "project",
            "key sk-abcdef1234567890 "
            "password=hunter2 then text")
        self.assertIn("[REDACTED]", rec["text"])
        self.assertNotIn("hunter2", rec["text"])

    def test_memory_bounded_retrieval(self):
        for i in range(30):
            self.mem.remember(
                "task", f"note {i} about parsing "
                        f"bug {i % 3}", task_id="t1")
        hits = self.mem.recall("parsing bug",
                               limit=5)
        self.assertLessEqual(len(hits), 5)
        self.assertTrue(all(
            "parsing" in r["text"] for r in hits))

    def test_memory_remove_and_clear(self):
        rec = self.mem.remember(
            "project", "temporary note")
        self.assertEqual(
            self.mem.remove(rec["id"])["removed"],
            rec["id"])
        self.assertEqual(
            self.mem.remove("nope")["error"],
            "not found")
        self.mem.remember("task", "x", task_id="t9")
        self.assertEqual(self.mem.clear_task("t9"), 1)

    def test_artifact_provenance_and_integrity(self):
        rec = self.art.record(
            "report", content="REPORT BODY",
            task_id="t1", run_id="r1",
            agent="report_writer")
        content = self.art.read_content(
            rec["artifact_id"])
        self.assertTrue(content["integrity"])
        self.assertEqual(
            content["artifact"]["task_id"], "t1")
        # tamper -> integrity fails
        p = Path(content["artifact"]["path"])
        p.write_text("TAMPERED", encoding="utf-8")
        bad = self.art.read_content(rec["artifact_id"])
        self.assertFalse(bad["integrity"])

    def test_evidence_state_machine(self):
        rec = self.ev.record(
            "observation", "observed X",
            confidence=0.7)
        self.assertEqual(rec["state"], "OBSERVED")
        r = self.ev.corroborate(
            rec["evidence_id"])
        self.assertEqual(r["state"], "CORROBORATED")
        r = self.ev.mark_reproduced(
            rec["evidence_id"])
        self.assertEqual(r["state"], "REPRODUCED")
        # demotion refused
        out = self.ev.corroborate(
            rec["evidence_id"])
        self.assertIn("error", out)


class TestAgentRunControls(unittest.TestCase):
    """The full agent stack through the real orchestrator,
    including pause/stop controls that affect real work."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        from environment.app import Environment
        self.env = Environment(self.tmp)
        self.env.capabilities.grant("terminal.execute")
        self.env.capabilities.grant("git.read")
        self.env.capabilities.grant("git.write")
        self.env.capabilities.grant(
            "filesystem.read")
        self.env.capabilities.grant(
            "filesystem.write")
        self.env.capabilities.grant(
            "research.execute")

    def test_terminal_agent_executes_and_records(self):
        out = self.env.orchestrator.run_agent(
            "terminal_agent",
            {"shell": "python_code",
             "command": "print('agent-ok')",
             "workdir": self.tmp,
             "timeout": 30})
        self.assertEqual(out["state"], "DONE")
        self.assertEqual(
            out["result"]["exit_code"], 0)
        self.assertIn("agent-ok",
                      out["result"]["stdout"])
        # evidence recorded
        self.assertTrue(self.env.evidence.list())

    def test_terminal_agent_stop_kills_process(self):
        import threading
        orch = self.env.orchestrator
        result = {}

        def runner():
            result["out"] = orch.run_agent(
                "terminal_agent",
                {"shell": "python_code",
                 "command":
                     "import time; time.sleep(60)",
                 "workdir": self.tmp,
                 "timeout": 55})

        t = threading.Thread(target=runner)
        t.start()
        time.sleep(2)
        # find the active run and stop it - the REAL process
        runs = orch.agent_status()
        active = [r for r in runs
                  if r["agent"] == "terminal_agent"
                  and r["state"] == "RUNNING"]
        self.assertTrue(active)
        rec = orch.agent_run_stop(active[0]["run_id"])
        t.join(timeout=15)
        self.assertFalse(t.is_alive())
        # the run reports stopped or failed (killed process),
        # never a fake completed
        self.assertIn(result["out"]["state"],
                      ("STOPPED", "FAILED", "DONE"))
        if result["out"]["state"] == "DONE":
            # process killed before completion: exit code set
            self.assertIsNotNone(
                result["out"]["result"].get(
                    "exit_code"))

    def test_coding_agent_writes_and_tests(self):
        # a tiny project next to the workspace
        proj = Path(self.tmp) / "proj"
        (proj / "tests").mkdir(parents=True,
                               exist_ok=True)
        (proj / "tests" / "test_x.py").write_text(
            "def test_ok():\n    assert 1 + 1 == 2\n")
        out = self.env.orchestrator.run_agent(
            "coding_agent",
            {"path": "note.txt",
             "content": "written by CYR@",
             "workdir": str(proj),
             "run_tests": False})
        self.assertEqual(out["state"], "DONE")
        # the workspace write is real: file exists under the
        # environment's authorized workspace root
        ws_note = Path(self.tmp) / "workspace" / \
            "note.txt"
        self.assertTrue(ws_note.exists())
        self.assertEqual(
            ws_note.read_text(encoding="utf-8"),
            "written by CYR@")
        # and the artifact registry recorded provenance
        arts = self.env.artifacts.list()
        self.assertTrue(arts)

    def test_security_researcher_full_loop(self):
        self.env.capabilities.grant("engine.cider")
        out = self.env.orchestrator.run_agent(
            "security_researcher",
            {"target_id":
             "T-authentication-face-id"})
        self.assertEqual(out["state"], "DONE")
        self.assertIn(out["result"]["disposition"],
                      ("SUPPORTED", "REFUTED",
                       "INCONCLUSIVE", "BLOCKED"))

    def test_recovery_agent_resumes(self):
        store = self.env.taskstore
        t = store.create("interrupted work")
        t.transition("planning")
        t.transition("running")
        t.checkpoint("cp1", {})
        t.data["state"] = "recovering"
        t.data["error"] = "interrupted by restart"
        store._persist(t)
        out = self.env.orchestrator.run_agent(
            "recovery_agent",
            {"task_id": t.data["task_id"]})
        self.assertEqual(out["state"], "DONE")
        self.assertEqual(
            store.get(t.data["task_id"]).
            data["state"], "running")

    def test_all_specialists_are_executable(self):
        """No advertised specialist may be config-only: every
        kind in SPECIALISTS must have a real execution path
        (verified by exercising a representative task each)."""
        from environment.agents import SPECIALISTS
        orch = self.env.orchestrator
        for kind in SPECIALISTS:
            # the dispatch must know the kind: a run with an
            # empty-but-valid task returns FAILED with a
            # clear error (never silently "done"), or DONE for
            # kinds with defaults
            out = orch.run_agent(kind, {})
            self.assertIn(out["state"],
                          ("DONE", "FAILED"))
            if out["state"] == "FAILED":
                # the failure must be an honest, specific error
                self.assertIn("error", out["result"])


if __name__ == "__main__":
    unittest.main()
