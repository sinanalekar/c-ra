"""Tests for the multi-agent specialists, report generation,
and the deeper engine routing."""
import tempfile
import unittest

from environment.config import Config
from environment.journal import Journal
from environment.permissions import PermissionSystem
from environment.providers import ProviderStore
from environment.targets import TargetUniverse
from environment.engines import build_registry
from environment.orchestrator import Orchestrator
from environment.agents import (SPECIALISTS, AgentRun,
                                ReviewPipeline,
                                ModelRoleRouter,
                                _local_challenges,
                                _local_evidence_matrix)
from environment.routing import (rank_experiments, route,
                                 design_questions)
from environment.reports import generate_report


def make_orch(tmp):
    config = Config(tmp)
    config.ensure_dirs()
    journal = Journal(config.journal_path)
    perms = PermissionSystem(config.grants_path, journal)
    store = ProviderStore(config.providers_path, journal)
    reg = build_registry(config, journal)
    orch = Orchestrator(config, reg, perms, journal,
                        TargetUniverse(),
                        provider_store=store)
    return orch, journal


class TestAgents(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orch, self.journal = make_orch(self.tmp)

    def test_specialist_specs_complete(self):
        for kind, spec in SPECIALISTS.items():
            for field in ("kind", "purpose", "allowed_tools",
                          "authorization_requirements",
                          "inputs", "outputs",
                          "resource_limits",
                          "stop_conditions"):
                self.assertIn(field, spec,
                              f"{kind} missing {field}")

    def test_hypothesis_generator_produces_claim(self):
        run = self.orch.run_agent(
            "hypothesis_generator",
            {"target_id": "T-authentication-face-id"})
        self.assertEqual(run["state"], "DONE")
        self.assertIn("claim", run["result"])
        self.assertIn("engine", run["result"])
        # the run is inspectable: steps recorded
        self.assertGreaterEqual(len(run["steps"]), 2)
        # and journaled
        actions = [e["action"]
                   for e in self.journal.entries()]
        self.assertIn("agent_step", actions)

    def test_experiment_designer_ranks(self):
        run = self.orch.run_agent(
            "experiment_designer",
            {"target_id": "T-kernel-xnu",
             "vulnerability_class": "memory_safety"})
        self.assertEqual(run["state"], "DONE")
        ranked = run["result"]["ranked_experiments"]
        self.assertTrue(ranked)
        # scores are descending
        scores = [e["score"] for e in ranked]
        self.assertEqual(scores,
                         sorted(scores, reverse=True))
        # memory-safety routes to hydra templates
        self.assertEqual(
            run["result"]["chosen"]["engine"], "hydra")

    def test_hypothesis_challenger_enumerates(self):
        run = self.orch.run_agent(
            "hypothesis_challenger", {"claim": "x"})
        classes = [c["class"]
                   for c in run["result"]["challenges"]]
        self.assertIn("negative control missing", classes)
        self.assertIn(
            "ambient-activity attribution "
            "(differential control)", classes)

    def test_unknown_agent_rejected(self):
        run = self.orch.run_agent("nope", {})
        self.assertEqual(run["state"], "FAILED")

    def test_agent_pause_stop_resume(self):
        run = AgentRun("hypothesis_challenger",
                       {"claim": "x"})
        run._step("a")
        run.pause()
        with self.assertRaises(Exception):
            run.checkpoint()
        self.assertEqual(run.state, "PAUSED")
        run.resume()
        run.checkpoint()          # runs again
        run.stop()
        with self.assertRaises(Exception):
            run.checkpoint()
        self.assertEqual(run.state, "STOPPED")


class TestReviewPipeline(unittest.TestCase):
    def test_local_mode_gates_decide(self):
        pipe = ReviewPipeline(None)
        exp = {"evidence": [{"type": "x"}],
                "negative_controls_pass": True,
                "reproduced": True,
                "summary": "claim"}
        out = pipe.run(exp)
        self.assertEqual(out["verdict"], "SUPPORTED")
        self.assertEqual(len(out["stages"]), 4)
        # every stage records its mode honestly
        modes = {s["role"]: s["mode"]
                 for s in out["stages"]}
        self.assertEqual(modes["researcher"], "LOCAL")
        self.assertEqual(modes["evidence_adjudicator"],
                         "LOCAL-VERITAS")

    def test_missing_gates_downgrade(self):
        pipe = ReviewPipeline(None)
        exp = {"evidence": [{"type": "x"}],
                "negative_controls_pass": False,
                "reproduced": False,
                "disposition": "SUPPORTED",
                "summary": "claim"}
        out = pipe.run(exp)
        # VERITAS controls transitions: no gates, no SUPPORTED
        self.assertEqual(out["verdict"], "INCONCLUSIVE")

    def test_model_router_local_without_provider(self):
        store = ProviderStore(
            tempfile.mkdtemp() + "/p.json")
        router = ModelRoleRouter(store)
        out = router.call("independent_reviewer",
                          "p", {"x": 1})
        self.assertEqual(out["mode"], "LOCAL")
        self.assertIn("LOCAL", out["note"])

    def test_evidence_matrix_partition(self):
        m = _local_evidence_matrix({
            "evidence": [{"a": 1}, {"b": 2}],
            "negative_controls_pass": True,
            "reproduced": True})
        self.assertGreaterEqual(m["PROVEN"], 3)
        self.assertEqual(m["UNTESTED"], 0)


class TestRouting(unittest.TestCase):
    def setUp(self):
        self.tu = TargetUniverse()
        self.kernel = dict(self.tu.get("T-kernel-xnu"))
        self.auth = dict(
            self.tu.get("T-authentication-face-id"))

    def test_design_questions_answered(self):
        q = design_questions(self.kernel)
        self.assertEqual(len(q), 12)
        self.assertIn("boundary", q["2_trust_boundary"])

    def test_routing_uses_engine_fit(self):
        r = route(self.kernel, "memory_safety")
        self.assertEqual(r["chosen"]["engine"], "hydra")
        self.assertIn("firmware_tooling",
                      r["required_capabilities"])
        r2 = route(self.auth, "auth_boundary")
        self.assertEqual(r2["chosen"]["engine"], "cider")
        self.assertNotIn("network",
                         r2["required_capabilities"])

    def test_seek_routing_needs_network_cap(self):
        icloud = dict(self.tu.get("T-services-icloud"))
        r = route(icloud, "web_endpoint")
        self.assertEqual(r["chosen"]["engine"], "seek")
        self.assertIn("network",
                      r["required_capabilities"])

    def test_ranked_not_identical_everywhere(self):
        k = [e["template"] for e in
             rank_experiments(self.kernel)[:3]]
        a = [e["template"] for e in
             rank_experiments(self.auth)[:3]]
        self.assertNotEqual(k, a)


class TestReports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orch, self.journal = make_orch(self.tmp)
        self.perms = self.orch.permissions

    def _full_experiment(self):
        self.perms.grant("experimental_execution")
        hyp = self.orch.register_hypothesis(
            "A session-state machine flaw violates its auth "
            "invariant and CIDER detects it with the repaired "
            "control clean",
            target_id="T-authentication-face-id",
            engine="cider",
            params={"experiment":
                    "exp_invariant_session"})
        rec = self.orch.run_experiment(
            hyp["hypothesis_id"])
        return rec

    def test_report_has_mandatory_sections(self):
        rec = self._full_experiment()
        if rec["disposition"] == "BLOCKED":
            self.skipTest("cider unavailable")
        report = self.orch.generate_report(
            rec["experiment_id"])
        md = report["markdown"]
        for section in (
                "Title", "Executive summary", "Target",
                "Scope and authorization", "Preconditions",
                "Security property", "Hypothesis",
                "Methodology", "Reproduction", "Controls",
                "Observed result", "Evidence", "Falsification",
                "Impact", "Limitations",
                "What was NOT demonstrated",
                "Reproduction instructions", "Timeline",
                "Hashes and provenance",
                "Disclosure recommendation"):
            self.assertIn(section, md)
        self.assertIn(report["sha256"], md)
        # never exaggerates: no real-system claims
        self.assertIn("No real-system impact is claimed", md)

    def test_not_demonstrated_is_mandatory(self):
        rec = self._full_experiment()
        if rec["disposition"] == "BLOCKED":
            self.skipTest("cider unavailable")
        report = self.orch.generate_report(
            rec["experiment_id"])
        self.assertIn("What was NOT demonstrated",
                      report["markdown"])
        self.assertIn("exploitability",
                      report["markdown"])

    def test_report_journaled_with_hash(self):
        rec = self._full_experiment()
        if rec["disposition"] == "BLOCKED":
            self.skipTest("cider unavailable")
        report = self.orch.generate_report(
            rec["experiment_id"])
        entries = self.journal.entries()
        rep = [e for e in entries
               if e["action"] == "report_generated"]
        self.assertTrue(rep)
        self.assertEqual(rep[-1]["sha256"],
                         report["sha256"])

    def test_report_on_unknown_experiment(self):
        out = self.orch.generate_report("EX-9999")
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
