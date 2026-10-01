"""Reinitialize subsystem tests: the A-J matrix from the
master prompt, run against controlled local git repositories
(real git, real diffs, real tests - no network, no
hallucinated state).

A  no changes            -> up to date
B  docs-only change       -> recorded, no code integration
C  compatible change      -> planned + safely applied + tested
D  breaking change        -> review required, not applied
E  security-boundary      -> authorization required
F  research-state schema  -> migration required
G  confidential material  -> blocked, never propagated
H  tests fail after apply -> reverted safely
I  uncommitted CYR@ local -> protected, refused
J  remote unavailable     -> exact failure, state preserved
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from environment.reinit import (ReinitEngine,
                                classify_files,
                                verdict_for)
from environment.journal import Journal


def sh(*args, cwd):
    return subprocess.run(
        args, cwd=str(cwd), capture_output=True,
        text=True, encoding="utf-8",
        errors="replace", timeout=120)


def robust_rmtree(p: Path):
    """Windows: git objects are read-only; chmod then
    delete."""
    import os
    import stat

    def onexc(f, path, exc):
        try:
            os.chmod(path, stat.S_IWRITE)
            f(path)
        except Exception:
            pass
    shutil.rmtree(p, onexc=onexc)


def init_repo(path: Path, bare=False):
    args = ["git", "init", "-q",
            "-b", "main"]
    if bare:
        args.append("--bare")
    sh(*args, cwd=path)
    if not bare:
        cfg(path)
    return path


def cfg(repo):
    sh("git", "config", "user.email", "t@t",
       cwd=repo)
    sh("git", "config", "user.name", "t", cwd=repo)


def commit(repo: Path, name: str,
           files: dict[str, str],
           msg: str):
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True,
                       exist_ok=True)
        p.write_text(content,
                     encoding="utf-8")
        sh("git", "add", "--", rel, cwd=repo)
    sh("git", "commit", "-q", "-m", msg,
       cwd=repo)


class Fixture:
    """A research-repo stand-in with a local remote."""

    def __init__(self, base: Path, name: str):
        self.name = name
        self.remote = base / f"{name}-remote.git"
        self.remote.mkdir()
        init_repo(self.remote, bare=True)
        self.repo = base / f"{name}"
        self.repo.mkdir()
        init_repo(self.repo)
        commit(self.repo, "seed",
               {"README.md": "seed"},
               "seed commit")
        sh("git", "remote", "add", "origin",
           str(self.remote), cwd=self.repo)
        sh("git", "push", "-q", "-u", "origin",
           "main", cwd=self.repo)

    def remote_commit(self, files, msg):
        """Commit on the remote (simulating new upstream
        work) without touching the local clone."""
        _upstream_push(self.remote, files, msg)


def _upstream_push(bare: Path, files, msg):
    """Clone the bare remote, commit on top (RELATED
    history), push - the correct simulation of upstream
    work."""
    tmp = bare.parent / (bare.name + "-upstream")
    if tmp.exists():
        robust_rmtree(tmp)
    sh("git", "clone", "-q", str(bare),
       str(tmp), cwd=bare.parent)
    commit(tmp, "up", files, msg)
    sh("git", "push", "-q", "origin", "main",
       cwd=tmp)
    robust_rmtree(tmp)


def bare_from(base: Path, repo: Path,
              name: str) -> Path:
    """A bare remote cloned FROM an existing repo (shared
    root commit - fast-forward merges stay valid)."""
    bare = base / f"{name}-remote.git"
    bare.mkdir()
    sh("git", "clone", "-q", "--bare", str(repo),
       str(bare), cwd=base)
    return bare


class ReinitMatrix(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.journal = Journal(
            self.tmp / "j.jsonl")
        self.workspace = self.tmp / "workspace"
        self.workspace.mkdir()
        self.engine = ReinitEngine(
            self.workspace, self.journal)
        # a CYR@-like repository fixture for the apply paths
        self.cyr = self.tmp / "cyr-fixture"
        self.cyr.mkdir()
        init_repo(self.cyr)
        commit(self.cyr, "base",
               {"README.md": "cyra",
                "tests/test_ok.py":
                    "import unittest\n\n"
                    "class TestOk(unittest."
                    "TestCase):\n"
                    "    def test_ok(self):\n"
                    "        self.assertTrue("
                    "True)\n"},
               "base")
        sh("git", "remote", "add", "origin",
           str(self.cyr), cwd=self.cyr)
        self.engine.cfg.data["repos"]["cyr"][
            "path"] = str(self.cyr)

    def _repo_fixture(self, name) -> Fixture:
        return Fixture(self.tmp, name)

    def _run(self, repos=None):
        return self.engine.start(
            model={"provider": "LOCAL",
                   "model_id": None},
            repos=repos)

    # ------------------------------------------ A
    def test_case_a_no_changes(self):
        f = self._repo_fixture("veritas")
        self.engine.cfg.data["repos"][
            "veritas"]["path"] = str(f.repo)
        out = self._run(["veritas"])
        self.assertEqual(out["state"],
                         "COMPLETED")
        self.assertEqual(
            out["verdicts"]["veritas"],
            "UP_TO_DATE")
        self.assertEqual(out["applied"], [])
        # session records exist
        self.assertTrue((self.workspace /
                        "reinitialization")
                        .is_dir())

    # ------------------------------------------ B
    def test_case_b_docs_only(self):
        f = self._repo_fixture("cider")
        self.engine.cfg.data["repos"][
            "cider"]["path"] = str(f.repo)
        f.remote_commit({"NOTES.md": "new notes"},
                        "docs: notes")
        out = self._run(["cider"])
        self.assertEqual(
            out["verdicts"]["cider"],
            "DOCS_ONLY")
        # manifest advanced to the new commit
        m = self.engine.manifest.get("cider")
        self.assertTrue(m.get(
            "last_seen_commit"))
        # nothing applied to CYR@
        self.assertEqual(out["applied"], [])

    # ------------------------------------------ C
    def test_case_c_compatible_applied(self):
        # a bare remote SHARED with the CYR@ fixture (same
        # root commit); upstream adds a compatible change
        bare = bare_from(self.tmp, self.cyr,
                         "cyr-upstream")
        sh("git", "remote", "remove",
           "origin", cwd=self.cyr)
        sh("git", "remote", "add", "origin",
           str(bare), cwd=self.cyr)
        sh("git", "fetch", "-q", "origin",
           cwd=self.cyr)
        self.engine.cfg.data["repos"]["cyr"][
            "path"] = str(self.cyr)
        # prime the manifest at the current commit
        self._run(["cyr"])
        _upstream_push(bare,
                       {"docs/sync-note.md": "ok",
                        "tests/test_extra.py":
                            "def test_extra():\n"
                            "    assert 1 == 1\n"},
                       "docs + compatible test")
        out = self._run(["cyr"])
        self.assertEqual(
            out["verdicts"]["cyr"], "COMPATIBLE")
        self.assertTrue(out["applied"],
                        "expected the compatible "
                        "change to be applied")

    # ------------------------------------------ D
    def test_case_d_breaking_requires_review(self):
        classes = classify_files([
            {"path":
             "environment/engines/base.py",
             "status": "M"}])
        self.assertIn("ENGINE_SURFACE", classes)
        self.assertEqual(verdict_for(classes),
                         "REVIEW_REQUIRED")

    # ------------------------------------------ E
    def test_case_e_security_boundary(self):
        classes = classify_files([
            {"path": "capabilities.py",
             "status": "M"}])
        self.assertEqual(verdict_for(classes),
                         "REQUIRES_AUTHORIZATION")

    # ------------------------------------------ F
    def test_case_f_research_schema(self):
        classes = classify_files([
            {"path":
                 "workspace/findings_schema.json",
             "status": "M"}])
        self.assertEqual(verdict_for(classes),
                         "MIGRATION_REQUIRED")

    # ------------------------------------------ G
    def test_case_g_confidential_blocked(self):
        classes = classify_files([
            {"path":
                 "SUBMITTED_OE1107708846.md",
             "status": "A"}])
        self.assertEqual(verdict_for(classes),
                         "BLOCKED_CONFIDENTIAL")
        # end-to-end: confidential repo never applied
        f = self._repo_fixture("seek")
        self.engine.cfg.data["repos"][
            "seek"]["path"] = str(f.repo)
        f.remote_commit(
            {"SUBMITTED_private_report.md":
                 "secret"},
            "add confidential")
        out = self._run(["seek"])
        self.assertEqual(
            out["verdicts"]["seek"],
            "BLOCKED_CONFIDENTIAL")
        self.assertIn("seek", out["blocked"])
        self.assertEqual(out["applied"], [])
        # and it never enters plan artifacts
        plan = Path(
            out and next(
                (self.workspace /
                 "reinitialization").iterdir())
        ) / "integration_plan.md"
        self.assertNotIn("secret",
                         plan.read_text(
                             encoding="utf-8"))

    # ------------------------------------------ H
    def test_case_h_failed_tests_revert(self):
        bare = bare_from(self.tmp, self.cyr,
                         "cyr-upstream-h")
        sh("git", "remote", "remove",
           "origin", cwd=self.cyr)
        sh("git", "remote", "add", "origin",
           str(bare), cwd=self.cyr)
        sh("git", "fetch", "-q", "origin",
           cwd=self.cyr)
        self.engine.cfg.data["repos"]["cyr"][
            "path"] = str(self.cyr)
        self._run(["cyr"])
        # upstream adds a change that BREAKS the tests
        _upstream_push(bare,
                       {"tests/test_ok.py":
                            "def test_ok():\n"
                            "    assert False\n",
                        "docs/note.md": "n"},
                       "breaking tests")
        out = self._run(["cyr"])
        self.assertEqual(out["state"], "FAILED")
        self.assertTrue(out["reverted"])
        # the base branch still has the original content
        content = sh("git", "show",
                     "main:tests/test_ok.py",
                     cwd=self.cyr)
        self.assertIn("assertTrue(True)",
                      content.stdout)

    # ------------------------------------------ I
    def test_case_i_dirty_tree_protected(self):
        bare = bare_from(self.tmp, self.cyr,
                         "cyr-upstream-i")
        sh("git", "remote", "remove",
           "origin", cwd=self.cyr)
        sh("git", "remote", "add", "origin",
           str(bare), cwd=self.cyr)
        sh("git", "fetch", "-q", "origin",
           cwd=self.cyr)
        self.engine.cfg.data["repos"]["cyr"][
            "path"] = str(self.cyr)
        self._run(["cyr"])
        _upstream_push(bare,
                       {"docs/x.md": "upstream"},
                       "docs upstream")
        # local uncommitted change appears
        (self.cyr / "local_work.txt").write_text(
            "my local work", encoding="utf-8")
        sh("git", "add", "local_work.txt",
           cwd=self.cyr)
        out = self._run(["cyr"])
        self.assertTrue(out["cyr_dirty_tree"])
        self.assertEqual(out["applied"], [])
        # local work untouched
        self.assertTrue(
            (self.cyr / "local_work.txt")
            .is_file())

    # ------------------------------------------ J
    def test_case_j_remote_unavailable(self):
        f = self._repo_fixture("hydra")
        self.engine.cfg.data["repos"][
            "hydra"]["path"] = str(f.repo)
        # break the remote then create upstream delta
        sh("git", "remote", "set-url", "origin",
           "file:///nonexistent/remote.git",
           cwd=f.repo)
        out = self._run(["hydra"])
        # session survives with an honest per-repo note
        self.assertIn(out["state"],
                      ("COMPLETED", "FAILED"))
        rec = out["repositories"]["hydra"]
        self.assertEqual(rec["status"],
                         "REMOTE_UNAVAILABLE")
        self.assertTrue(rec.get("reason"))


class TestClassificationUnits(unittest.TestCase):
    def test_no_changes(self):
        self.assertEqual(
            verdict_for(classify_files([])),
            "UP_TO_DATE")

    def test_confidential_beats_everything(self):
        self.assertEqual(verdict_for(
            ["DOCS", "CONFIDENTIAL"]),
            "BLOCKED_CONFIDENTIAL")


if __name__ == "__main__":
    unittest.main()
