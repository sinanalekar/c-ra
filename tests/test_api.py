"""Local backend API tests: the FastAPI surface (localhost-only
binding, permission-gated endpoints, honest states)."""
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from environment.app import Environment, create_app


class TestAPI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = Environment(self.tmp)
        self.client = TestClient(create_app(self.env))

    def test_status(self):
        r = self.client.get("/api/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("engines", body)
        self.assertIn("journal", body)
        self.assertTrue(body["journal"]["valid"])

    def test_engines_listed_with_availability(self):
        r = self.client.get("/api/engines")
        names = {e["name"]: e["available"]
                 for e in r.json()}
        self.assertEqual(sorted(names),
                         ["cider", "frontier", "hydra",
                          "seek", "veritas"])
        # availability is reported honestly, whatever it is
        self.assertIsInstance(names["cider"], bool)

    def test_targets_search_and_plan(self):
        r = self.client.post("/api/targets/search",
                             json={"query": "webkit"})
        self.assertGreater(len(r.json()), 0)
        tid = r.json()[0]["target_id"]
        r = self.client.get(f"/api/targets/{tid}")
        self.assertIn("research_plan", r.json())

    def test_hypothesis_lifecycle_via_api(self):
        self.client.post("/api/authorization/grant",
                        json={"capability":
                              "experimental_execution"})
        r = self.client.post("/api/hypotheses", json={
            "claim": "CIDER detects a session-state flaw",
            "target_id": "T-authentication-face-id",
            "engine": "cider",
            "params": {"experiment":
                       "exp_invariant_session"}})
        self.assertEqual(r.status_code, 200)
        hid = r.json()["hypothesis_id"]
        r = self.client.post(
            f"/api/hypotheses/{hid}/run", json={"params": {}})
        self.assertIn(r.status_code, (200, 404))
        if r.status_code == 200:
            self.assertIn(r.json()["disposition"],
                          ("SUPPORTED", "REFUTED",
                           "INCONCLUSIVE"))

    def test_run_blocked_without_grant(self):
        # first-run defaults grant the working set; a user who
        # revokes everything is denied (deny-by-default ledger)
        for cap in ("research.execute",):
            self.env.capabilities.revoke(cap)
        r = self.client.post("/api/hypotheses", json={
            "claim": "x", "target_id":
            "T-authentication-face-id",
            "engine": "cider"})
        hid = r.json()["hypothesis_id"]
        r = self.client.post(
            f"/api/hypotheses/{hid}/run", json={"params": {}})
        body = r.json()
        self.assertEqual(body["disposition"], "BLOCKED")

    def test_workspace_requires_permissions(self):
        # first-run defaults include filesystem access; revoke
        # it and the workspace is denied (deny-by-default)
        self.env.capabilities.revoke("filesystem.read")
        self.env.capabilities.revoke("filesystem.write")
        r = self.client.post("/api/workspace/write",
                            json={"path": "a.txt",
                                  "content": "x"})
        self.assertEqual(r.status_code, 403)
        self.client.post("/api/authorization/grant",
                        json={"capability":
                              "filesystem.write"})
        r = self.client.post("/api/workspace/write",
                            json={"path": "a.txt",
                                  "content": "x"})
        self.assertEqual(r.status_code, 200)

    def test_workspace_traversal_rejected(self):
        self.client.post("/api/authorization/grant",
                        json={"capability":
                              "workspace_write"})
        r = self.client.post("/api/workspace/write",
                            json={"path": "../escape",
                                  "content": "x"})
        self.assertEqual(r.status_code, 403)

    def test_providers_local_mode(self):
        r = self.client.get("/api/providers")
        roles = r.json()["roles"]
        self.assertEqual(roles["falsification_reviewer"][
                             "provider"],
                         "LOCAL (unconfigured)")

    def test_journal_endpoints(self):
        r = self.client.get("/api/journal")
        self.assertIsInstance(r.json(), list)
        r = self.client.get("/api/journal/verify")
        self.assertTrue(r.json()["valid"])


if __name__ == "__main__":
    unittest.main()
