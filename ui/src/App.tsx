import React, { useEffect, useRef, useState } from "react";

/* CYR@ - local desktop agent harness.
   Every panel talks to the real backend (127.0.0.1:8765).
   Unavailable capabilities display unavailable. */

const API = "http://127.0.0.1:8765";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json() as Promise<T>;
}

type Theme = "dark" | "light";

const themes = {
  dark: {
    bg: "#0e1218", panel: "#161b24", border: "#2a3140",
    text: "#d8dee9", dim: "#7f8ea3", accent: "#6fd08c",
    warn: "#d8b64a", bad: "#e06c6c", input: "#11151d",
  },
  light: {
    bg: "#f2f4f8", panel: "#ffffff", border: "#d5dae3",
    text: "#1c2330", dim: "#5d6b80", accent: "#157f42",
    warn: "#9a6b00", bad: "#b3261e", input: "#eef1f6",
  },
};

const box = (t: typeof themes.dark): React.CSSProperties => ({
  background: t.panel, border: `1px solid ${t.border}`,
  borderRadius: 8, padding: 12,
});

const btn = (t: typeof themes.dark): React.CSSProperties => ({
  background: t.input, color: t.text,
  border: `1px solid ${t.border}`, borderRadius: 6,
  padding: "4px 10px", cursor: "pointer", fontSize: 12,
});

const input = (t: typeof themes.dark): React.CSSProperties => ({
  background: t.input, color: t.text,
  border: `1px solid ${t.border}`, borderRadius: 6,
  padding: "4px 8px", fontSize: 12, width: "100%",
  boxSizing: "border-box" as const,
});

const label = (t: typeof themes.dark): React.CSSProperties => ({
  color: t.dim, fontSize: 10, textTransform: "uppercase",
  letterSpacing: 1, margin: "8px 0 4px",
});

type JournalEntry = { ts: string; action: string; [k: string]: unknown };
type TaskRec = { task_id: string; objective: string; state: string; events?: unknown[] };
type AgentRun = { run_id: string; agent: string; state: string; steps: number; task_id?: string };
type TermRec = { session_id: string; command: string; state: string; stdout?: string; stderr?: string; exit_code?: number | null };
type ArtifactRec = { artifact_id: string; type: string; sha256: string; created_utc: string };

function dispositionColor(t: typeof themes.dark, s: string): string {
  if (["SUPPORTED", "VALIDATED", "REPRODUCED", "completed", "DONE",
       "running", "ok", "true"].includes(s)) return t.accent;
  if (["BLOCKED", "REFUTED", "FAILED", "cancelled", "STOPPED",
       "paused"].includes(s)) return t.bad;
  return t.warn;
}

/* ------------------------------------------------ panels */

function TasksPanel({ t, refresh, say }: { t: typeof themes.dark; refresh: () => void; say: (m: string) => void }) {
  const [tasks, setTasks] = useState<TaskRec[]>([]);
  const [objective, setObjective] = useState("");
  const [agentKind, setAgentKind] = useState("coordinator");
  const [agentTask, setAgentTask] = useState("{}");
  const [selected, setSelected] = useState<TaskRec | null>(null);

  const load = async () => {
    setTasks(await api<TaskRec[]>("/api/tasks"));
    if (selected) {
      const fresh = await api<TaskRec>(`/api/tasks/${selected.task_id}`);
      setSelected(fresh);
    }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line

  const control = async (id: string, op: string) => {
    say(`task ${id}: ${op}`);
    await api(`/api/tasks/${id}/${op}`, { method: "POST", body: "{}" });
    load(); refresh();
  };

  const create = async () => {
    if (!objective.trim()) return;
    say("creating task ...");
    const rec = await api<TaskRec>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ objective }),
    });
    say(`task ${rec.task_id} created`);
    setObjective(""); load(); refresh();
  };

  const runAgentOnTask = async (taskId: string) => {
    let task: Record<string, unknown>;
    try { task = JSON.parse(agentTask || "{}"); }
    catch { say("agent task JSON invalid"); return; }
    say(`${agentKind} -> ${taskId}`);
    try {
      const out = await api<{ run_id: string; state: string }>(
        `/api/tasks/${taskId}/agents`, {
          method: "POST",
          body: JSON.stringify({ kind: agentKind, task }),
        });
      say(`run ${out.run_id}: ${out.state}`);
    } catch (e) { say(`agent error: ${String(e)}`); }
    load(); refresh();
  };

  return (
    <div>
      <div style={{ ...box(t), display: "flex", gap: 8 }}>
        <input style={input(t)} placeholder="new task objective ..."
          value={objective}
          onChange={(e) => setObjective(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && create()} />
        <button style={btn(t)} onClick={create}>create</button>
      </div>
      {tasks.length === 0 ? <div style={{ ...label(t), textAlign: "center" }}>no tasks yet</div> : null}
      {tasks.slice(-12).reverse().map((task) => (
        <div key={task.task_id} style={{ ...box(t), marginTop: 8 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <b style={{ fontSize: 12 }}>{task.task_id}</b>
            <span style={{ color: dispositionColor(t, task.state), fontSize: 12 }}>{task.state}</span>
            <span style={{ color: t.dim, fontSize: 12, flex: 1 }}>{task.objective}</span>
            <button style={btn(t)} onClick={() => setSelected(task)}>open</button>
            <button style={btn(t)} onClick={() => control(task.task_id, "pause")}>pause</button>
            <button style={btn(t)} onClick={() => control(task.task_id, "resume")}>resume</button>
            <button style={btn(t)} onClick={() => control(task.task_id, "stop")}>stop</button>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <select style={{ ...btn(t), flex: 1 }} value={agentKind}
              onChange={(e) => setAgentKind(e.target.value)}>
              {["coordinator", "planner", "researcher", "coding_agent",
                "terminal_agent", "browser_agent", "security_researcher",
                "hypothesis_generator", "experiment_designer",
                "hypothesis_challenger", "evidence_reviewer",
                "reproduction_agent", "report_writer", "recovery_agent",
                "artifact_analyst", "firmware_analyst",
                "network_researcher", "fuzzing_researcher",
                "method_researcher"].map((k) => (
                <option key={k} value={k}>{k}</option>))}
            </select>
            <input style={{ ...input(t), flex: 2 }} value={agentTask}
              placeholder='agent task JSON, e.g. {"shell":"python_code","command":"print(1)"}'
              onChange={(e) => setAgentTask(e.target.value)} />
            <button style={btn(t)} onClick={() => runAgentOnTask(task.task_id)}>run agent</button>
          </div>
        </div>
      ))}
      {selected ? (
        <div style={{ ...box(t), marginTop: 8 }}>
          <div style={{ ...label(t) }}>
            {selected.task_id} events (newest last)
          </div>
          <div style={{ fontSize: 11, maxHeight: 220, overflow: "auto" }}>
            {(selected.events ?? []).slice(-40).map((ev: any, i: number) => (
              <div key={i}>{ev.ts} - {ev.kind} - {String(ev.detail).slice(0, 100)}</div>
            ))}
          </div>
          <button style={{ ...btn(t), marginTop: 8 }}
            onClick={async () => {
              const rec = await api(`/api/tasks/${selected.task_id}/checkpoints`);
              say(`checkpoints: ${JSON.stringify(rec).slice(0, 300)}`);
            }}>checkpoints</button>
        </div>
      ) : null}
    </div>
  );
}

function ActivityPanel({ t, entries }: { t: typeof themes.dark; entries: JournalEntry[] }) {
  return (
    <div style={box(t)}>
      <div style={label(t)}>live activity (journal, newest first)</div>
      <div style={{ fontSize: 11, maxHeight: 500, overflow: "auto" }}>
        {entries.map((e, i) => (
          <div key={i} style={{ display: "flex", gap: 8 }}>
            <span style={{ color: t.dim }}>{e.ts.slice(11, 19)}</span>
            <span>{e.action}</span>
            {"capability" in e ? <span style={{ color: t.dim }}>{String(e.capability)}</span> : null}
            {"session_id" in e ? <span style={{ color: t.dim }}>{String(e.session_id)}</span> : null}
            {"run_id" in e ? <span style={{ color: t.dim }}>{String(e.run_id)}</span> : null}
            {"state" in e ? <span style={{ color: dispositionColor(t, String(e.state)) }}>{String(e.state)}</span> : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function WorkspacePanel({ t, say }: { t: typeof themes.dark; say: (m: string) => void }) {
  const [tree, setTree] = useState<any[]>([]);
  const [path, setPath] = useState("");
  const [content, setContent] = useState("");

  const loadTree = async (p = "") => {
    await api("/api/workspace/write", {
      method: "POST", body: JSON.stringify({ path: ".keep", content: "" }),
    }).catch(() => { }); // first grant may be needed
    const rows = await api<any[]>("/api/workspace/tree", {
      method: "POST", body: JSON.stringify({ path: p }),
    });
    setTree(rows);
  };

  useEffect(() => { loadTree(); }, []); // eslint-disable-line

  const grantAndLoad = async () => {
    say("requesting workspace authorization (session) ...");
    await api("/api/permissions/grant", {
      method: "POST",
      body: JSON.stringify({ capability: "filesystem.read", mode: "allow_session" }),
    });
    await api("/api/permissions/grant", {
      method: "POST",
      body: JSON.stringify({ capability: "filesystem.write", mode: "allow_session" }),
    });
    say("workspace authorized for this session");
    loadTree();
  };

  return (
    <div>
      <div style={{ ...box(t) }}>
        <button style={btn(t)} onClick={grantAndLoad}>authorize workspace (session)</button>
        <div style={{ ...label(t) }}>workspace files</div>
        <div style={{ fontSize: 11, maxHeight: 260, overflow: "auto" }}>
          {tree.map((f: any, i: number) => (
            <div key={i} style={{ display: "flex", gap: 8 }}>
              <span>{f.dir ? "[d]" : "   "}</span>
              <span style={{ cursor: "pointer" }}
                onClick={() => !f.dir && setPath(f.path)}>{f.path}</span>
            </div>
          ))}
        </div>
      </div>
      <div style={{ ...box(t), marginTop: 8 }}>
        <div style={label(t)}>read / write</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={input(t)} value={path} placeholder="workspace-relative path"
            onChange={(e) => setPath(e.target.value)} />
          <button style={btn(t)} onClick={async () => {
            try {
              const rec = await api<any>("/api/workspace/read", {
                method: "POST", body: JSON.stringify({ path }),
              });
              setContent(rec.content ?? JSON.stringify(rec));
            } catch (e) { say(String(e)); }
          }}>read</button>
          <button style={btn(t)} onClick={async () => {
            try {
              const rec = await api<any>("/api/workspace/write", {
                method: "POST", body: JSON.stringify({ path, content }),
              });
              say(`written ${path} sha=${rec.sha256}`);
            } catch (e) { say(String(e)); }
          }}>write</button>
        </div>
        <textarea style={{ ...input(t), marginTop: 8, minHeight: 120, fontFamily: "monospace" }}
          value={content} onChange={(e) => setContent(e.target.value)} />
      </div>
    </div>
  );
}

function TerminalPanel({ t, say }: { t: typeof themes.dark; say: (m: string) => void }) {
  const [shell, setShell] = useState("powershell");
  const [command, setCommand] = useState("");
  const [workdir, setWorkdir] = useState(".");
  const [history, setHistory] = useState<string[]>([]);
  const [active, setActive] = useState<TermRec | null>(null);
  const [out, setOut] = useState("");
  const [sessions, setSessions] = useState<TermRec[]>([]);
  const pollRef = useRef<number | null>(null);

  const refresh = async () => {
    setSessions(await api<TermRec[]>("/api/terminal"));
  };
  useEffect(() => { refresh(); return () => { if (pollRef.current) clearInterval(pollRef.current); }; }, []); // eslint-disable-line

  const run = async (confirm = false) => {
    if (!command.trim()) return;
    setHistory((h) => [...h, `$ ${command}`]);
    try {
      const rec = await api<TermRec>("/api/terminal", {
        method: "POST",
        body: JSON.stringify({ shell, command, workdir, timeout: 120, confirm_dangerous: confirm }),
      });
      if ((rec as any).blocked) {
        setHistory((h) => [...h, "BLOCKED: " + (rec as any).reason + " - confirm to execute"]);
        setActive(rec as TermRec);
        return;
      }
      setActive(rec);
      poll(rec.session_id);
    } catch (e) {
      setHistory((h) => [...h, `error: ${String(e)}`]);
      say(`terminal error: ${String(e).slice(0, 120)}`);
    }
  };

  const poll = (sid: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = window.setInterval(async () => {
      try {
        const rec = await api<TermRec>(`/api/terminal/${sid}`);
        setActive(rec);
        setOut((rec.stdout ?? "") + (rec.stderr ? `\n[stderr] ${rec.stderr}` : ""));
        if (rec.state !== "running") {
          if (pollRef.current) clearInterval(pollRef.current);
          setHistory((h) => [...h, `exit ${rec.exit_code}`]);
          refresh();
        }
      } catch { if (pollRef.current) clearInterval(pollRef.current); }
    }, 500);
  };

  return (
    <div>
      <div style={{ ...box(t), display: "flex", gap: 8 }}>
        <select style={btn(t)} value={shell} onChange={(e) => setShell(e.target.value)}>
          {["powershell", "cmd", "python", "python_code", "git"].map((s) => (
            <option key={s} value={s}>{s}</option>))}
        </select>
        <input style={{ ...input(t), flex: 2 }} value={workdir}
          onChange={(e) => setWorkdir(e.target.value)} />
        <input style={{ ...input(t), flex: 4 }} value={command}
          placeholder="command (streamed live)"
          onChange={(e) => setCommand(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()} />
        <button style={btn(t)} onClick={() => run()}>run</button>
        <button style={btn(t)} onClick={async () => {
          if (active?.session_id) {
            await api(`/api/terminal/${active.session_id}/stop`, { method: "POST", body: "{}" });
            say(`stopped ${active.session_id}`);
          }
        }}>stop</button>
        <button style={btn(t)} onClick={() => { setOut(""); setHistory([]); }}>clear</button>
      </div>
      <div style={{ ...box(t), marginTop: 8 }}>
        <div style={label(t)}>output (live)</div>
        <pre style={{ fontSize: 11, margin: 0, maxHeight: 240, overflow: "auto",
                      whiteSpace: "pre-wrap", color: t.text }}>{out}</pre>
      </div>
      <div style={{ ...box(t), marginTop: 8 }}>
        <div style={label(t)}>history</div>
        <div style={{ fontSize: 11, maxHeight: 160, overflow: "auto" }}>
          {history.map((h: string, i: number) => <div key={i}>{h}</div>)}
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
          <span style={{ fontSize: 11, color: t.dim }}>
            {active ? `${active.session_id}: ${active.state}${active.exit_code != null ? ` (exit ${active.exit_code})` : ""}` : "no active session"}
          </span>
          <button style={{ ...btn(t), marginLeft: "auto" }} onClick={() => navigator.clipboard?.writeText(out)}>copy output</button>
        </div>
      </div>
    </div>
  );
}

function GitPanel({ t, say }: { t: typeof themes.dark; say: (m: string) => void }) {
  const [repo, setRepo] = useState("");
  const [granted, setGranted] = useState(false);
  const [status, setStatus] = useState<any>(null);
  const [diff, setDiff] = useState("");
  const [log, setLog] = useState<string[]>([]);

  const grant = async () => {
    await api("/api/permissions/grant", {
      method: "POST", body: JSON.stringify({ capability: "git.read", mode: "allow_session" }),
    });
    await api("/api/permissions/grant", {
      method: "POST", body: JSON.stringify({ capability: "git.write", mode: "allow_session" }),
    });
    setGranted(true);
    say("git.read + git.write authorized (session)");
  };

  const op = async (name: string, extra: Record<string, unknown> = {}) => {
    try {
      const rec = await api<any>(`/api/git/${name}`, {
        method: "POST", body: JSON.stringify({ repo, ...extra }),
      });
      if (name === "status") setStatus(rec);
      if (name === "diff") setDiff(rec.diff ?? "");
      if (name === "log") setLog(rec.commits ?? []);
      say(`git ${name} ok`);
    } catch (e) { say(`git ${name}: ${String(e).slice(0, 140)}`); }
  };

  return (
    <div>
      <div style={{ ...box(t), display: "flex", gap: 8 }}>
        <input style={{ ...input(t), flex: 4 }} value={repo}
          placeholder="local repository path"
          onChange={(e) => setRepo(e.target.value)} />
        <button style={btn(t)} onClick={grant}>authorize git</button>
        <button style={btn(t)} onClick={() => op("discover")}>discover</button>
        <button style={btn(t)} onClick={() => op("status")}>status</button>
        <button style={btn(t)} onClick={() => op("diff")}>diff</button>
        <button style={btn(t)} onClick={() => op("log")}>log</button>
      </div>
      {status ? (
        <div style={{ ...box(t), marginTop: 8 }}>
          <div style={label(t)}>status</div>
          <div style={{ fontSize: 12, color: dispositionColor(t, status.branch ? "running" : "warn") }}>
            branch: {status.branch ?? "?"}
          </div>
          {(status.changes ?? []).map((c: any, i: number) => (
            <div key={i} style={{ fontSize: 11 }}>
              {c.index}{c.worktree} {c.path}</div>
          ))}
        </div>
      ) : null}
      <div style={{ ...box(t), marginTop: 8 }}>
        <div style={label(t)}>diff</div>
        <pre style={{ fontSize: 11, margin: 0, maxHeight: 200, overflow: "auto",
                      whiteSpace: "pre-wrap" }}>{diff || "(run diff)"}</pre>
      </div>
      <div style={{ ...box(t), marginTop: 8 }}>
        <div style={label(t)}>log</div>
        {log.map((c: string, i: number) => <div key={i} style={{ fontSize: 11 }}>{c}</div>)}
      </div>
    </div>
  );
}

function BrowserPanel({ t, say }: { t: typeof themes.dark; say: (m: string) => void }) {
  const [sid, setSid] = useState("");
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [status, setStatus] = useState<any>(null);
  const [sel, setSel] = useState("");

  const open = async () => {
    await api("/api/permissions/grant", {
      method: "POST", body: JSON.stringify({ capability: "browser.read", mode: "allow_session" }),
    });
    await api("/api/permissions/grant", {
      method: "POST", body: JSON.stringify({ capability: "browser.navigate", mode: "allow_session" }),
    });
    const sess = await api<{ session_id: string }>("/api/browser/sessions", {
      method: "POST", body: "{}",
    });
    setSid(sess.session_id);
    const st = await api<any>("/api/browser/status");
    setStatus(st);
    say(`browser session ${sess.session_id} (engine: ${st.engine})`);
  };

  const navigate = async () => {
    if (!sid || !url) return;
    try {
      const rec = await api<any>(`/api/browser/sessions/${sid}/navigate`, {
        method: "POST", body: JSON.stringify({ url }),
      });
      setTitle(rec.title ?? "");
      say(`navigated: ${rec.title} (${rec.status})`);
    } catch (e) { say(`navigate: ${String(e).slice(0, 140)}`); }
  };

  const extract = async () => {
    if (!sid) return;
    try {
      const rec = await api<any>(`/api/browser/sessions/${sid}/extract`, {
        method: "POST", body: "{}",
      });
      setText(rec.text ?? "");
      say(`extracted ${rec.text?.length ?? 0} chars, ${rec.links?.length ?? 0} links`);
    } catch (e) { say(`extract: ${String(e).slice(0, 140)}`); }
  };

  return (
    <div>
      <div style={{ ...box(t), display: "flex", gap: 8 }}>
        <button style={btn(t)} onClick={open}>open session</button>
        <input style={{ ...input(t), flex: 4 }} value={url} placeholder="https:// ..."
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && navigate()} />
        <button style={btn(t)} onClick={navigate}>navigate</button>
        <button style={btn(t)} onClick={extract}>extract</button>
        <input style={{ ...input(t), width: 140 }} value={sel} placeholder="#selector"
          onChange={(e) => setSel(e.target.value)} />
        <button style={btn(t)} onClick={async () => {
          if (!sid || !sel) return;
          try {
            const rec = await api<any>(`/api/browser/sessions/${sid}/actions`, {
              method: "POST",
              body: JSON.stringify({ action: "click", selector: sel, confirm: true }),
            });
            say(`click: ${JSON.stringify(rec).slice(0, 120)}`);
          } catch (e) { say(`click: ${String(e).slice(0, 140)}`); }
        }}>click</button>
      </div>
      <div style={{ ...box(t), marginTop: 8, fontSize: 11 }}>
        {status ? (
          <div style={{ color: t.dim }}>
            engine: {status.engine} | interaction: {String(status.interaction)} |
            screenshots: {String(status.screenshots)} - {status.note}
          </div>
        ) : "open a session to see honest capability status"}
      </div>
      <div style={{ ...box(t), marginTop: 8 }}>
        <div style={label(t)}>{title || "page text"}</div>
        <div style={{ fontSize: 11, maxHeight: 260, overflow: "auto", whiteSpace: "pre-wrap" }}>
          {text.slice(0, 5000) || "(navigate + extract)"}
        </div>
      </div>
    </div>
  );
}

function AgentsPanel({ t, say }: { t: typeof themes.dark; say: (m: string) => void }) {
  const [specs, setSpecs] = useState<any[]>([]);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [kind, setKind] = useState("coordinator");
  const [task, setTask] = useState("{}");

  const load = async () => {
    setSpecs(await api<any[]>("/api/agents/specs"));
    setRuns(await api<AgentRun[]>("/api/agents"));
  };
  useEffect(() => { load(); }, []); // eslint-disable-line

  const control = async (runId: string, op: string) => {
    try {
      const rec = await api(`/api/agents/${runId}/${op}`, {
        method: "POST",
        body: op === "redirect" ? JSON.stringify({ task: { objective: "redirected" } }) : "{}",
      });
      say(`run ${runId} ${op}: ${JSON.stringify(rec).slice(0, 120)}`);
    } catch (e) { say(String(e)); }
    load();
  };

  return (
    <div>
      <div style={{ ...box(t), display: "flex", gap: 8 }}>
        <select style={{ ...btn(t), flex: 1 }} value={kind} onChange={(e) => setKind(e.target.value)}>
          {specs.map((s: any) => <option key={s.kind} value={s.kind}>{s.kind}</option>)}
        </select>
        <input style={{ ...input(t), flex: 3 }} value={task}
          onChange={(e) => setTask(e.target.value)}
          placeholder="agent task JSON" />
        <button style={btn(t)} onClick={async () => {
          try {
            const out = await api<any>("/api/agents/run", {
              method: "POST",
              body: JSON.stringify({ kind, task: JSON.parse(task || "{}") }),
            });
            say(`run ${out.run_id}: ${out.state}`);
          } catch (e) { say(String(e)); }
          load();
        }}>run</button>
      </div>
      <div style={{ ...box(t), marginTop: 8 }}>
        <div style={label(t)}>agent runs (pause/resume/stop affect real executions)</div>
        {runs.slice(-15).reverse().map((r: AgentRun) => (
          <div key={r.run_id} style={{ display: "flex", gap: 8, fontSize: 11, alignItems: "center" }}>
            <span style={{ color: t.dim }}>{r.run_id}</span>
            <span>{r.agent}</span>
            <span style={{ color: dispositionColor(t, r.state) }}>{r.state}</span>
            <span style={{ color: t.dim }}>{r.steps} steps</span>
            <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
              <button style={btn(t)} onClick={() => control(r.run_id, "pause")}>pause</button>
              <button style={btn(t)} onClick={() => control(r.run_id, "resume")}>resume</button>
              <button style={btn(t)} onClick={() => control(r.run_id, "stop")}>stop</button>
              <button style={btn(t)} onClick={async () => {
                const rec = await api(`/api/agents/${r.run_id}/checkpoints`);
                say(`checkpoints ${r.run_id}: ${JSON.stringify(rec).slice(0, 200)}`);
              }}>cp</button>
            </span>
          </div>
        ))}
      </div>
      <div style={{ ...box(t), marginTop: 8 }}>
        <div style={label(t)}>specialists</div>
        {specs.map((s: any) => (
          <div key={s.kind} style={{ fontSize: 11 }}>
            <b>{s.kind}</b> <span style={{ color: t.dim }}>{s.purpose.slice(0, 90)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ResearchPanel({ t, say }: { t: typeof themes.dark; say: (m: string) => void }) {
  const [targets, setTargets] = useState<any[]>([]);
  const [route, setRoute] = useState<any>(null);
  const [coverage, setCoverage] = useState<any>(null);

  const load = async () => {
    const tg = await api<any[]>("/api/targets/search", {
      method: "POST", body: JSON.stringify({ query: "" }),
    });
    setTargets(tg.slice(0, 30));
    setCoverage(await api<any>("/api/coverage"));
  };
  useEffect(() => { load(); }, []); // eslint-disable-line

  return (
    <div>
      <div style={{ ...box(t), fontSize: 12 }}>
        {coverage ? `targets: ${coverage.total_targets}, untested: ${coverage.untested_count} - ${coverage.note}` : ""}
      </div>
      <div style={{ ...box(t), marginTop: 8, maxHeight: 300, overflow: "auto" }}>
        <div style={label(t)}>Apple target universe (route any target)</div>
        {targets.map((t2: any) => (
          <div key={t2.target_id} style={{ fontSize: 11, display: "flex", gap: 8 }}>
            <span style={{ color: t.dim }}>{t2.parent_category}</span>
            <span>{t2.product}</span>
            <button style={{ ...btn(t), padding: "0 6px", marginLeft: "auto", fontSize: 10 }}
              onClick={async () => {
                const rec = await api<any>("/api/targets/route", {
                  method: "POST",
                  body: JSON.stringify({ target_id: t2.target_id }),
                });
                setRoute(rec);
                say(`route ${t2.target_id}: ${rec.chosen.engine}/${rec.chosen.template}`);
              }}>route</button>
          </div>
        ))}
      </div>
      {route ? (
        <div style={{ ...box(t), marginTop: 8 }}>
          <div style={label(t)}>routing decision ({route.target_id})</div>
          <div style={{ fontSize: 12 }}>chosen: {route.chosen.engine}/{route.chosen.template}</div>
          <div style={{ fontSize: 11, color: t.dim }}>
            capabilities: {route.required_capabilities.join(", ")}
          </div>
          {route.ranked_experiments.map((e: any, i: number) => (
            <div key={i} style={{ fontSize: 11 }}>
              {i + 1}. {e.engine}/{e.template} score {e.score} (impact {e.impact},
              auth-burden {e.authorization_burden}, risk {e.safety_risk})
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ArtifactsPanel({ t, say }: { t: typeof themes.dark; say: (m: string) => void }) {
  const [items, setItems] = useState<ArtifactRec[]>([]);
  const [content, setContent] = useState("");

  const load = async () => setItems(await api<ArtifactRec[]>("/api/artifacts"));
  useEffect(() => { load(); }, []); // eslint-disable-line

  return (
    <div>
      <div style={box(t)}>
        <div style={label(t)}>artifacts (provenance + integrity)</div>
        {items.slice(-25).reverse().map((a: ArtifactRec) => (
          <div key={a.artifact_id} style={{ fontSize: 11, display: "flex", gap: 8 }}>
            <span style={{ color: t.dim }}>{a.artifact_id}</span>
            <span>{a.type}</span>
            <span style={{ color: t.dim }}>{a.sha256.slice(0, 16)}</span>
            <button style={{ ...btn(t), padding: "0 6px", marginLeft: "auto", fontSize: 10 }}
              onClick={async () => {
                const rec = await api<any>(`/api/artifacts/${a.artifact_id}`);
                setContent(`integrity=${rec.integrity}\n${(rec.content ?? "").slice(0, 3000)}`);
              }}>open</button>
          </div>
        ))}
        {items.length === 0 ? <div style={{ fontSize: 11, color: t.dim }}>none yet</div> : null}
      </div>
      <div style={{ ...box(t), marginTop: 8 }}>
        <div style={label(t)}>artifact content</div>
        <pre style={{ fontSize: 11, margin: 0, maxHeight: 260, overflow: "auto",
                      whiteSpace: "pre-wrap" }}>{content}</pre>
      </div>
      <div style={{ ...box(t), marginTop: 8 }}>
        <button style={btn(t)} onClick={async () => {
          const rec = await api<any>("/api/evidence/stats");
          say(`evidence: ${JSON.stringify(rec)}`);
        }}>evidence stats</button>
      </div>
    </div>
  );
}

function SettingsPanel({ t, say }: { t: typeof themes.dark; say: (m: string) => void }) {
  const [providers, setProviders] = useState<any>(null);
  const [models, setModels] = useState<any>(null);
  const [caps, setCaps] = useState<any>(null);
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://");
  const [model, setModel] = useState("");
  const [role, setRole] = useState("coordinator");

  const load = async () => {
    setProviders(await api<any>("/api/providers"));
    setModels(await api<any>("/api/models"));
    setCaps(await api<any>("/api/permissions"));
  };
  useEffect(() => { load(); }, []); // eslint-disable-line

  return (
    <div>
      <div style={{ ...box(t) }}>
        <div style={label(t)}>provider (OpenAI-compatible, https only)</div>
        <div style={{ display: "flex", gap: 8 }}>
          <input style={input(t)} placeholder="name" value={name}
            onChange={(e) => setName(e.target.value)} />
          <input style={{ ...input(t), flex: 2 }} placeholder="https://api ..." value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)} />
          <button style={btn(t)} onClick={async () => {
            try {
              await api("/api/providers", {
                method: "POST",
                body: JSON.stringify({ spec: { name, base_url: baseUrl, api_format: "openai" } }),
              });
              say(`provider ${name} configured (API key via OS credential store)`);
              load();
            } catch (e) { say(String(e)); }
          }}>add</button>
        </div>
        <div style={{ ...label(t) }}>role binding</div>
        <div style={{ display: "flex", gap: 8 }}>
          <select style={btn(t)} value={role} onChange={(e) => setRole(e.target.value)}>
            {["coordinator", "planner", "reasoning", "coding", "research",
              "browser", "terminal", "reviewer", "independent_reviewer",
              "falsification_reviewer", "report_writer",
              "security_researcher"].map((r) => <option key={r}>{r}</option>)}
          </select>
          <input style={{ ...input(t), flex: 2 }} placeholder="model id" value={model}
            onChange={(e) => setModel(e.target.value)} />
          <button style={btn(t)} onClick={async () => {
            try {
              await api("/api/providers/roles", {
                method: "POST",
                body: JSON.stringify({ role, provider: name, model_id: model }),
              });
              say(`role ${role} -> ${name}/${model}`);
              load();
            } catch (e) { say(String(e)); }
          }}>bind</button>
        </div>
      </div>
      <div style={{ ...box(t), marginTop: 8, fontSize: 11 }}>
        <div style={label(t)}>model routes</div>
        {models ? Object.entries(models.roles).map(([r, v]: any) => (
          <div key={r}>{r}: <span style={{ color: t.dim }}>
            {v.mode === "LOCAL" ? v.note : `${v.provider}/${v.model_id}`}</span></div>
        )) : null}
      </div>
      <div style={{ ...box(t), marginTop: 8, fontSize: 11, maxHeight: 260, overflow: "auto" }}>
        <div style={label(t)}>capabilities (deny-by-default ledger)</div>
        {caps ? (caps.grants ?? []).map((g: any, i: number) => (
          <div key={i}>{g.capability} [{g.mode}] scope={g.scope}</div>
        )) : null}
        {(caps?.grants ?? []).length === 0 ?
          <span style={{ color: t.dim }}>no grants yet</span> : null}
      </div>
    </div>
  );
}

function ReportsPanel({ t, say }: { t: typeof themes.dark; say: (m: string) => void }) {
  const [expId, setExpId] = useState("");
  const [report, setReport] = useState("");
  return (
    <div>
      <div style={{ ...box(t), display: "flex", gap: 8 }}>
        <input style={{ ...input(t), flex: 2 }} value={expId} placeholder="experiment id (EX-...)"
          onChange={(e) => setExpId(e.target.value)} />
        <button style={btn(t)} onClick={async () => {
          try {
            const r = await fetch(`${API}/api/experiments/${expId}/report.md`);
            setReport(r.ok ? await r.text() : `error ${r.status}`);
            say("report generated");
          } catch (e) { say(String(e)); }
        }}>generate report</button>
      </div>
      <div style={{ ...box(t), marginTop: 8 }}>
        <pre style={{ fontSize: 11, margin: 0, maxHeight: 420, overflow: "auto",
                      whiteSpace: "pre-wrap" }}>{report || "(reports include the mandatory not-demonstrated list)"}</pre>
      </div>
    </div>
  );
}

/* ------------------------------------------------ app */

const VIEWS = ["Tasks", "Activity", "Workspace", "Terminal", "Git",
  "Browser", "Agents", "Research", "Artifacts", "Reports", "Settings"] as const;
type View = typeof VIEWS[number];

export default function App() {
  const [theme, setTheme] = useState<Theme>("dark");
  const [view, setView] = useState<View>("Tasks");
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [consoleLog, setConsoleLog] = useState<string[]>([]);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<any>(null);

  const say = (m: string) => setConsoleLog((l) => [...l, m]);

  const refresh = async () => {
    try {
      const st = await api<any>("/api/status");
      setStatus(st);
      setConnected(true);
      const j = await api<JournalEntry[]>("/api/journal?limit=60");
      setJournal(j.slice().reverse());
    } catch {
      setConnected(false);
    }
  };

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 4000);
    return () => clearInterval(id);
  }, []);

  const t = themes[theme];

  return (
    <div style={{ background: t.bg, color: t.text, minHeight: "100vh",
                  fontFamily: "Segoe UI, sans-serif" }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12,
                    padding: "14px 16px 6px" }}>
        <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: 1 }}>CYR@</div>
        <div style={{ fontSize: 12, color: t.dim }}>local desktop agent harness</div>
        <div style={{ marginLeft: "auto", fontSize: 11, color: t.dim }}>
          backend {connected ?
            <span style={{ color: t.accent }}>loopback online</span> :
            <span style={{ color: t.bad }}>offline</span>}
          {status ? ` | journal ${status.journal.entries} entries ${status.journal.valid ? "VALID" : "TAMPERED"}` : ""}
        </div>
        <button style={btn(t)} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
          {theme === "dark" ? "light" : "dark"}
        </button>
      </div>
      <div style={{ display: "flex", padding: "0 16px 12px", gap: 6, flexWrap: "wrap" }}>
        {VIEWS.map((v) => (
          <button key={v} style={{
            ...btn(t),
            ...(view === v ? { borderColor: t.accent, color: t.accent } : {}),
          }} onClick={() => setView(v)}>{v}</button>
        ))}
      </div>
      <div style={{ padding: "0 16px" }}>
        {view === "Tasks" ? <TasksPanel t={t} refresh={refresh} say={say} /> : null}
        {view === "Activity" ? <ActivityPanel t={t} entries={journal} /> : null}
        {view === "Workspace" ? <WorkspacePanel t={t} say={say} /> : null}
        {view === "Terminal" ? <TerminalPanel t={t} say={say} /> : null}
        {view === "Git" ? <GitPanel t={t} say={say} /> : null}
        {view === "Browser" ? <BrowserPanel t={t} say={say} /> : null}
        {view === "Agents" ? <AgentsPanel t={t} say={say} /> : null}
        {view === "Research" ? <ResearchPanel t={t} say={say} /> : null}
        {view === "Artifacts" ? <ArtifactsPanel t={t} say={say} /> : null}
        {view === "Reports" ? <ReportsPanel t={t} say={say} /> : null}
        {view === "Settings" ? <SettingsPanel t={t} say={say} /> : null}
      </div>
      <div style={{ ...box(t), margin: "12px 16px", fontSize: 12 }}>
        <div style={label(t)}>console</div>
        {consoleLog.slice(-8).map((l: string, i: number) => <div key={i}>{l}</div>)}
        {consoleLog.length === 0 ?
          <span style={{ color: t.dim }}>activity log (nothing yet)</span> : null}
      </div>
      <div style={{ padding: "6px 16px", fontSize: 10, color: t.dim, display: "flex", gap: 14 }}>
        <span>engines: {status ? status.engines.filter((e: any) => e.available).map((e: any) => e.name).join(", ") : "-"}</span>
        <span>auth: deny-by-default</span>
        <span>loopback only</span>
        <span>v1.0.0</span>
      </div>
    </div>
  );
}
