# CYR@ Rebuild Report (v1.3.0)

Date: 2026-09-30. Everything below was executed against the
packaged, installed application on the development machine.

## 1-2. Architecture before → after

**Before**: panel-based console (Tasks/Activity/Workspace/
Terminal/Git/Browser/Agents/Research/Artifacts/Reports/
Settings as separate screens), green-heavy visual identity,
capability truth spread across the permission ledger + UI
labels, no ecosystem synchronization, capability metadata
duplicated in UI text.

**After**: a compact navigation rail (Home/Tasks/Research/
Tools/Agents/Memory/Settings/Diagnostics) around a chat-first
Home; **one authoritative capability registry** the UI
consumes (`/api/capabilities`: implementation status +
availability + authorization + honest note per capability);
**diagnostics** rendering the real architecture graph with
statuses; and the **Reinitialize subsystem** — a durable,
evidence-backed synchronization session between CYR@ and its
research ecosystem. Neutral professional palette; green is
semantic only (verified/success). `ARCHITECTURE_TRUTH.md`
documents the audited chain for every subsystem.

## 3. Broken components discovered

- The model-composed chat reply received an empty tool-result
  context (`[{}]`) — the model honestly refused to fabricate
  output while the tool HAD run (found live on the installed
  app; fixed: exit codes/stdout/stderr/dispositions now reach
  the model context, capped and grounded).
- Command extraction swallowed natural-language tails
  ("run X and tell me the output" → SyntaxError → the model
  truthfully reported the failure). Fixed with prose-stripping
  extraction (verified: 'print("x")').
- `ReinitStart` pydantic model was function-local → FastAPI
  bound it as a query param (422s). Hoisted; the lesson is now
  applied to all request models.
- Reinit session completed "COMPLETED" even when an apply
  failed its test gate. Fixed: apply-failure → FAILED with the
  revert recorded.

## 4-6. Removed / rebuilt / newly implemented

- **Removed**: the 11-panel panel-scape; decorative gradients,
  glow, oversized cards; dead role-binding pickers.
- **Rebuilt**: UI (neutral design system, semantic color),
  Settings (Models/Permissions/Appearance tabs populated from
  real state), task list controls.
- **Newly implemented**: `capability_registry.py` (28
  capabilities, authoritative), `reinit.py` (Reinitialize
  subsystem), `/api/capabilities`, `/api/diagnostics`, the
  full `/api/reinitialize/*` surface, `/api/health`, task
  deletion, staged startup (render shell → connect → load →
  background discovery).

## 7-11. Integrations

VERITAS/CIDER/SEEK/HYDRA/Frontier preserved as engines behind
adapters (verified online in diagnostics; VERITAS research
state untouched — its own repo still reports journal VALID,
41 hypotheses, 26 validated findings). Reinitialize checks
all five + CYR@ itself with real `git fetch`/`rev-list`/
`diff` — no copying of research data, ever.

## 12-13. Reinitialize + synchronization model

Session machine CREATED→…→COMPLETED/FAILED with a live
timeline; per-repo: local/remote commits, commits since last
sync, changed files, deterministic classification (NO_CHANGES/
DOCS/TESTS→COMPATIBLE/CONFIDENTIAL/SECURITY_BOUNDARY/
RESEARCH_STATE_SCHEMA/ENGINE_SURFACE/CODE). Verdicts:
UP_TO_DATE, DOCS_ONLY, COMPATIBLE (auto-apply with backup
branch + ff-merge + TEST GATE), REVIEW_REQUIRED,
MIGRATION_REQUIRED, REQUIRES_AUTHORIZATION,
BLOCKED_CONFIDENTIAL, REMOTE_UNAVAILABLE. Sync manifest
persists last_seen_commit per repo. Auto-push disabled by
default (structurally); push is high-risk per-operation.
Session records: session.json, inspection.json,
repository_diffs.json, integration_plan.md, tests.json,
result.md, provenance.json.

## 14-17. Performance / UI / settings / security

Startup: shell renders instantly; /api/health answers as soon
as the process binds (22 s cold start = one-file sidecar
extraction; the splash communicates it). Discovery is a
background thread. UI polls only /api/health + /api/tasks
(2.5 s) — heavy views (diagnostics/capabilities) load on
demand. Settings: three tabs, real state, no placeholders.
Security unchanged: loopback, deny-by-default + first-run
defaults (journaled), OS-vault keys, high-risk confirms.

## 18-19. Tests + Windows verification

- **118 tests green** (12 = the A–J Reinitialize matrix:
  A no-changes ✓, B docs-only ✓, C compatible→applied+tested
  ✓, D breaking→review ✓, E security→authorization ✓, F
  schema→migration ✓, G confidential→blocked (never in plan
  artifacts) ✓, H failed tests→reverted, base branch intact
  ✓, I dirty tree→protected ✓, J remote down→exact failure,
  state preserved ✓).
- **Installed app (Windows 11)**: silent reinstall → backend
  up in 20-22 s → NVIDIA 81 models auto-discovered →
  zero-click chat executed a real command → **model-composed
  reply grounded in the actual tool output** ("final-ok-13",
  exit 0) → Reinitialize COMPLETED (10-event timeline, real
  verdicts incl. REVIEW_REQUIRED for repos with new commits)
  → clean shutdown, no orphan processes.

## 20. Remaining limitations (honest)

- Packaged app lacks bundled Chromium: interactive browser
  automation falls back to http-fetch (reported honestly;
  system playwright enables it).
- Computer-use beyond app-launch/process-list is genuinely
  not implemented; displayed as PARTIAL everywhere.
- Sub-second agents may complete before a stop lands (the
  reported state is the real state).
- First launch takes ~20 s (one-file extraction). Onedir
  packaging would cut this at installer-complexity cost.
- Reinitialize applies automatically only to
  COMPATIBLE/DOCS_ONLY classes on the CYR@ repo; everything
  else requires explicit review — by design.
