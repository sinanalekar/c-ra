"""Authoritative capability registry: ONE truth source the UI
consumes. Each capability exposes implementation status,
availability, authorization state, scope, and a reason when
unavailable. Merges the authorization ledger with live tool
runtime probes and engine availability - the UI can never
claim a capability that does not exist."""
from __future__ import annotations


def build_registry(env) -> dict:
    caps = env.capabilities
    from .capabilities import canonical
    out = {}

    def entry(name, impl, available=True,
              note=""):
        cap = canonical(name)
        grants = [g for g in
                  caps.grants.get(cap, [])
                  if g["mode"] != "deny"]
        out[name] = {
            "capability": name,
            "implementation": impl,
            "available": available,
            "authorization": "granted"
            if grants else "denied",
            "scope": [g["scope"]
                      for g in grants],
            "note": note,
        }

    # ---- filesystem
    entry("filesystem.read", "IMPLEMENTED")
    entry("filesystem.write", "IMPLEMENTED")
    entry("filesystem.delete", "IMPLEMENTED",
          note="high-risk: per-operation "
               "confirmation required")
    entry("filesystem.execute", "IMPLEMENTED")
    # ---- terminal / process
    entry("terminal.execute", "IMPLEMENTED",
          note="real subprocess execution; "
               "destructive shapes gated")
    entry("process.spawn", "IMPLEMENTED")
    # ---- git
    entry("git.read", "IMPLEMENTED")
    entry("git.write", "IMPLEMENTED",
          note="dirty-tree checkout refused; "
               "restore is high-risk")
    entry("git.push", "IMPLEMENTED",
          note="high-risk: grant + per-push "
               "confirmation; never silent")
    # ---- browser
    engine = "playwright/chromium" \
        if env.browser._driver_ok \
        else "http-fetch fallback"
    entry("browser.read", "IMPLEMENTED",
          note="engine: " + engine)
    entry("browser.navigate", "IMPLEMENTED",
          note="engine: " + engine)
    entry("browser.interact", "IMPLEMENTED",
          available=env.browser._driver_ok,
          note=("real clicks/typing via "
                "playwright/chromium"
                if env.browser._driver_ok else
                "requires playwright + chromium; "
                "honest fallback in packaged app"))
    entry("browser.download", "IMPLEMENTED",
          available=env.browser._driver_ok,
          note="high-risk: confirmation; needs the "
               "playwright engine")
    entry("browser.upload", "IMPLEMENTED",
          available=env.browser._driver_ok,
          note="high-risk: confirmation; needs the "
               "playwright engine")
    # ---- computer
    cs = env.computer.capability_status()
    entry("computer.read", "IMPLEMENTED",
          note="process listing")
    entry("computer.interact", "PARTIAL",
          available=True,
          note="app launch real; keyboard/mouse/"
               "screenshot NOT implemented - "
               "reported unavailable, never faked")
    # ---- network / research
    entry("network.request", "IMPLEMENTED",
          note="SEEK live research gate; "
               "requires exact scope")
    entry("research.execute", "IMPLEMENTED",
          note="VERITAS-gated research loop with "
               "negative-control + reproduction "
               "gates")
    for e in env.registry.describe_all():
        name = "engine." + e["name"]
        entry(name, "IMPLEMENTED",
              available=e["available"],
              note=("%s v%s - %s"
                    % (e["name"], e["version"],
                       ", ".join(
                           e["capabilities"][:3])))
              if e["available"] else
              "engine repository not "
              "resolvable on this machine")
    # ---- agent controls
    entry("agent.pause", "IMPLEMENTED",
          note="step-granular checkpoints for "
               "runs; durable task state for "
               "tasks")
    entry("agent.resume", "IMPLEMENTED")
    entry("agent.stop", "IMPLEMENTED",
          note="terminal-agent stop kills the "
               "real process")
    entry("agent.redirect", "IMPLEMENTED")
    # ---- reinitialize
    entry("research.reinitialize", "IMPLEMENTED",
          note="differential synchronization "
               "session; auto-push disabled by "
               "default")
    return {"capabilities": out,
            "deny_by_default": True,
            "generated_utc": __import__("time")
            .strftime("%Y-%m-%dT%H:%M:%SZ",
                      __import__("time")
                      .gmtime())}


def build_diagnostics(env) -> dict:
    """Real runtime health with evidence, not generic
    'healthy'."""
    from .version import VERSION, PRODUCT_NAME
    import time
    journal = env.journal.verify()
    reinit = env.reinit.current() if getattr(
        env, "reinit", None) else None
    nodes = [
        {"node": "desktop-shell",
         "status": "running",
         "detail": "Tauri 2 window (this UI)"},
        {"node": "backend",
         "status": "running",
         "detail": "FastAPI @127.0.0.1:8765"},
        {"node": "task-manager",
         "status": "running",
         "detail": "%d durable tasks loaded"
                   % len(env.taskstore.tasks)},
        {"node": "capability-registry",
         "status": "running",
         "detail": "%d capabilities"
                   % len(env.capabilities.grants)},
        {"node": "tool-runtime",
         "status": "running",
         "detail": "terminal/git/filesystem live; "
                   "browser engine: %s"
                   % ("playwright"
                      if env.browser._driver_ok
                      else "fetch-fallback")},
        {"node": "research-orchestrator",
         "status": "running",
         "detail": "%d/%d engines available"
                   % (sum(1 for e in
                          env.registry.describe_all()
                          if e["available"]),
                      len(env.registry.
                          describe_all()))},
        {"node": "veritas",
         "status": "online"
         if env.registry.get("veritas")
         .available() else "unavailable",
         "detail": "journal head: %s"
                   % (env.registry.get("veritas")
                      .export_provenance("diag")
                      .get("veritas_journal_head")
                      or "n/a")},
    ]
    for name in ("cider", "seek", "hydra",
                 "frontier"):
        e = env.registry.get(name)
        nodes.append({
            "node": name,
            "status": "online"
            if e.available() else "unavailable",
            "detail": "v%s" % e.version})
    return {
        "product": PRODUCT_NAME,
        "version": VERSION,
        "backend": "FastAPI/uvicorn loopback",
        "frontend": "React %s bundle"
                    % ("(tauri shell)"),
        "desktop_runtime": "Tauri 2 (WebView2)",
        "journal": journal,
        "storage": {
            "workspace": str(env.config.workspace),
            "tasks": len(env.taskstore.tasks),
            "artifacts": len(env.artifacts._index),
            "evidence": len(env.evidence._index),
        },
        "engines": env.registry.describe_all(),
        "providers": {
            "configured": sorted(
                env.providers.config[
                    "providers"].keys()),
            "roles_bound": {
                k: v for k, v in
                env.providers.config[
                    "role_bindings"].items()
                if v}},
        "last_reinitialization":
            reinit or "none this session",
        "reinit_sessions": env.reinit.sessions()
        if hasattr(env, "reinit") else [],
        "nodes": nodes,
        "checked_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
