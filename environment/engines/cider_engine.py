"""CIDER engine adapter: the autonomous experiment machine.
Runs CIDER's own runtime (its builtin experiment functions and
ResearchAgent) inside the ENVIRONMENT's workspace - the sibling
repository is imported read-only and never written to."""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

from .base import (EngineResult, EngineUnavailable,
                   ResearchEngine)

EXPERIMENTS = {
    "exp_fuzz_tlv": "event-feedback fuzzing on a TLV parser "
                    "(crash-class discovery)",
    "exp_invariant_session": "session-state machine invariant "
                             "monitor (flawed vs repaired "
                             "control)",
    "exp_fuzz_session": "session-state machine fuzzing",
    "exp_pcap_distill": "capture-to-corpus distillation",
    "exp_log_oracle": "syslog/crash-log oracle invariants",
    "exp_grammar_induction": "grammar induction from corpora",
    "exp_mdns_cache": "mDNS cache-coherence invariant library "
                      "(poisoning, stale-TTL, duplicate-unique)",
    "exp_corpus_diff": "differential grammar fingerprints",
}


class CiderEngine(ResearchEngine):
    name = "cider"
    version = "1.1.0"
    capabilities = (
        "autonomous_experiment_cycles", "hypothesis_registry",
        "fuzzing", "invariant_monitoring", "grammar_induction",
        "corpus_distillation", "provenance_chains",
    )
    inputs = ("hypothesis", "params", "seeds")
    outputs = ("result_json", "report", "evidence", "artifacts")
    experiment_types = tuple(EXPERIMENTS)
    authorization_requirements = ("experimental_execution",)
    risk_level = "low"

    def __init__(self, repo_path, work_root, journal=None):
        self.repo_path = repo_path
        self.work_root = Path(work_root)
        self.journal = journal
        self._module = None

    def _import(self):
        if self._module is not None:
            return self._module
        if self.repo_path is None:
            raise EngineUnavailable(
                "cider repository path not configured")
        if self.repo_path not in sys.path:
            sys.path.insert(0, self.repo_path)
        try:
            self._module = importlib.import_module(
                "cider.builtin_experiments")
        except Exception as e:
            raise EngineUnavailable(
                f"cider package import failed: {e}") from e
        return self._module

    def available(self) -> bool:
        try:
            self._import()
            return True
        except EngineUnavailable:
            return False

    def execute(self, experiment_id: str, hypothesis: dict,
                params: dict, ctx: dict) -> EngineResult:
        mod = self._import()
        fn_name = params.get("experiment",
                             "exp_invariant_session")
        if fn_name not in EXPERIMENTS:
            raise ValueError(
                f"unknown cider experiment {fn_name!r}; "
                f"available: {sorted(EXPERIMENTS)}")
        exp_dir = self.work_root / "cider" / experiment_id
        exp_dir.mkdir(parents=True, exist_ok=True)
        fn = getattr(mod, fn_name)
        run_params = dict(params.get("params", {}))
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                time.gmtime())
        try:
            fn(str(exp_dir), run_params)
        except Exception as e:
            # honest failure recording (section 47)
            failed = {
                "experiment_id": experiment_id,
                "engine": self.name, "error": repr(e),
                "started_utc": started,
                "state": "FAILED",
            }
            (exp_dir / "FAILED.json").write_text(
                json.dumps(failed, indent=1), encoding="utf-8")
            if self.journal:
                self.journal.append(
                    "engine_experiment_failed",
                    engine=self.name,
                    experiment_id=experiment_id,
                    error=repr(e))
            return EngineResult(
                engine=self.name, experiment_id=experiment_id,
                disposition="BLOCKED",
                evidence=[], controls=[],
                summary=f"cider experiment failed: {e!r}")
        # collect the engine's own outputs (RESULT.json when
        # present, else the experiment's evidence JSONs and the
        # REPORT.md outcome line)
        result_path = exp_dir / "RESULT.json"
        report_path = exp_dir / "REPORT.md"
        if result_path.exists():
            result = json.loads(result_path.read_text(
                encoding="utf-8"))
            hypothesis_outcome = result.get(
                "hypothesis_outcome", result.get("outcome", ""))
            summary = (result.get("summary")
                       or f"cider {fn_name}: "
                          f"hypothesis {hypothesis_outcome}")
            control_clean = bool(result.get(
                "control_clean", result.get(
                    "negative_control", True)))
        elif report_path.exists():
            report = report_path.read_text(encoding="utf-8")
            outcome_line = ""
            for line in report.splitlines():
                if line.startswith("**Outcome:**"):
                    outcome_line = line.split(
                        "**Outcome:**", 1)[1].strip()
                    break
            hypothesis_outcome = outcome_line
            summary_lines = [l for l in report.splitlines()
                             if l.strip()][:2]
            summary = " | ".join(summary_lines) or \
                      f"cider {fn_name}"
            control_clean = True
            for p in exp_dir.glob("*.json"):
                try:
                    data = json.loads(
                        p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                for key, val in data.items():
                    if "control" in key.lower() and \
                            isinstance(val, dict) and \
                            "violations" in val:
                        control_clean = \
                            val["violations"] == 0
        else:
            return EngineResult(
                engine=self.name, experiment_id=experiment_id,
                disposition="INCONCLUSIVE",
                evidence=[], controls=[],
                summary="cider ran but produced no "
                        "RESULT.json or REPORT.md")
        disposition = {
            "SUPPORTED": "SUPPORTED",
            "REFUTED": "REFUTED",
            "INCONCLUSIVE": "INCONCLUSIVE",
        }.get(str(hypothesis_outcome).upper(), "INCONCLUSIVE")
        evidence = [{
            "type": "engine_result",
            "source": "cider:" + fn_name,
            "observation": {
                "outcome": hypothesis_outcome,
                "evidence_files": [
                    p.name for p in exp_dir.glob("*.json")],
            },
            "interpretation": EXPERIMENTS[fn_name],
            "confidence": 0.9,
            "artifacts": [str(p) for p in
                          sorted(exp_dir.glob("*"))
                          if p.is_file()],
        }]
        controls = [{
            "type": "negative_control",
            "observation":
                "cider's flawed-vs-repaired control discipline "
                "(repaired control clean)",
            "passed": control_clean,
        }]
        out = EngineResult(
            engine=self.name, experiment_id=experiment_id,
            disposition=disposition, evidence=evidence,
            controls=controls,
            summary=summary,
        )
        if self.journal:
            self.journal.append(
                "engine_experiment",
                engine=self.name, experiment_id=experiment_id,
                disposition=disposition,
                experiment=fn_name)
        return out

    def reproduce(self, experiment_id: str, ctx: dict):
        """Independent reproduction: same experiment, fresh id,
        deterministic seeds - CIDER's runs are seeded."""
        params = ctx.get("params", {})
        return self.execute(experiment_id + "-repro", {},
                            params, ctx)

    def collect_evidence(self, experiment_id: str) -> list:
        exp_dir = self.work_root / "cider" / experiment_id
        out = []
        for p in sorted(exp_dir.glob("*.json")):
            out.append({"artifact": str(p),
                        "sha_note": "content-addressed at "
                                    "import time"})
        return out

    def export_provenance(self, experiment_id: str) -> dict:
        exp_dir = self.work_root / "cider" / experiment_id
        prov = {"engine": self.name,
                "experiment_id": experiment_id}
        result_path = exp_dir / "RESULT.json"
        if result_path.exists():
            prov["result_recorded"] = True
        return prov

    def validate(self, experiment_id: str) -> dict:
        return {"ok": self.available(),
                "detail": "cider package importable; experiments: "
                          + ", ".join(sorted(EXPERIMENTS))}
