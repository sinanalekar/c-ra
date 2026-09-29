# Architecture Map — the Five Research Engines

Phase-1 deliverable (master prompt section 48): inspection of
the five repositories, their reusable code, provenance systems,
entry points, conflicts, and the adapters this environment builds.
Everything below was verified against the actual repositories
(VERITAS at `C:\Users\SINAN\veritas`, the others via the study
clones; all five are read-only to this environment).

## Combined architecture

```
VERITAS Desktop UI (ui/, Tauri shell)
        |
        v  local IPC (loopback only)
Research Orchestrator (environment/orchestrator.py)
   VERITAS = coordinator + evidence judge + falsification gates
        |
        +-- CIDER adapter    (experiment machine)
        +-- Frontier adapter  (method/invention discovery)
        +-- HYDRA adapter     (Apple firmware/kernel statics)
        +-- SEEK adapter      (empirical/network evidence)
        |
        v
Evidence Engine -> Falsification Gate -> Reproduction Gate
        |
        v
SUPPORTED / REFUTED / INCONCLUSIVE / BLOCKED (journal-verified)
```

## Engine inventory

### 1. VERITAS — coordinator + evidence judge (`C:\Users\SINAN\veritas`)
- **State**: v2.3, cycle 53; 41 hypotheses (40 SUPPORTED, 1
  REFUTED), 26 VALIDATED findings, journal 355+ entries chain
  VALID, Brier 0.0035, 143/143 tests.
- **Entry points**: `python -m veritas
  {init|run|status|report|verify|findings|calibration|memory|surface|diff}`;
  Python package `veritas` (planner, program, provenance,
  discovery, causal, blindspots, invention, dialectic,
  instruments/*).
- **Provenance**: hash-chained `workspace/journal.jsonl` +
  `HEAD`, fail-closed `verify`, V-09 canonicalization law.
- **Schemas**: hypotheses.json (falsifiable statements with
  falsification criteria), findings.json (tier VALIDATED +
  recorded challenge evidence), experiment RESULT/REPORT pairs
  under experiments/EXP-*/.
- **Reusable here**: the whole evidence/falsification discipline;
  the orchestrator adapts its gates (negative controls,
  independent reproduction, dual-gate promotion).
- **Adapter**: in-process import (`environment/engines/
  veritas_engine.py`); repository NEVER written to.

### 2. CIDER — experiment machine (`cider-agent`, v1.1.0)
- **Entry points**: `cider.cli:main`, package `cider` with
  `ResearchAgent(root, workspace, experiments_dir)` exposing
  `init_seed_hypotheses / run_cycle / run_frontier / verify_
  provenance / status_report`, plus standalone builtin
  experiments: exp_fuzz_tlv, exp_invariant_session,
  exp_fuzz_session, exp_pcap_distill, exp_log_oracle,
  exp_grammar_induction, exp_mdns_cache, exp_corpus_diff.
- **Provenance**: its own hash-chained workspace journal (42
  entries, 51/51 tests at cycle 3).
- **Adapter**: in-process import of `cider.builtin_experiments`;
  experiments run inside THIS environment's workspace
  (`environment/engines/cider_engine.py`); outcomes harvested
  from RESULT.json / experiment evidence JSONs / REPORT.md
  outcome lines honestly.

### 3. Frontier — method/invention discovery (`frontier-algorithm-discovery`, engine v3)
- **Entry points**: package `frontier` (pipeline, cli,
  certificate, search, detectors, features); FINAL_REPORT_V6,
  REPRODUCIBILITY commands, 49/49 tests.
- **Key results**: two-stage precision-floored rule discovery,
  DiscoveryCertificates (padded A/E/I, bit-exact reproduction),
  N-23 no-free-lunch negative, seed-fragility fixed via
  stratified seeding + mixture FPR cap.
- **Adapter**: in-process import of `frontier.pipeline`
  (`frontier_engine.py`); method campaigns run on explicit
  request; certificates are METHOD results, never
  real-vulnerability claims.

### 4. HYDRA — Apple firmware/kernel statics (`hydra-apple-vrs`, v0.1.0)
- **Entry points**: package `hydra`, tools (kernelcache slice
  rebase, x86 kext analysis/diff), results/ artifacts (iOS 27.0
  vuln scan: 1,311 bounds-check + 846 overflow candidates; ANE
  triage 74 -> 0; iPhone 16 corpus).
- **Real evidence**: pattern scans on iPhone 17,3 iOS 26.0
  kernelcache (197,263 functions), macOS 15->26 bootkc
  differential.
- **Adapter**: in-process import (`hydra_engine.py`);
  firmware experiments require the `firmware_tooling`
  capability AND a target artifact; without an artifact the
  adapter returns BLOCKED (honest). All output remains
  STATIC_CANDIDATE.

### 5. SEEK — empirical/network evidence (`seek`)
- **State**: journaled daemon + research sessions (T1..T117):
  the lockdown trust-record bounty finding (SUBMITTED to Apple,
  OE1107708846) and the Apple web hunt (CL.TE smuggling,
  REQUEST_SMUGGLING_ONLY classification, 8 stop conditions).
- **Method laws absorbed (VERITAS wave 5)**: differential
  attribution (T65), five-state evidence matrix, exhaustion
  accounting (T115), honest impact downgrades (T91->T92).
- **Adapter**: journal bridge (`seek_engine.py`) - live network
  experiments require the `network` capability + exact scope;
  without them BLOCKED. Real-world observations remain owned by
  SEEK's provenance; never re-claimed here.

## Conflicts / duplication and resolution

- **Four journals** (environment, veritas, cider, seek): kept
  SEPARATE. The environment journal records coordination state;
  engine journals record engine-internal research. The
  orchestrator's export_provenance bridges heads, never rewrites
  them.
- **Hypothesis schemas** differ (veritas: falsification criteria
  + families; cider: EXP-*/H-* pairs): the environment's
  hypothesis record (EH-*) is the superset with an explicit
  null hypothesis; engine-native schemas preserved inside
  adapters.
- **Evidence grading** overlaps (veritas findings.json tiers vs
  seek's PROVEN/CORROBORATED/INFERRED matrix): the environment
  gate requires negative controls + independent reproduction
  for SUPPORTED; finer partitioning delegated to the evidence
  objects' own fields.
- **Duplicated discovery machinery** (veritas discovery vs
  frontier search vs cider grammar induction): NOT merged. Each
  engine keeps its specialty; the orchestrator routes by
  experiment type.

## Adapter contract (section 9)

`ResearchEngine`: name, version, capabilities, inputs, outputs,
experiment_types, authorization_requirements, risk_level,
validate(), execute(), reproduce(), collect_evidence(),
export_provenance(). Unavailable engines raise
EngineUnavailable and report available=False - never faked
(tested: test_honest_unavailable).

## Gates enforced by the coordinator

1. **Authorization gate** - deny by default; insufficient
   authorization => BLOCKED disposition (journaled), never an
   exception swallowed by the UI.
2. **Negative-control gate** - SUPPORTED requires recorded
   controls that pass.
3. **Reproduction gate** - SUPPORTED requires independent
   reproduction (fresh id, same seeds - engines are
   deterministic).
4. **Provenance gate** - every transition journaled;
   `journal verify` must stay VALID (tamper-tested).

## What this environment deliberately does NOT do yet

Roadmapped (master prompt phases 3-20), not claimed: packaging
installers, device tooling, live network experiments without
grants, multi-model review with real providers (LOCAL mode is
reported honestly until configured), git-integration UI, report
generation. Each phase lands with tests; no fake completion.
