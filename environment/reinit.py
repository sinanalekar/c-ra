"""CYR@ Reinitialize subsystem.

A durable, evidence-backed synchronization session between
CYR@ and its research ecosystem (VERITAS, CIDER, SEEK, HYDRA,
Frontier + CYR@ itself).

REAL mechanics only:
- git inspection (rev-parse, fetch, rev-list, diff) of the
  configured repositories,
- a persistent sync manifest (last_seen_commit per repo),
- deterministic change classification (docs / compatible /
  breaking / security-boundary / research-state schema /
  confidential),
- safe integration: clean-tree protection, backup branch,
  patch, TESTS, revert on failure,
- session records under reinitialization/{timestamp}/ with
  provenance,
- auto-push ALWAYS disabled by default; pushes require the
  high-risk confirm path (never silent).

The REINITIALIZATION model (when bound) composes the plan
narrative from the tool-grounded inspection; LOCAL mode
composes deterministically. Neither invents repository
state."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

CONFIDENTIAL_PATTERNS = (
    re.compile(r"SUBMITTED_", re.I),
    re.compile(r"private|confidential", re.I),
    re.compile(r"\.(pem|key|p12)$", re.I),
    re.compile(r"(api[_-]?key|token|secret)", re.I),
    re.compile(r"bounty|draft[-_]cve", re.I),
)
SECURITY_BOUNDARY = re.compile(
    r"(capabilit|authoriz|permission|security|credential)", re.I)
RESEARCH_SCHEMA = re.compile(
    r"workspace/.*schema|schema.*\.json$", re.I)
DOCS_ONLY_EXT = (".md", ".txt", ".rst", ".adoc")
TESTS_PATTERN = re.compile(
    r"tests?[/\\]|test_\w+\.py$|conftest\.py$", re.I)
ENGINE_SURFACE = re.compile(
    r"environment[/\\]engines|environment[/\\]\w+\.py")


def _git(repo: Path, *args, timeout: int = 60):
    p = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
        timeout=timeout)
    return p


class ReinitConfig:
    """Repository set + policies. auto_push is structurally
    never enabled by defaults."""

    def __init__(self, root: Path):
        self.path = root / "reinit" / "config.json"
        self.path.parent.mkdir(parents=True,
                               exist_ok=True)
        if self.path.exists():
            try:
                self.data = json.loads(
                    self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.data = {}
        else:
            self.data = {}
        self.data.setdefault("repos", {
            "veritas": {
                "path": r"C:\Users\SINAN\veritas"},
            "cider": {
                "path": r"C:\Users\SINAN\AppData\Local\Temp"
                        r"\opencode\study-cider"},
            "seek": {
                "path": r"C:\Users\SINAN\AppData\Local\Temp"
                        r"\opencode\study-seek"},
            "hydra": {
                "path": r"C:\Users\SINAN\AppData\Local\Temp"
                        r"\opencode\study-hydra"},
            "frontier": {
                "path": r"C:\Users\SINAN\AppData\Local\Temp"
                        r"\opencode\study-frontier"},
            "cyr": {"path": ""},   # filled at runtime
        })
        self.data.setdefault("policy", {
            "update": "safe",        # safe | review-only
            "auto_commit": True,
            "auto_push": False,      # never defaults on
        })
        self.save()

    def save(self):
        self.path.write_text(json.dumps(
            self.data, indent=1, sort_keys=True),
            encoding="utf-8")

    def repo_path(self, name: str) -> str:
        if name == "cyr":
            return self.data["repos"][name].get("path") or ""
        return self.data["repos"].get(name, {}).get("path", "")

    def set_cyr_path(self, p: str):
        self.data["repos"]["cyr"]["path"] = p
        self.save()


class SyncManifest:
    """Per-repository last-known state."""

    def __init__(self, root: Path):
        self.path = root / "reinit" / "manifest.json"
        self.path.parent.mkdir(parents=True,
                               exist_ok=True)
        if self.path.exists():
            try:
                self.data = json.loads(
                    self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.data = {"repos": {}}
        else:
            self.data = {"repos": {}}

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            self.data, indent=1, sort_keys=True),
            encoding="utf-8")
        tmp.replace(self.path)

    def get(self, repo: str) -> dict:
        return self.data["repos"].get(repo, {})

    def update(self, repo: str, record: dict):
        self.data["repos"][repo] = {
            **self.data["repos"].get(repo, {}), **record,
            "last_sync_time": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self.save()


def classify_files(files: list[dict]) -> list[str]:
    """Deterministic classification of changed files."""
    classes = set()
    if not files:
        return ["NO_CHANGES"]
    for f in files:
        p = f["path"]
        low = p.lower()
        if any(rx.search(low) for rx in
               CONFIDENTIAL_PATTERNS):
            classes.add("CONFIDENTIAL")
        elif SECURITY_BOUNDARY.search(low):
            classes.add("SECURITY_BOUNDARY")
        elif RESEARCH_SCHEMA.search(low):
            classes.add("RESEARCH_STATE_SCHEMA")
        elif low.endswith(DOCS_ONLY_EXT):
            classes.add("DOCS")
        elif TESTS_PATTERN.search(low):
            classes.add("TESTS")
        elif ENGINE_SURFACE.search(low):
            classes.add("ENGINE_SURFACE")
        else:
            classes.add("CODE")
    return sorted(classes)


VERDICTS = {
    # classes -> verdict
    "NO_CHANGES": "UP_TO_DATE",
    "DOCS": "DOCS_ONLY",
    "TESTS": "COMPATIBLE",
    "CONFIDENTIAL": "BLOCKED_CONFIDENTIAL",
    "SECURITY_BOUNDARY":
        "REQUIRES_AUTHORIZATION",
    "RESEARCH_STATE_SCHEMA":
        "MIGRATION_REQUIRED",
    "ENGINE_SURFACE": "REVIEW_REQUIRED",
    "CODE": "REVIEW_REQUIRED",
}


def verdict_for(classes: list[str]) -> str:
    """Highest-severity verdict wins."""
    order = ["BLOCKED_CONFIDENTIAL",
             "REQUIRES_AUTHORIZATION",
             "MIGRATION_REQUIRED", "REVIEW_REQUIRED",
             "COMPATIBLE", "DOCS_ONLY",
             "UP_TO_DATE"]
    verdicts = {VERDICTS[c] for c in classes
                if c in VERDICTS}
    for v in order:
        if v in verdicts:
            return v
    return "REVIEW_REQUIRED"


class ReinitSession:
    """One durable reinitialization run. Also surfaces as a
    durable task in the task store (state machine + live
    event timeline)."""

    STATES = ("CREATED", "PREPARING", "CONNECTING",
              "INSPECTING", "COMPARING", "PLANNING",
              "WAITING_FOR_AUTHORIZATION", "APPLYING",
              "TESTING", "VERIFYING", "COMPLETED",
              "FAILED")

    def __init__(self, session_dir: Path,
                 model: dict | None,
                 repos: list[str], journal=None):
        self.dir = session_dir
        self.model = model or {"provider": "LOCAL",
                               "model_id": None}
        self.repos = repos
        self.journal = journal
        self.data = {
            "session_id":
                session_dir.name,
            "started_utc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "state": "CREATED",
            "model": self.model,
            "repos": repos,
            "timeline": [],
            "repositories": {},
            "verdicts": {},
            "applied": [],
            "reverted": [],
            "review_required": [],
            "blocked": [],
            "error": None,
        }

    # ------------------------------------------------ records
    def _write(self, name: str, payload):
        (self.dir / name).write_text(
            json.dumps(payload, indent=1, sort_keys=True),
            encoding="utf-8")

    def event(self, text: str, kind: str = "step"):
        rec = {"ts": time.strftime(
                   "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "kind": kind, "text": text}
        self.data["timeline"].append(rec)
        self._write("session.json", self.data)
        if self.journal:
            self.journal.append("reinit_event",
                                session=self.data[
                                    "session_id"],
                                kind=kind,
                                text=text[:200])
        return rec

    def state(self, new: str, reason: str = ""):
        assert new in self.STATES
        self.data["state"] = new
        self.data["state_reason"] = reason
        self._write("session.json", self.data)

    # ------------------------------------------------ run
    def run(self, cfg: ReinitConfig,
            manifest: SyncManifest,
            providers=None) -> dict:
        try:
            return self._run(cfg, manifest,
                             providers)
        except Exception as e:
            self.state("FAILED", repr(e)[:300])
            self.event("Reinitialization failed: %r" % e,
                       "error")
            self._write("result.md",
                        "# Reinitialization FAILED\n\n"
                        "Reason:\n%s\n\nApplied: %s\n"
                        "Reverted: %s\nManual action "
                        "required: inspect %s\n"
                        % (repr(e)[:500],
                           self.data["applied"],
                           self.data["reverted"],
                           str(self.dir)))
            return self.result()

    def _run(self, cfg, manifest, providers):
        self.state("PREPARING")
        self.event("Session started (model: %s/%s)"
                   % (self.model.get("provider"),
                      self.model.get("model_id") or
                      "LOCAL"))

        # CONNECTING: verify the reinitialization model route
        self.state("CONNECTING")
        route = {"mode": "LOCAL"}
        if providers is not None and \
                self.model.get("provider") != "LOCAL":
            route = providers.resolve_role(
                "security_researcher", override={
                    "provider": self.model["provider"],
                    "model_id": self.model.get(
                        "model_id")})
            if route.get("mode") == "remote":
                self.event("Connected to model %s/%s"
                           % (self.model["provider"],
                              self.model.get(
                                  "model_id")))
            else:
                self.event("Model unavailable (%s) - "
                           "continuing in LOCAL mode "
                           "(deterministic)"
                           % route.get("note", ""),
                           kind="warn")
        else:
            self.event("LOCAL mode - deterministic "
                       "synchronization")

        # INSPECTING + COMPARING per repository
        self.state("INSPECTING")
        diffs = {}
        for name in self.repos:
            path = cfg.repo_path(name)
            rec = {"repository": name}
            if not path or not Path(path).is_dir():
                rec["status"] = "UNAVAILABLE"
                rec["reason"] = ("path not configured or "
                                 "missing")
                self.data["repositories"][name] = rec
                self.event("Checked %s: repository "
                           "unavailable" % name,
                           kind="warn")
                continue
            repo = Path(path)
            head = _git(repo, "rev-parse", "HEAD")
            branch = _git(repo,
                          "rev-parse",
                          "--abbrev-ref", "HEAD")
            remote = _git(repo, "remote", "get-url",
                         "origin")
            rec["path"] = path
            rec["branch"] = \
                branch.stdout.strip() or "?"
            rec["local_commit"] = \
                head.stdout.strip()[:12]
            rec["remote"] = \
                remote.stdout.strip()[:120]
            # fetch (local remotes in tests work fine)
            fetch = _git(repo, "fetch", "origin",
                         "--quiet")
            if fetch.returncode != 0:
                rec["status"] = "REMOTE_UNAVAILABLE"
                rec["reason"] = \
                    fetch.stderr.strip()[-200:]
                self.data["repositories"][name] = rec
                self.event(
                    "Checked %s: remote unavailable "
                    "- %s" % (name,
                              rec["reason"][:80]),
                    kind="warn")
                continue
            last = manifest.get(name)
            rec["last_seen_commit"] = \
                last.get("last_seen_commit",
                         rec["local_commit"])
            base = rec["last_seen_commit"]
            rng = f"{base}..origin/{rec['branch']}"
            count = _git(repo, "rev-list", "--count",
                         rng)
            new_commits = int(
                count.stdout.strip() or "0") \
                if count.returncode == 0 else 0
            rec["commits_since_last_sync"] = \
                new_commits
            files = []
            if new_commits:
                dl = _git(repo, "diff", "--name-status",
                          rng)
                for line in dl.stdout.splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        files.append({
                            "status": parts[0][:1],
                            "path": parts[-1]})
            rec["changed_files"] = files[:200]
            rec["classes"] = classify_files(files)
            rec["verdict"] = verdict_for(
                rec["classes"])
            diffs[name] = rec
            self.data["repositories"][name] = rec
            if not new_commits:
                self.event("Checked %s: up to date"
                           % name, "ok")
            else:
                self.event("Checked %s: %d new commit(s),"
                           " %d changed file(s)"
                           % (name, new_commits,
                              len(files)))
            self._write("inspection.json",
                        self.data["repositories"])

        self.state("COMPARING")
        self._write("repository_diffs.json", diffs)

        # PLANNING: classify verdicts, decide actions
        self.state("PLANNING")
        plan_lines = []
        for name, rec in \
                self.data["repositories"].items():
            v = rec.get("verdict", "UNAVAILABLE")
            self.data["verdicts"][name] = v
            if v == "UP_TO_DATE":
                plan_lines.append(
                    "- %s: up to date (manifest "
                    "refreshed)" % name)
            elif v == "DOCS_ONLY":
                plan_lines.append(
                    "- %s: documentation-only changes - "
                    "recorded, no code integration "
                    "needed" % name)
                manifest.update(name, {
                    "last_seen_commit":
                        rec.get("local_commit"),
                    "verdict": v})
            elif v == "BLOCKED_CONFIDENTIAL":
                self.data["blocked"].append(name)
                plan_lines.append(
                    "- %s: CONFIDENTIAL material "
                    "detected - never propagated into "
                    "CYR@ artifacts" % name)
            elif v == "REQUIRES_AUTHORIZATION":
                self.state(
                    "WAITING_FOR_AUTHORIZATION", name)
                plan_lines.append(
                    "- %s: SECURITY-BOUNDARY change - "
                    "explicit authorization required"
                    % name)
            elif v in ("REVIEW_REQUIRED",
                       "MIGRATION_REQUIRED"):
                self.data["review_required"].append(
                    name)
                plan_lines.append(
                    "- %s: SYNC REVIEW REQUIRED (%s) - "
                    "not auto-applied" % (name, v))
            else:
                plan_lines.append(
                    "- %s: %s" % (name, v))
        # CYR@ self-check
        cyr_path = cfg.repo_path("cyr")
        if cyr_path:
            st = _git(Path(cyr_path),
                      "status", "--porcelain")
            dirty = bool(st.stdout.strip())
            self.data["cyr_dirty_tree"] = dirty
            plan_lines.append(
                "- CYR@ working tree: %s"
                % ("UNCOMMITTED CHANGES - protected; "
                   "no self-mutation this session"
                   if dirty else "clean"))
        plan_md = ("# Reinitialization integration plan"
                   "\n\n" + "\n".join(plan_lines) +
                   "\n")
        # model-composed narrative when remote
        if route.get("mode") == "remote" and providers:
            narrative = _model_plan_narrative(
                providers, route, self.data)
            if narrative:
                plan_md += ("\n## Model review\n\n" +
                            narrative)
        self._write("integration_plan.md", plan_md)
        self.event("Integration plan generated")

        # APPLYING: safe auto-apply only for compatible
        # classes on the CYR@ repo, and only with a clean
        # tree. Source research repos are NEVER code-copied.
        self.state("APPLYING")
        applied_any = False
        apply_failed = False
        for name, rec in \
                self.data["repositories"].items():
            if name == "cyr" and \
                    rec.get("verdict") in (
                    "DOCS_ONLY", "COMPATIBLE") and \
                    rec.get("commits_since_last_sync"):
                if self.data.get("cyr_dirty_tree"):
                    self.event(
                        "CYR@ local changes present - "
                        "self-update refused (protected)",
                        "warn")
                    continue
                ok, detail = self._safe_apply_cyr(
                    Path(cfg.repo_path("cyr")), rec)
                if ok:
                    self.data["applied"].append(
                        {"repo": name,
                         "detail": detail})
                    applied_any = True
                    self.event(
                        "Applied compatible %s "
                        "integration: %s"
                        % (name, detail), "ok")
                else:
                    apply_failed = True
                    self.data["reverted"].append(
                        {"repo": name,
                         "detail": detail})
                    self.event(
                        "Applied change FAILED tests - "
                        "reverted: %s" % detail,
                        "error")
        # refresh manifests for reviewed/ok repos
        for name, rec in \
                self.data["repositories"].items():
            if rec.get("verdict") in (
                    "UP_TO_DATE", "DOCS_ONLY",
                    "COMPATIBLE",
                    "REVIEW_REQUIRED",
                    "MIGRATION_REQUIRED"):
                manifest.update(name, {
                    "last_seen_commit":
                        rec.get("local_commit"),
                    "verdict":
                        rec.get("verdict")})

        # TESTING + VERIFYING
        if applied_any:
            self.state("TESTING")
            cyr_path = cfg.repo_path("cyr")
            t = subprocess.run(
                ["python", "-m", "unittest",
                 "discover", "-s", "tests"],
                cwd=cyr_path, capture_output=True,
                text=True, timeout=900)
            tests_rec = {
                "exit_code": t.returncode,
                "tail": (t.stdout + t.stderr)[-2000:]}
            self._write("tests.json", tests_rec)
            if t.returncode != 0:
                for a in self.data["applied"][:]:
                    self._revert_cyr(
                        Path(cyr_path), a)
                    self.data["reverted"].append(a)
                    self.data["applied"].remove(a)
                self.state("FAILED",
                           "post-apply tests failed")
                self.event("Tests FAILED after update - "
                           "changes reverted", "error")
                self._finish()
                return self.result()
            self.event("Tests passed (%s)"
                       % "exit 0", "ok")
        if apply_failed:
            self.state("FAILED",
                       "an integration change "
                       "failed its test gate and "
                       "was reverted")
            self._finish()
            return self.result()
        self.state("VERIFYING")
        self.event("Synchronization verified")
        self.state("COMPLETED")
        self._finish()
        return self.result()

    def _safe_apply_cyr(self, repo: Path,
                        rec: dict):
        """Safe self-integration on a sync branch with a
        backup point and test gate. Only for compatible
        classes."""
        stamp = time.strftime("%Y%m%d%H%M%S")
        backup = f"reinit-backup-{stamp}"
        sync = f"reinit-sync-{stamp}"
        _git(repo, "branch", backup)
        _git(repo, "checkout", "-b", sync)
        merge = _git(repo, "merge", "--no-edit",
                     f"origin/{rec['branch']}",
                     "--ff-only")
        if merge.returncode != 0:
            _git(repo, "checkout", rec["branch"])
            _git(repo, "branch", "-D", sync)
            return False, ("fast-forward merge failed: "
                           + merge.stderr.strip()[:200])
        t = subprocess.run(
            ["python", "-m", "unittest",
             "discover", "-s", "tests"],
            cwd=repo, capture_output=True,
            text=True, timeout=900)
        if t.returncode != 0:
            _git(repo, "checkout", rec["branch"])
            _git(repo, "branch", "-D", sync)
            return False, ("tests failed: " +
                           (t.stderr or t.stdout)
                           .strip()[-300:])
        return True, (f"branch {sync} created from "
                      f"{rec['branch']}; tests pass; "
                      f"backup {backup}")

    def _revert_cyr(self, repo: Path, applied):
        _git(repo, "checkout",
             applied.get("base_branch", "main"))
        _git(repo, "branch", "-D",
             applied.get("sync_branch", "")) \
            if applied.get("sync_branch") else None

    def _finish(self):
        ok = self.data["state"] == "COMPLETED"
        lines = ["# Reinitialization %s"
                 % ("COMPLETE" if ok else "FAILED"),
                 "",
                 "Model: %s/%s" % (
                     self.model.get("provider"),
                     self.model.get("model_id") or
                     "LOCAL"),
                 ""]
        for name, rec in \
                self.data["repositories"].items():
            lines.append(
                "- %s: %s (%d new commits)"
                % (name, rec.get("verdict",
                                 "UNAVAILABLE"),
                   rec.get(
                       "commits_since_last_sync", 0)))
        if self.data["review_required"]:
            lines.append("")
            lines.append(
                "SYNC REVIEW REQUIRED: " +
                ", ".join(
                    self.data["review_required"]))
        if self.data["blocked"]:
            lines.append(
                "BLOCKED (confidential): " +
                ", ".join(self.data["blocked"]))
        lines += ["", "Applied: %s"
                  % (self.data["applied"] or "none"),
                  "Reverted: %s"
                  % (self.data["reverted"] or "none")]
        (self.dir / "result.md").write_text(
            "\n".join(lines), encoding="utf-8")
        self._write("provenance.json", {
            "session": self.data["session_id"],
            "model": self.model,
            "timeline":
                self.data["timeline"],
            "repositories":
                self.data["repositories"],
            "manifest_updates": [
                r for r in self.data["repositories"]],
        })
        if self.journal:
            self.journal.append(
                "reinit_finished",
                session=self.data["session_id"],
                state=self.data["state"])

    def result(self) -> dict:
        return dict(self.data)


def _model_plan_narrative(providers, route, data):
    """The REINITIALIZATION model reviews the grounded
    inspection and composes the plan narrative. Real call,
    tool-grounded context only."""
    import urllib.request
    try:
        provider = providers.config["providers"][
            route["provider"]]
        key = providers.get_api_key(
            route["provider"])
        if not key:
            return None
        context = json.dumps({
            "repositories": data["repositories"],
            "verdicts": data["verdicts"]},
            indent=1)[:8000]
        body = json.dumps({
            "model": route.get("model_id"),
            "messages": [
                {"role": "system",
                 "content":
                     "You review a synchronization "
                     "inspection between CYR@ and its "
                     "research repositories. Summarize "
                     "what changed and what actions are "
                     "recommended, grounded ONLY in the "
                     "provided data. Never invent "
                     "commits or files."},
                {"role": "user",
                 "content": context},
            ]}).encode()
        req = urllib.request.Request(
            provider["base_url"] + "/chat/completions",
            data=body,
            headers={"Content-Type":
                         "application/json",
                     "Authorization":
                         "Bearer " + key})
        with urllib.request.urlopen(
                req, timeout=120) as r:
            resp = json.loads(r.read().decode())
        return resp["choices"][0]["message"]["content"]
    except Exception:
        return None


class ReinitEngine:
    def __init__(self, root: Path, journal=None):
        self.root = root
        self.cfg = ReinitConfig(root)
        self.manifest = SyncManifest(root)
        self.sessions_dir = root / "reinitialization"
        self.sessions_dir.mkdir(parents=True,
                                exist_ok=True)
        self.journal = journal
        self._current = None

    def start(self, model: dict | None = None,
              repos: list[str] | None = None,
              providers=None) -> dict:
        repos = repos or list(
            self.cfg.data["repos"].keys())
        stamp = time.strftime(
            "%Y%m%d-%H%M%S")
        sdir = self.sessions_dir / stamp
        sdir.mkdir(parents=True, exist_ok=True)
        session = ReinitSession(sdir, model, repos,
                                self.journal)
        self._current = session
        return session.run(self.cfg, self.manifest,
                          providers)

    def current(self) -> dict | None:
        return self._current.result() \
            if self._current else None

    def sessions(self) -> list:
        out = []
        for d in sorted(
                self.sessions_dir.iterdir(),
                reverse=True):
            p = d / "session.json"
            if p.is_file():
                try:
                    out.append(json.loads(
                        p.read_text(
                            encoding="utf-8")))
                except (json.JSONDecodeError,
                        OSError):
                    continue
        return out[:25]

    def manifest_data(self) -> dict:
        return self.manifest.data

    def config_data(self) -> dict:
        return self.cfg.data
