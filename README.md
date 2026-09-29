# CYR@

Local-first desktop AI agent harness for authorized security
research: a coordinator, a central authorization layer, real
tool runtimes (terminal, Git, browser, filesystem, computer
use), durable long-running tasks with checkpoints and recovery,
multi-agent specialists, model/provider routing, and the five
security-research engines (VERITAS, CIDER, SEEK, HYDRA,
Frontier) as first-class internal engines.

Loopback-only backend. Deny-by-default authorization. No
capability is ever claimed that is not implemented: unavailable
engines, missing browser drivers, and blocked operations are
reported honestly in the UI and the journal.

## Architecture

```
CYR@ desktop shell (Tauri 2, window title "CYR@")
        |
        v  loopback HTTP (127.0.0.1:8765)
local backend (FastAPI)
   Orchestrator (agents, gates, dispositions)
   Central capability system (deny | allow_once | allow_task |
                             allow_workspace | allow_session)
   Tool runtimes: terminal, Git, browser (Playwright),
                  filesystem workspace, computer use
   Durable tasks + checkpoints + restart recovery
   Memory, artifacts (hash-verified), evidence ledger
        |
        +-- Engine adapters: VERITAS, CIDER, Frontier, HYDRA, SEEK
        v
journal (hash-chained, fail-closed tamper detection)
```

## Quick start

```bash
pip install -e .
python -m environment.server        # 127.0.0.1:8765

cd ui && npm install && npm run dev  # dev console (5175)

# or the packaged desktop app (builds the installer):
powershell -ExecutionPolicy Bypass -File tools\package.ps1
```

## The core loops

Agent loop: understand -> plan -> authorize -> execute ->
observe -> verify -> review -> act -> checkpoint -> report.

Security research loop (VERITAS discipline): target ->
authorization -> hypothesis -> experiment -> negative control
-> reproduction -> evidence -> falsification -> review ->
disposition (SUPPORTED / REFUTED / INCONCLUSIVE / BLOCKED). A
successful original experiment without passing negative
controls AND independent reproduction is never dispositioned
SUPPORTED.

## Capabilities and authorization

One central ledger (`environment/capabilities.py`) gates every
sensitive tool: filesystem.read/write/delete/execute,
terminal.execute, process.spawn, git.read/write/push,
browser.read/navigate/interact/download/upload,
computer.read/interact, network.request, research.execute,
engine.veritas/cider/seek/hydra/frontier. Grant modes: deny,
allow_once (consumed on use), allow_task (bound to a task id),
allow_workspace (path-scoped), allow_session. High-risk
capabilities (git.push, filesystem.delete, computer.interact,
browser.download/upload) additionally require per-operation
confirmation. Nothing bypasses the ledger; every decision is
journaled.

## Tool runtimes (all real)

- **Terminal**: real PowerShell/CMD/Python/Git processes with
  live streaming output, stop/cancel/timeout, and confirmation
  gates for destructive command shapes.
- **Git**: status/diff/log/branches/add/commit/checkout/
  restore/stash/merge/fetch/pull/push with safety gates
  (never silently pushes or discards user changes; refuses
  checkout on dirty trees).
- **Browser**: Playwright/Chromium automation - navigation,
  extraction, clicks, typing, screenshots, downloads, uploads -
  with an http-fetch fallback when the driver is absent
  (reported honestly, interaction disabled - never faked).
  Only http/https; never bypasses auth, CAPTCHAs, paywalls.
- **Computer use**: authorized application launch and process
  inspection. Keyboard/mouse injection and window focusing are
  NOT implemented - reported unavailable, never faked.
- **Filesystem**: workspace-confined, path-traversal-proof
  read/write/delete/search; broader roots require explicit
  allow_workspace grants.

## Tasks, agents, and recovery

Durable tasks (queued/planning/running/waiting_for_user/
paused/blocked/recovering/completed/failed/cancelled) persist
every transition, event, and checkpoint to disk before it is
reported; closing the UI never destroys task state. On boot,
interrupted tasks are marked `recovering` and the recovery
agent resumes them from their last checkpoint.

Nineteen specialist agents run with stable run IDs, checkpointed
inspectable steps, real pause/resume/stop controls (stopping a
terminal agent kills its process), and journaled audit trails.
The review pipeline (researcher -> independent reviewer ->
falsification reviewer -> evidence adjudicator) runs LOCAL
deterministic policies with honest reporting; bound model
providers are called per-role when configured. CYR@ controls
state transitions - models never vote to create truth.

## Providers and models

Arbitrary OpenAI-compatible providers (https only); API keys
stored via the OS credential store (keyring) - never plaintext,
never in Git, journals, or logs. Twelve routable roles
(coordinator, planner, reasoning, coding, research, browser,
terminal, reviewer, independent reviewer, falsification
reviewer, report writer, security researcher) with per-role
model, timeout, retries, streaming, and fallback. Without a
provider the system runs LOCAL mode and says so.

## Reports and evidence

Disclosure-grade reports (Title, Executive summary, Target,
Scope/Authorization, Preconditions, Security property,
Hypothesis, Methodology, Reproduction, Controls, Observed
result, Evidence, Falsification, Impact, Limitations, **What
was NOT demonstrated**, Reproduction instructions, Timeline,
Hashes, Disclosure recommendation). Evidence is a first-class
model with provenance, hashes, confidence, and a monotonic
state machine (OBSERVED -> CORROBORATED -> REPRODUCED ->
VALIDATED). Artifacts are content-hashed with integrity
verification.

## Repository layout

```
environment/            backend (orchestrator, capabilities,
                        terminal, gitops, browser, computer,
                        tasks, memory, artifacts, evidence,
                        agents, providers, reports, routing,
                        targets, workspace, journal, engines/)
ui/                     React + TypeScript console (11 panels)
src-tauri/              Tauri 2 desktop shell + NSIS config
tools/                  packaging pipeline, icon builder
tests/                  89 tests (real runtimes, honest skips)
docs/                   ARCHITECTURE_MAP.md
```

## Version

1.0.0 (canonical: `environment/version.py`; the Python
package, UI, Tauri, installer, and metadata all match).

## Scope and authorization

Research targets researcher-owned accounts, devices, data, and
explicitly authorized bug-bounty targets. No workflows for
credential theft, unauthorized access, persistence, destructive
DoS, data exfiltration, malware, or cross-user exploitation.
Human approval is mandatory before any external disclosure or
submission. Confidential research never enters this public
repository.
