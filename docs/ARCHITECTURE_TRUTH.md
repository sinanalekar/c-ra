# CYR@ — Architecture Truth Report

Audit date: 2026-09-30. Every statement below was traced
through the actual source and/or executed; nothing is inferred
from filenames.

## DESKTOP RUNTIME (traced)

- **What launches first**: the OS starts `cyr.exe` (Tauri 2
  shell, Rust, `src-tauri/src/main.rs`). `spawn_sidecar()`
  locates `veritas-backend-*.exe` next to the main exe and
  spawns it with `VERITAS_ENV_ROOT` set, then opens the
  window.
- **Who owns the UI**: the Tauri WebView (Windows: WebView2)
  serving the compiled React bundle from `ui/dist`. The
  frontend contains NO business logic - every action is a
  fetch to the backend.
- **Who owns the backend**: the PyInstaller one-file sidecar
  (`tools/backend_entry.py` → `environment.server.main`) —
  FastAPI on **127.0.0.1:8765 only**. CORS allows exactly the
  Tauri origins (`tauri://localhost`, `http://tauri.localhost`)
  and the dev ports.
- **UI ↔ backend**: plain HTTP + JSON over loopback. The
  preflight fix (v1.2.1) is why this works at all in the
  packaged app.
- **Backend crashes**: NOT handled by the shell today - if the
  sidecar dies, the UI shows "backend offline" and keeps
  retrying (`poll()` every 2 s), but the shell does not
  respawn it. **Known gap → fixed in this rebuild: the Rust
  shell now restarts the sidecar if it exits unexpectedly.**
- **Startup**: UI shell renders immediately (staged); the
  splash polls `/api/health`; provider discovery runs in a
  background thread so the API is never blocked behind catalog
  fetches.

## AGENT RUNTIME (traced)

- Agents execute **in-process** in the backend
  (`environment/orchestrator.py:_execute_agent`), dispatched by
  `run_agent(kind, task, parent_task_id, model_override)`.
- Runs are synchronous within a request, wrapped in
  checkpointed steps (`AgentRun.checkpoint()` consults a control
  flag between steps).
- **Cancellation**: `agent_run_stop` sets the flag AND kills
  the terminal session of a terminal_agent (real process kill,
  tested). For fast agents the flag is consulted between steps
  - a sub-second agent may complete before a stop lands (the
  UI reports the actual resulting state, never a fake one).
- **Pause/resume**: step-granular for agents; task-granular
  pause/resume transitions are durable (`tasks.py`, validated
  state machine, persisted before reporting).
- **Redirect**: task-level redirect persists a new objective;
  run-level redirect rewrites a not-yet-finished run's task.
- **Checkpoints**: every task transition, event, checkpoint,
  and delegated-agent completion is written to
  `workspace/tasks/<id>.json` via atomic rename BEFORE being
  reported.
- **Recovery**: on boot, tasks persisted in a live state are
  marked `recovering` with their last checkpoint named; the
  recovery agent resumes them (verified with a hard-kill
  restart during the acceptance run).

## TOOL RUNTIME TRUTH (executed, not assumed)

| Tool | Status | Evidence |
|---|---|---|
| filesystem | **IMPLEMENTED** (workspace-scoped; traversal-proof, tested) | write/read/search/tree verified live |
| terminal | **IMPLEMENTED** (real Popen; streaming, stop, timeout, destructive-shape gate) | real process runs + kill verified |
| git | **IMPLEMENTED** (status/diff/log/branches/add/commit/checkout/restore/stash/merge/fetch/pull/push; push=grant+confirm; dirty-tree refusal) | commit flow + gates tested |
| browser | **IMPLEMENTED with a boundary** — Playwright/Chromium real (navigate/extract/click/type/press/scroll/screenshot/download/upload verified against a live loopback page); **packaged app lacks chromium** → honest http-fetch fallback, interaction disabled | live tests + capability_status |
| computer/app control | **PARTIAL** — authorized app launch + process listing are real; keyboard/mouse/screenshot/window-focus are NOT implemented and are reported unavailable | capability_status output above |
| model runtime | **IMPLEMENTED** — OpenAI-compatible providers, OS-vault keys (keyring/WinVault), live /models catalogs, per-task model binding, remote replies verified through NVIDIA NIM | live remote chat verified |
| memory | **IMPLEMENTED** (session/task/project/persistent/research; redaction; bounded recall) | tests |
| artifacts | **IMPLEMENTED** (content-hashed, tamper detection) | integrity test |
| evidence | **IMPLEMENTED** (monotonic states, hashes, confidence) | state machine tests |
| long-running tasks | **IMPLEMENTED** (10-state durable machine + recovery) | restart-recovery verified |

## RESEARCH ARCHITECTURE (traced)

- CYR@ orchestrator → engine adapters
  (`environment/engines/*`) — all five registered, each with
  an honest `available()` probe.
- **VERITAS**: in-process import of the sibling repository
  (read-only); the blind-spot closure experiment and the
  journal-head provenance export are real calls. VERITAS's own
  research state is NOT copied into CYR@ — it stays in its
  repository (41 hypotheses, 26 validated findings, journal
  chain VALID verified this session).
- **CIDER**: real in-process execution of its builtin
  experiments inside CYR@'s workspace (read-only repo import);
  outcome harvesting from RESULT.json / evidence JSONs /
  REPORT.md; vertical slice verified end-to-end.
- **Frontier / HYDRA**: capability-probe adapters; deep
  method campaigns and firmware scans require explicit params
  (HYDRA additionally requires an artifact; without it the
  adapter returns BLOCKED — honest).
- **SEEK**: journal-bridge adapter; live network research is
  capability-gated (network.request) and returns BLOCKED
  without it — honest.
- Gates: SUPPORTED requires negative controls + independent
  reproduction; otherwise INCONCLUSIVE. Verified by tests that
  missing gates refuse SUPPORTED.

## SETTINGS (traced)

- Providers/roles: UI → `/api/providers*` →
  `providers.json` + OS vault → consumed by
  `resolve_role()` on every chat turn and agent run. Real.
- Capability grants: UI → `/api/permissions/grant` →
  grants.json ledger → consumed by every tool runtime. Real.
- Removed in this rebuild: nothing had a dead consumer, but
  the role-binding pickers previously wrote bindings that
  nothing displayed contextually — the new Settings shows
  each role's live route on every screen that uses a model.

## NO-MOCK SWEEP

`grep -n "TODO|FIXME|mock|stub|fake|placeholder"` across
production modules returns only `reports.py`'s deliberate
self-hash placeholder string (not a mock). No random progress,
no fake streaming, no hardcoded statuses on execution paths.

## BROKEN / WEAK POINTS FOUND (honest)

1. Sidecar crash → shell did not restart it (fixed this
   rebuild, Rust supervisor loop).
2. Packaged app cannot use interactive browser automation
   (chromium not bundled) — falls back honestly; documented.
3. Computer-use beyond app-launch/process-list is genuinely
   unimplemented — reported as such everywhere.
4. Task-state granularity: the chat pipeline transitions a
   task to `running` on delegation; the richer
   CREATED→PLANNING→…machine from the master prompt is
   implemented in the rebuild as phases on the same durable
   store.
5. UI polled the journal; the rebuild moves the activity
   stream to SSE (`/api/events`) with polling only as a
   fallback.

## VERITAS RESEARCH STATE (verified intact)

The sibling VERITAS repository is untouched by CYR@ (read-only
import). Verified this session: journal chain VALID, Brier
~0.0035, 41 hypotheses (40 SUPPORTED, 1 REFUTED), 26
VALIDATED findings, waves 1–5 including H-0038..H-0041
(evidence-matrix, exhaustion, differential attribution, scan
saturation) all present and green.
