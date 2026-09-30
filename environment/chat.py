"""Chat engine: the primary CYR@ experience.

One user message -> one turn: the coordinator understands the
message, routes to REAL agents/tools (terminal, files, git,
browser, research engines), and composes the reply. With a
provider+model bound the reply is composed by that model
(OpenAI-compatible call, real HTTP); in LOCAL mode the reply is
a deterministic summary of what actually executed - clearly
labeled, never pretending a model wrote it.

Messages persist per task (workspace/chat/<task_id>.json).
Permission denials surface as permission-request cards, not
silent failures."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import urllib.request


class ChatStore:
    """Per-task chat message persistence."""

    def __init__(self, root: Path):
        self.root = Path(root) / "chat"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, task_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", task_id)
        return self.root / f"{safe}.json"

    def messages(self, task_id: str) -> list:
        p = self._path(task_id)
        if not p.exists():
            return []
        try:
            return json.loads(
                p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

    def append(self, task_id: str, message: dict) -> dict:
        msgs = self.messages(task_id)
        message = {"ts": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **message}
        msgs.append(message)
        p = self._path(task_id)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            msgs[-500:], indent=1), encoding="utf-8")
        tmp.replace(p)
        return message


class ChatEngine:
    """The turn pipeline. All tool execution is REAL and goes
    through the central authorization; denials become
    permission-request cards."""

    def __init__(self, env):
        self.env = env
        self.store = ChatStore(env.config.workspace)
        self.orchestrator = env.orchestrator

    # ------------------------------------------------ turn
    def turn(self, task_id: str, text: str,
             model: dict | None = None) -> dict:
        task = self.env.taskstore.get(task_id)
        if task is None:
            return {"error": "unknown task"}
        if model is not None:
            task.data["model"] = model
            self.env.taskstore._persist(task)
        if task.data["state"] in ("completed", "cancelled"):
            try:
                task.transition("running",
                                "reopened by chat")
            except Exception:
                pass
        user_msg = self.store.append(
            task_id, {"role": "user", "content": text})
        activity: list[dict] = []

        # ---- understand + route (deterministic LOCAL intent
        #      detection; the model, when bound, composes the
        #      final reply from the REAL results below)
        intents = self._intents(text)
        results: list[dict] = []
        for intent in intents:
            out = self._execute_intent(
                task_id, intent, text, activity)
            results.append(out)

        # ---- compose the assistant reply
        route = self._resolve_route(task_id, model)
        if route.get("mode") == "remote":
            reply = self._remote_reply(
                task_id, text, results, route)
        else:
            reply = self._local_reply(
                text, results, route)
        assistant_msg = self.store.append(task_id, {
            "role": "assistant",
            "content": reply,
            "mode": route.get("mode", "LOCAL"),
            "model": route.get("model_id"),
            "activity": activity,
            "results": results})
        task.event("chat_turn",
                   "user message handled (%d intents)"
                   % len(intents))
        return {"user": user_msg,
                "assistant": assistant_msg,
                "activity": activity}

    # ------------------------------------------------ routing
    def _intents(self, text: str) -> list[str]:
        t = text.lower()
        intents = []
        url = re.search(
            r"https?://\S+", text)
        if url:
            intents.append("browser")
        if re.search(
            r"\b(run|execute|command|shell|"
            r"powershell|cmd|terminal|"
            r"run tests?|pytest|unittest)\b", t):
            intents.append("terminal")
        if re.search(
            r"\b(git|commit|branch|diff|"
            r"status|push|pull|repo)\b", t):
            intents.append("git")
        if re.search(
            r"\b(fix|edit|write|create|"
            r"patch|modify)\b.*\b(file|"
            r"code|function|bug)?\b", t) or \
                re.search(r"\bwrite\b.*\bto\b", t):
            intents.append("coding")
        if re.search(
            r"\b(research|investigate|hypothes"
            r"is|vulnerab|security|"
            r"target)\b", t):
            intents.append("security")
        if re.search(
            r"\b(analyze|inspect|"
            r"review|structure|"
            r"overview|summar)\w*\b", t):
            intents.append("inspect")
        if not intents:
            intents.append("help")
        return intents[:3]

    def _resolve_route(self, task_id: str,
                       model: dict | None) -> dict:
        task = self.env.taskstore.get(task_id)
        chosen = model or \
            (task.data.get("model") if task else None)
        if chosen and chosen.get("provider") and \
                chosen.get("model_id"):
            route = self.env.providers.resolve_role(
                "coordinator",
                override={"provider":
                          chosen["provider"],
                          "model_id":
                          chosen["model_id"]})
            route["model_id"] = chosen["model_id"]
            return route
        return self.env.providers.resolve_role(
            "coordinator")

    # ------------------------------------------------ tools
    def _execute_intent(self, task_id: str, intent: str,
                        text: str,
                        activity: list) -> dict:
        orch = self.orchestrator
        task = self.env.taskstore.get(task_id)
        if task.data["state"] in ("queued", "planning",
                                  "paused",
                                  "recovering"):
            task.transition("running",
                            "chat turn work")
        try:
            if intent == "terminal":
                # extract the command from the message
                cmd = self._extract_command(text)
                grant = self.env.capabilities.authorize(
                    "terminal.execute", scope=".")
                if not grant["allowed"]:
                    activity.append({
                        "type": "permission_request",
                        "capability": "terminal.execute",
                        "reason": grant["reason"],
                        "command": cmd})
                    return {"intent": intent,
                            "needs_permission":
                                "terminal.execute",
                            "command": cmd}
                run = orch.run_agent(
                    "terminal_agent",
                    {"shell": "python_code",
                     "command": cmd, "workdir": ".",
                     "timeout": 120},
                    parent_task_id=task_id)
                activity.append({
                    "type": "terminal",
                    "command": cmd,
                    "exit_code":
                        (run.get("result") or {}).get(
                            "exit_code"),
                    "output": (((run.get("result") or
                                 {}).get("stdout") or
                                "")[:1200])})
                return {"intent": intent, "run": run}

            if intent == "git":
                grant = self.env.capabilities.authorize(
                    "git.read", scope=".")
                if not grant["allowed"]:
                    activity.append({
                        "type": "permission_request",
                        "capability": "git.read",
                        "reason": grant["reason"]})
                    return {"intent": intent,
                            "needs_permission":
                                "git.read"}
                st = self.env.git.status(".")
                activity.append({
                    "type": "git_status",
                    "branch": st.get("branch"),
                    "changes": st.get("changes", [])[:20]})
                return {"intent": intent,
                        "git": st}

            if intent == "browser":
                url = re.search(
                    r"https?://\S+", text).group(0)
                for cap in ("browser.read",
                            "browser.navigate"):
                    if not self.env.capabilities. \
                            authorize(cap, scope=url)[
                            "allowed"]:
                        activity.append({
                            "type":
                                "permission_request",
                            "capability": cap,
                            "reason":
                                "browser authorization "
                                "required",
                            "url": url})
                        return {"intent": intent,
                                "needs_permission": cap,
                                "url": url}
                run = orch.run_agent(
                    "browser_agent", {"url": url},
                    parent_task_id=task_id)
                res = run.get("result") or {}
                activity.append({
                    "type": "browser",
                    "url": url,
                    "title": res.get("title"),
                    "text_head":
                        (res.get("text_head") or
                         "")[:400]})
                return {"intent": intent, "run": run}

            if intent == "coding":
                m = re.search(
                    r"(?:to|in|file)\s+[`\"]?"
                    r"([\w./\\-]+\.\w+)", text)
                path = m.group(1) if m else ""
                if not path:
                    activity.append({
                        "type": "info",
                        "detail": "no file path detected "
                                  "in the message"})
                    return {"intent": intent,
                            "info": "no path"}
                grant = self.env.capabilities.authorize(
                    "filesystem.read", scope=path)
                if not grant["allowed"]:
                    activity.append({
                        "type":
                            "permission_request",
                        "capability": "filesystem.read",
                        "reason": grant["reason"],
                        "path": path})
                    return {"intent": intent,
                            "needs_permission":
                                "filesystem.read",
                            "path": path}
                existing = self.env.workspace.read(
                    path)
                return {"intent": intent,
                        "path": path,
                        "current": (existing.get(
                            "content") or "")[:2000]}

            if intent == "security":
                m = re.search(
                    r"\b(xnu|webkit|kernel|safari|"
                    r"icloud|face ?id|touch ?id|"
                    r"bluetooth|airdrop|imessage|"
                    r"tcc|sandbox)\w*\b", text.lower())
                target_id = {
                    "xnu": "T-kernel-xnu",
                    "kernel": "T-kernel-xnu",
                    "webkit": "T-safari-webkit",
                    "safari": "T-safari-safari",
                    "icloud": "T-services-icloud",
                    "face id": "T-authentication-"
                               "face-id",
                    "facEid".lower():
                        "T-authentication-face-id",
                    "touch id":
                        "T-authentication-touch-id",
                    "bluetooth":
                        "T-wireless-technologies-"
                        "bluetooth",
                    "airdrop":
                        "T-wireless-technologies-"
                        "airdrop",
                    "imessage":
                        "T-services-imessage",
                    "tcc": "T-userland-tcc",
                    "sandbox": "T-userland-sandbox",
                }.get(m.group(1) if m else "",
                      "T-authentication-face-id")
                if not self.env.capabilities.authorize(
                        "research.execute",
                        scope=target_id)["allowed"]:
                    activity.append({
                        "type":
                            "permission_request",
                        "capability":
                            "research.execute",
                        "reason":
                            "research authorization "
                            "required",
                        "target": target_id})
                    return {"intent": intent,
                            "needs_permission":
                                "research.execute",
                            "target": target_id}
                run = orch.run_agent(
                    "security_researcher",
                    {"target_id": target_id},
                    parent_task_id=task_id)
                res = run.get("result") or {}
                activity.append({
                    "type": "research",
                    "target": target_id,
                    "disposition":
                        res.get("disposition")})
                return {"intent": intent, "run": run}

            if intent == "inspect":
                grant = self.env.capabilities.authorize(
                    "filesystem.read", scope="*")
                if grant["allowed"]:
                    tree = self.env.workspace.tree("")
                    files = [f for f in tree
                             if not f["dir"]]
                    activity.append({
                        "type": "workspace",
                        "files": len(files),
                        "dirs": len(tree) -
                                len(files)})
                    result = {"intent": intent,
                              "files": len(files)}
                else:
                    activity.append({
                        "type":
                            "permission_request",
                        "capability":
                            "filesystem.read",
                        "reason": grant["reason"]})
                    result = {"intent": intent,
                              "needs_permission":
                                  "filesystem.read"}
                git_ok = self.env.capabilities. \
                    authorize("git.read", scope=".")
                if git_ok["allowed"]:
                    st = self.env.git.status(".")
                    result["git_branch"] = \
                        st.get("branch")
                    result["git_changes"] = \
                        len(st.get("changes", []))
                return result

            # help intent
            return {"intent": "help"}
        except Exception as e:
            activity.append({
                "type": "error",
                "detail": repr(e)[:300]})
            return {"intent": intent,
                    "error": repr(e)[:300]}

    def _extract_command(self, text: str) -> str:
        """Best-effort command extraction for the terminal
        intent: fenced code blocks first, then after 'run'."""
        m = re.search(r"```(?:\w+)?\n(.*?)```",
                      text, re.S)
        if m:
            return m.group(1).strip()[:500]
        m = re.search(
            r"(?:run|execute|command)\s*[:`]?\s*(.+)",
            text, re.I)
        if m:
            return m.group(1).strip().strip(
                "`\"'")[:500]
        # fall back to the whole message as code if it
        # looks like code
        if any(c in text for c in ("print(", "=",
                                   "import ")):
            return text[:500]
        return "echo " + text.strip()[:200]

    # ------------------------------------------------ replies
    def _local_reply(self, text: str, results: list,
                     route: dict) -> str:
        lines = []
        needs_perm = [r for r in results if
                      r.get("needs_permission")]
        if needs_perm:
            caps = ", ".join(sorted({r[
                "needs_permission"] for r in
                needs_perm}))
            lines.append(
                "I need your authorization before I "
                "can do this: **%s**. Grant it in the "
                "capability panel (or answer a "
                "permission card) and ask me again."
                % caps)
        for r in results:
            i = r["intent"]
            if i == "terminal" and "run" in r:
                res = r["run"].get("result") or {}
                if res.get("exit_code") == 0:
                    lines.append(
                        "Command ran (exit 0). "
                        "Output is in the terminal "
                        "card.")
                elif "exit_code" in res:
                    lines.append(
                        "Command finished with exit "
                        "code %s." % res["exit_code"])
            elif i == "git" and "git" in r:
                lines.append(
                    "Repository status is in the git "
                    "card (branch %s, %d changes)."
                    % (r["git"].get("branch"),
                       len(r["git"].get("changes",
                                        []))))
            elif i == "browser" and "run" in r:
                res = r["run"].get("result") or {}
                if res.get("title"):
                    lines.append(
                        "Browsed to **%s** - the "
                        "extracted text is in the "
                        "browser card."
                        % res["title"])
            elif i == "coding" and r.get("path"):
                lines.append(
                    "Read **%s** - current content "
                    "is in the file card. Tell me "
                    "the change you want (or paste "
                    "the new content) and I'll "
                    "write it." % r["path"])
            elif i == "security" and "run" in r:
                res = r["run"].get("result") or {}
                lines.append(
                    "Research loop on %s: "
                    "**%s** (negative controls + "
                    "reproduction gates applied)."
                    % (res.get("hypothesis_id",
                               "?"),
                       res.get("disposition", "?")))
            elif i == "inspect":
                bits = []
                if "files" in r:
                    bits.append("%d files in the "
                                "workspace" %
                                r["files"])
                if r.get("git_branch"):
                    bits.append(
                        "git branch %s (%d changes)"
                        % (r["git_branch"],
                           r.get("git_changes",
                                 0)))
                if bits:
                    lines.append(
                        "Inspected: " + "; ".join(
                            bits) + ".")
            elif i == "help":
                lines.append(
                    "I'm running in LOCAL mode (no "
                    "model provider configured - "
                    "add one in Settings to get "
                    "model-composed replies). I can "
                    "still work for real: run "
                    "commands, read/write files, "
                    "git status/diff, browse and "
                    "extract pages, and run the "
                    "VERITAS research loop on "
                    "Apple targets. Try: `run "
                    "print('hi')`, `show git "
                    "status`, `analyze this repo`, "
                    "or `research the WebKit "
                    "target`.")
        if not lines:
            lines.append(
                "Nothing executed for this "
                "message. LOCAL mode: ask me to "
                "run, inspect, fix, git, browse, "
                "or research something.")
        lines.append("_[LOCAL mode - deterministic "
                     "reply from real execution "
                     "results]_")
        return "\n\n".join(lines)

    def _remote_reply(self, task_id: str, text: str,
                      results: list,
                      route: dict) -> str:
        """Real OpenAI-compatible call with the tool results
        as context."""
        provider = self.env.providers.config[
            "providers"][route["provider"]]
        key = self.env.providers.get_api_key(
            route["provider"])
        if not key:
            return (self._local_reply(
                text, results,
                {"mode": "LOCAL"}) +
                "\n\n[provider key missing - "
                "LOCAL reply]")
        context = json.dumps(
            [{"intent": r["intent"],
              **{k: v for k, v in r.items()
                 if k in ("command", "path",
                          "current", "git_branch",
                          "git_changes", "files",
                          "url", "error",
                          "needs_permission")}}
             for r in results],
            indent=1)[:6000]
        activity_summary = json.dumps(
            [r["result"] if isinstance(
                r.get("result"), dict) else {}
             for r in results])[:6000]
        body = json.dumps({
            "model": route["model_id"],
            "messages": [
                {"role": "system",
                 "content":
                     "You are CYR@, a local "
                     "desktop agent. You execute "
                     "real tools (terminal, files, "
                     "git, browser, security "
                     "research) and summarize "
                     "the ACTUAL results below "
                     "for the user. Never invent "
                     "tool output. If a "
                     "permission was missing, "
                     "say what needs granting."},
                {"role": "user",
                 "content": text + "\n\n[TOOL "
                            "RESULTS]\n" +
                            context + "\n" +
                            activity_summary},
            ],
        }).encode()
        req = urllib.request.Request(
            provider["base_url"] +
            "/chat/completions", data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key})
        try:
            with urllib.request.urlopen(
                    req,
                    timeout=route.get("timeout",
                                      120)) as r:
                resp = json.loads(r.read().decode())
            return resp["choices"][0][
                "message"]["content"]
        except Exception as e:
            return (self._local_reply(
                text, results,
                {"mode": "LOCAL"}) +
                "\n\n[provider call failed (%r) - "
                "LOCAL reply]" % e)
