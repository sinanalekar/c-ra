"""Unit tests: journal integrity, permissions boundaries,
workspace confinement, provider schema, target universe."""
import json
import os
import tempfile
import unittest

from environment.config import Config
from environment.journal import Journal
from environment.permissions import (CAPABILITIES,
                                     AuthorizationError,
                                     PermissionSystem)
from environment.providers import ProviderStore
from environment.targets import TargetUniverse
from environment.workspace import (Workspace, WorkspaceError)


class TestJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.j = Journal(os.path.join(self.tmp, "j.jsonl"))

    def test_chain_valid_and_tamper_detected(self):
        self.j.append("a", x=1)
        self.j.append("b", y=2)
        self.assertTrue(self.j.verify()["valid"])
        # tamper
        path = self.j.path
        lines = path.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["x"] = 999
        lines[0] = json.dumps(rec, sort_keys=True)
        path.write_text("\n".join(lines) + "\n",
                        encoding="utf-8")
        self.assertFalse(self.j.verify()["valid"])


class TestPermissions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ps = PermissionSystem(
            os.path.join(self.tmp, "g.json"))

    def test_deny_by_default(self):
        with self.assertRaises(AuthorizationError):
            self.ps.require("experimental_execution")

    def test_grant_then_allowed(self):
        self.ps.grant("experimental_execution")
        self.ps.require("experimental_execution")

    def test_scope_respected(self):
        self.ps.grant("experimental_execution", scope="T-x-y")
        with self.assertRaises(AuthorizationError):
            self.ps.require("experimental_execution",
                            scope="other")

    def test_high_risk_needs_confirmation(self):
        self.ps.grant("device_access")
        self.assertFalse(
            self.ps.check("device_access",
                          confirm_high_risk=False))
        self.assertTrue(
            self.ps.check("device_access",
                          confirm_high_risk=True))

    def test_unknown_capability_rejected(self):
        with self.assertRaises(AuthorizationError):
            self.ps.grant("not_a_capability")


class TestWorkspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ps = PermissionSystem(
            os.path.join(self.tmp, "g.json"))
        self.ws = Workspace(self.tmp, self.ps)

    def test_write_requires_permission(self):
        with self.assertRaises(AuthorizationError):
            self.ws.write("a.txt", "hi")

    def test_traversal_rejected(self):
        self.ps.grant("workspace_write")
        with self.assertRaises(WorkspaceError):
            self.ws.write("../escape.txt", "no")

    def test_write_read_search_cycle(self):
        self.ps.grant("workspace_write")
        self.ps.grant("workspace_read")
        self.ws.write("notes/x.md", "needle in haystack")
        self.assertEqual(
            self.ws.read("notes/x.md")["content"],
            "needle in haystack")
        self.assertIn("notes/x.md",
                      self.ws.search("needle"))

    def test_delete_requires_own_permission(self):
        self.ps.grant("workspace_write")
        self.ws.write("d.txt", "x")
        with self.assertRaises(AuthorizationError):
            self.ws.delete("d.txt")
        self.ps.grant("file_delete")
        self.assertTrue(self.ws.delete("d.txt")["deleted"])


class TestProviders(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.store = ProviderStore(
            os.path.join(self.tmp, "p.json"))

    def test_local_mode_honest(self):
        st = self.store.status()
        self.assertEqual(st["roles"]["coordinator"][
                             "provider"],
                         "LOCAL (unconfigured)")

    def test_provider_schema_enforced(self):
        with self.assertRaises(ValueError):
            self.store.add_provider({"name": "x"})
        with self.assertRaises(ValueError):
            self.store.add_provider({
                "name": "x", "base_url": "http://insecure",
                "api_format": "openai"})
        ok = self.store.add_provider({
            "name": "x", "base_url": "https://api.x.io",
            "api_format": "openai"})
        self.assertTrue(ok["configured"])

    def test_role_binding_requires_provider(self):
        with self.assertRaises(ValueError):
            self.store.bind_role("coordinator", "nope",
                                 "m")


class TestTargets(unittest.TestCase):
    def setUp(self):
        self.tu = TargetUniverse()

    def test_universe_searchable(self):
        hits = self.tu.search("webkit")
        self.assertTrue(any(
            t["product"] == "WebKit" for t in hits))

    def test_coverage_starts_untested(self):
        cov = self.tu.coverage_report()
        self.assertEqual(cov["untested_count"],
                         cov["total_targets"])

    def test_coverage_updates_only_from_experiments(self):
        t = next(iter(self.tu.targets.values()))
        self.tu.record_experiment(t["target_id"], {
            "ts": "now", "experiment_id": "EX-1",
            "has_negative_control": True,
            "reproduced": True, "evidence": True})
        cov = self.tu.coverage_report()
        self.assertEqual(cov["by_coverage_state"].get(
            "reproduced"), 1)

    def test_research_plan_gaps_reported(self):
        t = next(iter(self.tu.targets.values()))
        plan = self.tu.for_target(t["target_id"])
        self.assertIn("attack surface unmapped",
                      plan["research_gaps"])


if __name__ == "__main__":
    unittest.main()
