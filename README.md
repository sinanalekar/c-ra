# VERITAS environment

A local-first, autonomous security-research **operating
environment** for authorized Apple security research: the
coordinator, evidence judge, falsification gates, provenance
system, and desktop console wrapping five first-class research
engines.

> It is NOT a chatbot, dashboard toy, generic LLM wrapper, or
> plugin manager. It optimizes for scientific validity,
> reproducibility, provenance, responsible disclosure, and human
> control - never for finding count.

## Architecture

```
Desktop UI (Tauri shell / browser)  <->  local backend (127.0.0.1)
        |
Research Orchestrator   (VERITAS = coordinator + evidence judge)
  +-- CIDER adapter     experiment machine
  +-- Frontier adapter  method/invention discovery
  +-- HYDRA adapter     Apple firmware/kernel statics
  +-- SEEK adapter      empirical/network evidence
        |
Evidence Engine -> Falsification Gate -> Reproduction Gate
        v
SUPPORTED / REFUTED / INCONCLUSIVE / BLOCKED   (journal-verified)
```

Full Phase-1 inspection: `docs/ARCHITECTURE_MAP.md`.

## The core loop, enforced by the orchestrator

```
target -> hypothesis -> experiment design -> controlled execution
-> observation -> negative controls -> falsification ->
independent reproduction -> evidence grading -> disposition
```

A successful original experiment without negative controls AND
independent reproduction is **never** dispositioned SUPPORTED -
the gates downgrade it to INCONCLUSIVE and the journal records
why. Insufficient authorization is a recorded BLOCKED disposition,
not a silent failure.

## Honest by construction

- Engines that are missing report `unavailable` - never faked
  (tested).
- Firmware scans without an artifact: BLOCKED. Network
  experiments without the `network` capability + exact scope:
  BLOCKED.
- HYDRA output is always `STATIC_CANDIDATE`; Frontier
  certificates are method results, never real-vulnerability
  claims; SEEK's real-world observations stay owned by SEEK's
  provenance.
- The journal is hash-chained; `journal verify` fails closed on
  tampering (tested).
- Permissions are deny-by-default, inspectable, never silently
  expanded; high-risk capabilities need explicit confirmation.
- Model roles without a configured provider read
  `LOCAL (unconfigured)` - the system never pretends a model
  reviewed anything.

## Quick start

```bash
# backend (loopback only)
pip install -e .
python -m environment.server        # 127.0.0.1:8765

# UI (dev mode; proxies /api to the backend)
cd ui && npm install && npm run dev  # http://localhost:5175

# desktop shell (packaging phase)
cd src-tauri && cargo tauri dev
```

Click **run vertical slice** in the UI: it grants
`experimental_execution`, registers a hypothesis on an Apple
target, dispatches it to CIDER's real runtime, and walks the
evidence through the falsification + reproduction gates into a
journaled disposition.

## Tests

```bash
python -m unittest discover -s tests   # 34 tests
```

Covered: journal tamper detection, permission boundaries
(deny-by-default, scope, high-risk confirmation), workspace
confinement (traversal rejected), provider schema enforcement,
target universe coverage (recorded-experiments-only), the
five-engine adapter contract, and the end-to-end vertical slice
including the deliberate BLOCKED paths.

## Repository layout

```
environment/         Python backend (orchestrator, gates, adapters)
  engines/           ResearchEngine adapters for all five engines
  permissions.py     least-privilege authorization layer
  providers.py       model/provider abstraction (LOCAL mode honest)
  journal.py         hash-chained environment provenance
  targets.py         Apple target universe + coverage engine
  workspace.py       permission-gated local file access
ui/                  React + TypeScript console
src-tauri/           Tauri 2 desktop shell scaffold
docs/                ARCHITECTURE_MAP.md (the Phase-1 inspection)
tests/               34 tests incl. the vertical slice
```

## Scope and authorization

Research targets researcher-owned accounts, devices, data, and
explicitly authorized bug-bounty targets. The system does not
build workflows for credential theft, unauthorized access,
persistence, destructive DoS, data exfiltration, malware, or
cross-user exploitation. Human approval is mandatory before any
external disclosure or submission.
