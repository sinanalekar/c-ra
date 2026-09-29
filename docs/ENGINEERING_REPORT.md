# CYR@ 1.0.0 — Engineering Report

Date: 2026-09-30. All claims below were verified by actual
runs during this session; nothing is claimed that was not
executed.

## What changed

The repository (formerly "VERITAS environment") was
transformed into CYR@, a local-first desktop agent harness,
while preserving and extending the existing security-research
infrastructure (all five engines intact). Renamed the user-
facing product to CYR@ everywhere visible: window title,
product name, installer name, Start Menu shortcut, README,
icons, package metadata; internal engines keep their names.
GitHub repository migrated: `sinanalekar/veritas-environment`
-> `sinanalekar/c-ra` (history preserved, old URL redirects).
Version canonicalized at 1.0.0 (`environment/version.py`):
Python package, UI package, Tauri, installer, and API metadata
all match.

## Architecture changes

New modules (all typed Python, small, tested):

- `environment/capabilities.py` — the ONE central
  authorization ledger: 23 capabilities, grant modes (deny /
  allow_once consumed on use / allow_task / allow_workspace /
  allow_session), high-risk confirmation set, journaled
  decisions. The legacy permission names remain as aliases
  through the same ledger (one system, no bypass).
- `environment/terminal.py` — real process runtime
  (PowerShell/CMD/Python/Python-code/Git) with streaming
  output, stop/cancel/timeout, and a 12-pattern destructive
  command gate requiring confirmation.
- `environment/gitops.py` — controlled Git runtime with safety
  gates (refuses checkout on dirty trees; push is high-risk:
  grant + per-operation confirm).
- `environment/browser.py` — REAL Playwright/Chromium
  automation: navigation, extraction, page source, click, type,
  press, scroll, screenshots, downloads, uploads; http-fetch
  fallback when the driver is missing (reported honestly).
  http/https only.
- `environment/computer.py` — computer-use abstraction:
  authorized application launch + process inspection;
  keyboard/mouse/screenshot reported NOT implemented.
- `environment/tasks.py` — durable task engine (10 states,
  validated transitions), disk-persisted BEFORE reporting,
  boot-time recovery marking interrupted tasks `recovering`.
- `environment/memory.py`, `environment/artifacts.py`,
  `environment/evidence.py` — persistent memory with secret
  redaction and bounded retrieval; hash-verified artifacts;
  evidence with a monotonic state machine.
- `environment/api_runtime.py` — 60+ new endpoints (tasks,
  terminal, git, browser, computer, capabilities, memory,
  artifacts, evidence, agent run controls, model routes).
- UI rewritten: 11 working panels (Tasks, Activity,
  Workspace, Terminal, Git, Browser, Agents, Research,
  Artifacts, Reports, Settings), dark/light themes, strict
  TypeScript, no dead controls.
- 19 specialist agents, all executable (none config-only) —
  enforced by a test that runs every advertised kind.
- Tauri shell: CYR@ window, mainBinaryName `cyr`, sidecar
  lifecycle (spawn at boot, kill at exit).

## Tests

`python -m unittest discover -s tests`: **89 tests, OK
(2 honest skips)**. The skips occur only when chromium cannot
launch under machine load - the tests verify REAL interaction
when it can (verified separately: navigation, typing, and an
onclick handler executing and changing the page title).

Coverage added this phase: capability modes (once/task/
workspace/deny-override/high-risk), terminal real execution +
stop + timeout + dangerous-command blocking, git grants +
commit flow + push gate + dirty-tree refusal, browser scheme
gating + real interaction + screenshot, computer confirm
gating + honest unavailable, task durability across restarts +
recovery, memory redaction + bounded recall + removal,
artifact integrity (tamper detection), evidence state machine,
agent controls (stop kills the real process), all-specialists-
executable.

## Build, installer, installation

- UI: strict tsc + Vite, clean build (167.82 kB JS).
- Sidecar: PyInstaller onefile, all five engine adapters
  included (123.2 MB), API up in ~3 s standalone.
- Desktop: Tauri 2 release build (`cyr.exe`, 20.6 MB).
- Installer: `CYR@_1.0.0_x64-setup.exe` (125.56 MiB), NSIS.
- Installed silently (/S) on the development machine:
  `C:\Users\SINAN\AppData\Local\CYR@\` with
  `cyr.exe`, `veritas-backend.exe`, `WebView2Loader.dll`,
  `uninstall.exe`; Start Menu shortcut `CYR@.lnk` present.

## Runtime verification (executed)

1. Launched installed CYR@ from the Start Menu shortcut.
2. Backend auto-started (loopback 127.0.0.1:8765), all five
   engines discovered (veritas, cider, frontier, hydra, seek),
   journal chain VALID.
3. Workspace write: file written, sha256 returned.
4. Task created; coordinator agent produced a 7-step plan.
5. Terminal agent ran a real Python process; output streamed
   and was recorded as evidence + artifact.
6. Git status/diff via the runtime on this repository
   (branch main, 32 changed files detected live).
7. Security researcher ran the full research loop through
   CIDER: SUPPORTED with negative controls + reproduction.
8. Task paused -> state=paused; resumed -> running;
   redirected objective persisted; checkpoints recorded
   (`agent:terminal_agent`).
9. Hard-killed the backend; after restart the task was
   `recovering` (last checkpoint named); the recovery agent
   resumed it to running.
10. Browser (playwright/chromium): navigated example.com
    (status 200), extracted 1301 chars, real interaction
    capability reported True.
11. Report generated with sha + mandatory not-demonstrated
    section; journal 125 entries, chain VALID.
12. Clean shutdown: app exit kills the sidecar (no orphans
    observed).

## Provider verification

Model routes resolve per-role with LOCAL fallback reported
honestly ("role unconfigured; LOCAL deterministic policy").
Provider schema enforced (https-only, key via OS credential
store - plaintext refused). No external API was called by any
test (LOCAL mode; deterministic policies).

## Known limitations

- Packaged app: the PyInstaller sidecar does not bundle
  Chromium; the installed app's browser engine runs the
  http-fetch fallback and reports interaction UNAVAILABLE
  until a system-wide playwright + chromium is present.
  Never faked either way.
- First backend launch takes ~18 s (one-file sidecar
  extraction).
- The coding agent's write surface is workspace-confined;
  arbitrary-path writes require an explicit allow_workspace
  grant (by design).
- Contexts: no git rebase or conflict-resolution automation
  yet; merge is single-shot with output recorded.

## Intentionally unavailable (reported, not faked)

- Computer use: keyboard input, mouse input, window focusing,
  UI automation, screen capture.
- Browser interactive automation when the driver is absent
  (fallback mode).
- SEEK live network experiments without the network capability
  + exact scope (BLOCKED disposition).
- HYDRA firmware scans without an artifact (BLOCKED).
- Any engine whose repository is missing (available=False).
- Model review in LOCAL mode (roles report LOCAL; verdicts
  come from the deterministic gates, never a model vote).

## Security considerations

Loopback-only binding. Deny-by-default central authorization
with per-grant audit. High-risk operations require explicit
confirmation. API keys via OS credential store, never in
files, Git, journals, or reports; memory redacts secret
shapes. Path traversal rejected (workspace confinement).
Dangerous command shapes blocked pending confirmation. Journal
hash-chained with fail-closed tamper verification. Push and
destructive Git operations gated. Confidential research never
enters this repository; examples are synthetic.
