"""Report generation (master prompt section 39).

The full disclosure-grade report: title, executive summary,
target, scope, authorization, affected version/build,
preconditions, security property, hypothesis, methodology,
reproduction, controls, observed result, evidence, falsification,
impact, limitations, what was NOT demonstrated, reproduction
instructions, timeline, hashes, provenance, disclosure
recommendation. Never exaggerates impact; synthetic-world results
say synthetic; the not-demonstrated list is mandatory."""
from __future__ import annotations

import hashlib
import time


def _sha(blob: str) -> str:
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def generate_report(experiment: dict, hypothesis: dict,
                    target: dict, pipeline: dict | None = None,
                    journal_entries: list | None = None) -> dict:
    """Produce the report record + markdown. The report hashes
    itself into its own provenance section."""
    disposition = experiment.get("disposition", "INCONCLUSIVE")
    is_synthetic = target.get("platform") == "apple" and \
        experiment.get("engine") in ("cider", "frontier",
                                     "veritas") and \
        not target.get("available_artifacts")
    result = experiment.get("result", {})
    evidence = experiment.get("evidence", [])
    controls_ok = experiment.get("negative_controls_pass")
    reproduced = experiment.get("reproduced")

    if disposition == "SUPPORTED":
        impact = ("No real-system impact is claimed. The "
                  "mechanism is demonstrated on the engine's "
                  "controlled research substrate only; "
                  "real-world applicability requires the "
                  "authorized device/service validation phase.")
    elif disposition == "BLOCKED":
        impact = ("Not characterizable: the experiment was "
                  "blocked (missing authorization, inputs, or "
                  "availability). Nothing was demonstrated.")
    else:
        impact = ("Not characterized: the gates did not pass "
                  "(controls=%s, reproduced=%s)."
                  % (controls_ok, reproduced))

    not_demonstrated = []
    if not controls_ok:
        not_demonstrated.append(
            "negative controls were not recorded as passing")
    if not reproduced:
        not_demonstrated.append(
            "independent reproduction was not achieved")
    if disposition != "SUPPORTED":
        not_demonstrated.append(
            "the hypothesis itself (disposition %s)" %
            disposition)
    if is_synthetic:
        not_demonstrated.append(
            "any real Apple product behavior - the result is a "
            "controlled-substrate (engine-world) observation")
    not_demonstrated.append(
        "exploitability, end-user impact, and affected "
        "production versions")

    timeline = []
    for e in journal_entries or []:
        if e.get("experiment_id") == experiment.get(
                "experiment_id") or \
                e.get("hypothesis_id") == hypothesis.get(
                    "hypothesis_id"):
            timeline.append({"ts": e["ts"],
                            "action": e["action"]})
    if not timeline:
        timeline.append({"ts": experiment.get("ts", ""),
                         "action": "experiment_completed"})

    falsification_section = pipeline and \
        next((s for s in pipeline["stages"]
              if s["role"] == "falsification_reviewer"), None)

    lines = [
        "# Security Research Report",
        "",
        "## Title",
        hypothesis.get("claim", "untitled"),
        "",
        "## Executive summary",
        f"Disposition: **{disposition}**. "
        + result.get("summary", "")[:400],
        "",
        "## Target",
        f"{target.get('parent_category')} > "
        f"{target.get('product')} "
        f"({target.get('target_id')})",
        "",
        "## Scope and authorization",
        "Authorized research only. Required capabilities: "
        + ", ".join(target.get(
            "required_capabilities", []))
        + ". The experiment ran under the environment's "
          "least-privilege authorization layer.",
        "",
        "## Affected version/build",
        "Not established by this experiment"
        if is_synthetic else
        (target.get("versions") or "not established"),
        "",
        "## Preconditions",
        "Engine %s available; capabilities granted; "
        "deterministic seeds." % experiment.get("engine"),
        "",
        "## Security property",
        "The property under test is the hypothesis's predicted "
        "invariant; see Hypothesis below.",
        "",
        "## Hypothesis",
        f"**H-claim:** {hypothesis.get('claim', '')}",
        f"**Null hypothesis:** "
        f"{hypothesis.get('null_hypothesis', '')}",
        f"**Falsification conditions:** "
        f"{hypothesis.get('falsification_conditions', '')}",
        "",
        "## Methodology",
        f"Engine: {experiment.get('engine')}; experiment "
        f"{experiment.get('experiment_id')}; the engine's own "
        "instrument ran inside the environment's workspace with "
        "the coordinator's gates applied (negative-control "
        "gate, reproduction gate, provenance gate).",
        "",
        "## Reproduction",
        "Independent reproduction ran as "
        f"{experiment.get('experiment_id')}-repro with the same "
        "seeds (deterministic engines): "
        + ("REPRODUCED" if reproduced else
           "NOT REPRODUCED"),
        "",
        "## Controls",
        "Negative controls: "
        + ("PASSING (repaired/benign control clean)"
           if controls_ok else
           "missing or failing"),
        "",
        "## Observed result",
        result.get("summary", "(see evidence objects)"),
        "",
        "## Evidence",
        f"{len(evidence)} evidence object(s) recorded; "
        "artifacts content-hashed at capture time.",
        "",
        "## Falsification",
        ("Challenge classes demanded by the falsification "
         "reviewer: "
         + ", ".join(falsification_section.get(
             "challenge_classes", [])))
        if falsification_section else
        "Falsification gate: negative controls "
        + ("passed" if controls_ok else "did not pass"),
        "",
        "## Impact",
        impact,
        "",
        "## Limitations",
        "- Controlled research substrate only"
        if is_synthetic else
        "- Scope limited to the authorized target",
        "- Deterministic engine behavior; variance "
          "characterization pending",
        "- Model roles ran in LOCAL mode unless a provider is "
          "configured",
        "",
        "## What was NOT demonstrated",
    ]
    lines += [f"- {n}" for n in not_demonstrated]
    lines += [
        "",
        "## Reproduction instructions",
        "1. Start the local backend "
        "(`python -m environment.server`).",
        f"2. Re-run hypothesis "
        f"`{hypothesis.get('hypothesis_id')}` via "
        "`POST /api/hypotheses/<id>/run`.",
        "3. Deterministic engines regenerate identical "
        "results; compare dispositions and evidence hashes.",
        "",
        "## Timeline",
    ]
    lines += [f"- {t['ts']} - {t['action']}"
              for t in timeline]
    lines += [
        "",
        "## Hashes and provenance",
        "report_sha256[:32] = PENDING (covers the report "
        "body with this line empty)",
        f"experiment_id: "
        f"{experiment.get('experiment_id')}",
        f"hypothesis_id: "
        f"{hypothesis.get('hypothesis_id')}",
        "every transition above is verifiable in the "
        "environment's hash-chained journal.",
        "",
        "## Disclosure recommendation",
    ]
    if disposition == "SUPPORTED" and not is_synthetic:
        lines.append(
            "Human review required before ANY external "
            "disclosure or submission. The environment never "
            "submits externally.")
    else:
        lines.append(
            "No disclosure action: the disposition does not "
            "meet the validated-finding bar, or the result is "
            "a controlled-substrate observation only. Human "
            "review remains mandatory for any future external "
            "step.")
    md = "\n".join(lines)
    # the report hash covers the body with the hash line empty
    # (self-reference resolved deterministically)
    placeholder = ("report_sha256[:32] = PENDING (covers the "
                    "report body with this line empty)")
    sha = _sha(md.replace(placeholder, ""))
    md = md.replace(placeholder,
                    f"report_sha256[:32] = {sha}")
    return {
        "schema": "veritas_environment_report_v1",
        "experiment_id": experiment.get("experiment_id"),
        "hypothesis_id": hypothesis.get("hypothesis_id"),
        "target_id": target.get("target_id"),
        "disposition": disposition,
        "generated_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "markdown": md,
        "sha256": sha,
    }
