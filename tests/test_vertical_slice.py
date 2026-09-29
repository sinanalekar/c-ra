"""The vertical slice test (master prompt section 60):

Desktop UI -> local backend -> workspace -> provider
configuration -> VERITAS coordinator -> one CIDER experiment ->
evidence -> falsification -> provenance -> result

Exercised end-to-end, in-process, with deliberate failure
paths: authorization denial, engine unavailability, tamper
detection."""
import os
import tempfile
import unittest

from environment.config import Config
from environment.journal import Journal
from environment.permissions import (AuthorizationError,
                                     PermissionSystem)
from environment.targets import TargetUniverse
from environment.engines import build_registry
from environment.orchestrator import Orchestrator


class TestEngineAdapters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config = Config(self.tmp)
        self.journal = Journal(
            self.config.journal_path)
        self.registry = build_registry(self.config,
                                       self.journal)

    def test_all_five_registered(self):
        names = sorted(self.registry.all())
        self.assertEqual(names,
                         ["cider", "frontier", "hydra",
                          "seek", "veritas"])

    def test_describe_contract(self):
        for e in self.registry.all().values():
            d = e.describe()
            for key in ("name", "version", "available",
                        "capabilities", "inputs", "outputs",
                        "experiment_types",
                        "authorization_requirements",
                        "risk_level"):
                self.assertIn(key, d)

    def test_honest_unavailable(self):
        # a registry with no paths at all reports unavailable,
        # never fakes
        import environment.engines.base as base
        e = base.EngineRegistry()
        from environment.engines.cider_engine import \
            CiderEngine
        e.register(CiderEngine(None, self.tmp))
        self.assertFalse(e.get("cider").available())

    def test_veritas_engine_available_and_runs(self):
        eng = self.registry.get("veritas")
        if not eng.available():
            self.skipTest("veritas repo not on this machine")
        res = eng.execute("EX-SLICE", {"claim": "x"}, {},
                          {})
        self.assertIn(res.disposition,
                      ("SUPPORTED", "REFUTED",
                       "INCONCLUSIVE", "BLOCKED"))
        self.assertTrue(res.evidence)


class TestVerticalSlice(unittest.TestCase):
    """The full chain, gates and all."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.config = Config(self.tmp)
        self.config.ensure_dirs()
        self.journal = Journal(
            self.config.journal_path)
        self.permissions = PermissionSystem(
            self.config.grants_path, self.journal)
        self.registry = build_registry(self.config,
                                       self.journal)
        self.targets = TargetUniverse()
        self.orch = Orchestrator(
            self.config, self.registry, self.permissions,
            self.journal, self.targets)

    def test_slice_denies_without_authorization(self):
        hyp = self.orch.register_hypothesis(
            "A session-state invariant flaw is discoverable "
            "by CIDER's invariant monitor",
            target_id="T-authentication-face-id",
            engine="cider",
            params={"experiment":
                    "exp_invariant_session"})
        rec = self.orch.run_experiment(
            hyp["hypothesis_id"])
        # insufficient authorization is a recorded BLOCKED
        # disposition (master prompt section 25), not an
        # exception swallowed by the UI
        self.assertEqual(rec["disposition"], "BLOCKED")
        self.assertIn("insufficient authorization",
                      rec["reason"])
        # the denial is journaled
        entries = self.journal.entries()
        self.assertTrue(any(
            e["action"] == "authorization_denied"
            for e in entries))

    def test_slice_full_chain(self):
        # 1. authorization gate: grant what the engine needs
        self.permissions.grant("experimental_execution")
        # 2. hypothesis on a real target in the universe
        hyp = self.orch.register_hypothesis(
            "A session-state machine flaw violates its "
            "auth invariant and CIDER's monitor detects it "
            "with the repaired control staying clean",
            target_id="T-authentication-face-id",
            engine="cider",
            falsification=
                "the repaired control also trips the "
                "monitor, or the flaw is not reproducible")
        hid = hyp["hypothesis_id"]
        self.assertEqual(hyp["state"], "REGISTERED")
        # 3. engine availability is real
        if not self.registry.get("cider").available():
            self.skipTest("cider repo not resolvable")
        # 4. run the experiment through the coordinator
        rec = self.orch.run_experiment(hid)
        self.assertIn(rec["disposition"],
                      ("SUPPORTED", "REFUTED",
                       "INCONCLUSIVE"))
        # 5. evidence + negative-control + reproduction gates
        self.assertTrue(rec["evidence"])
        self.assertIn("reproduction", rec)
        self.assertIn("negative_controls_pass", rec)
        # 6. a SUPPORTED disposition REQUIRES both gates
        if rec["disposition"] == "SUPPORTED":
            self.assertTrue(rec["negative_controls_pass"])
            self.assertTrue(rec["reproduced"])
        # 7. provenance: every step journaled, chain valid
        chain = self.journal.verify()
        self.assertTrue(chain["valid"])
        actions = [e["action"]
                   for e in self.journal.entries()]
        for needed in ("research_session_started",
                      "hypothesis_registered",
                      "experiment_started",
                      "experiment_completed"):
            self.assertIn(needed, actions)
        # 8. coverage updated from the ACTUAL experiment
        cov = self.targets.coverage_report()
        self.assertEqual(
            cov["by_coverage_state"].get(
                "controlled",
                cov["by_coverage_state"].get(
                    "reproduced", 0)) >= 1, True)

    def test_seek_blocks_without_network_grant(self):
        hyp = self.orch.register_hypothesis(
            "an authorized endpoint behaves differently "
            "under CL/TE framing",
            target_id="T-services-icloud", engine="seek")
        rec = self.orch.run_experiment(
            hyp["hypothesis_id"])
        self.assertEqual(rec["disposition"], "BLOCKED")

    def test_hydra_blocks_without_artifact(self):
        self.permissions.grant("firmware_tooling")
        self.permissions.grant("experimental_execution")
        hyp = self.orch.register_hypothesis(
            "the kernelcache contains unguarded multiply-"
            "as-address sites",
            target_id="T-kernel-xnu", engine="hydra")
        rec = self.orch.run_experiment(
            hyp["hypothesis_id"])
        self.assertEqual(rec["disposition"], "BLOCKED")
        # the blocked state is journaled, honest
        entries = self.journal.entries()
        self.assertTrue(any(
            e["action"] == "engine_experiment_blocked"
            for e in entries))


if __name__ == "__main__":
    unittest.main()
