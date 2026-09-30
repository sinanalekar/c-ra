import React, { useEffect, useRef, useState } from "react";

/* CYR@ - Codex-style local agent app.
   Chat-first: composer with model picker, streaming activity
   cards, provider management like OpenCode. Every control
   hits the real backend. */

const API = "http://127.0.0.1:8765";

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 300)}`);
  return r.json() as Promise<T>;
}

type Theme = "dark" | "light";
const themes = {
  dark: {
    bg: "#0b0e13", panel: "#11151d", side: "#0d1117",
    border: "#232b38", text: "#dce3ee", dim: "#76839a",
    accent: "#5fd08a", accentDim: "#2b4c3a",
    warn: "#d8b64a", bad: "#e06c6c", input: "#171c26",
    user: "#1c2a3a", assistant: "#131926",
  },
  light: {
    bg: "#eef1f6", panel: "#ffffff", side: "#e4e9f0",
    border: "#ccd4e0", text: "#1a2230", dim: "#5d6b80",
    accent: "#0f7a3d", accentDim: "#d3edda",
    warn: "#8a6200", bad: "#b3261e", input: "#f2f5fa",
    user: "#d9e6f5", assistant: "#f7f9fc",
  },
};
type ThemeT = typeof themes.dark;

type TaskRec = {
  task_id: string; objective: string; state: string;
  model?: { provider: string; model_id: string } | null;
};
type Activity = {
  type: string; [k: string]: unknown;
  command?: string; exit_code?: number | null; output?: string;
  branch?: string; changes?: { path: string; index: string; worktree: string }[];
  title?: string; text_head?: string; url?: string;
  disposition?: string; target?: string;
  capability?: string; reason?: string;
  files?: number; dirs?: number;
};
type Msg = {
  role: "user" | "assistant"; content: string; ts?: string;
  mode?: string; model?: string | null;
  activity?: Activity[]; results?: unknown[];
};
type ModelPick = { provider: string; model_id: string } | null;
type ProviderRec = {
  name: string; base_url: string; disabled: boolean;
  has_key: boolean; models: string[];
  label?: string; model_info?: Record<string, any>;
};

/* ---------------------------------------------- mini-markdown */

function Md({ text, t }: { text: string; t: ThemeT }) {
  const parts: React.ReactNode[] = [];
  let key = 0;
  const segments = text.split(/```/);
  segments.forEach((seg, i) => {
    if (i % 2 === 1) {
      const nl = seg.indexOf("\n");
      const code = nl >= 0 ? seg.slice(nl + 1) : seg;
      parts.push(
        <pre key={key++} style={{
          background: t.input, border: `1px solid ${t.border}`,
          borderRadius: 8, padding: 10, fontSize: 12,
          overflow: "auto", whiteSpace: "pre-wrap",
          margin: "6px 0",
        }}>{code}</pre>);
    } else {
      // bold + inline code
      const chunks = seg.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
      chunks.forEach((c) => {
        if (!c) return;
        if (c.startsWith("**") && c.endsWith("**")) {
          parts.push(<strong key={key++}>{c.slice(2, -2)}</strong>);
        } else if (c.startsWith("`") && c.endsWith("`") && c.length > 2) {
          parts.push(<code key={key++} style={{
            background: t.input, borderRadius: 4,
            padding: "1px 5px", fontSize: 12,
            fontFamily: "Consolas, monospace",
          }}>{c.slice(1, -1)}</code>);
        } else {
          parts.push(<span key={key++}>{c}</span>);
        }
      });
    }
  });
  return <div style={{ lineHeight: 1.55 }}>{parts}</div>;
}

/* ---------------------------------------------- activity cards */

function GrantButton({ t, cap, onGranted }: {
  t: ThemeT; cap: string; onGranted: () => void }) {
  const [done, setDone] = useState(false);
  return (
    <button style={{
      fontSize: 11, padding: "4px 10px", cursor: "pointer",
      background: done ? t.accentDim : t.accent,
      color: done ? t.accent : "#08120b", border: "none",
      borderRadius: 6, fontWeight: 600,
    }} onClick={async () => {
      if (done) return;
      await api("/api/permissions/grant", {
        method: "POST",
        body: JSON.stringify({ capability: cap, mode: "allow_session" }),
      });
      setDone(true);
      onGranted();
    }}>{done ? "granted for session" : `Grant ${cap}`}</button>
  );
}

function ActivityCard({ a, t, onGranted, say }: {
  a: Activity; t: ThemeT; onGranted: () => void;
  say: (m: string) => void;
}) {
  const card: React.CSSProperties = {
    background: t.panel, border: `1px solid ${t.border}`,
    borderRadius: 8, padding: 10, margin: "6px 0",
    fontSize: 12,
  };
  const head: React.CSSProperties = {
    color: t.dim, fontSize: 10, textTransform: "uppercase",
    letterSpacing: 1, marginBottom: 4,
  };
  if (a.type === "terminal") {
    return (
      <div style={card}>
        <div style={head}>terminal
          {a.exit_code != null && (
            <span style={{
              marginLeft: 8, color: a.exit_code === 0 ? t.accent : t.bad,
            }}>exit {a.exit_code}</span>)}
        </div>
        <div style={{ fontFamily: "Consolas, monospace", fontSize: 11,
                      color: t.text, whiteSpace: "pre-wrap",
                      maxHeight: 240, overflow: "auto" }}>
          {(a.output ?? "").trim() || "(no output)"}
        </div>
      </div>);
  }
  if (a.type === "git_status") {
    const changes: any[] = (a.changes ?? []).slice(0, 10);
    return (
      <div style={card}>
        <div style={head}>git status - branch {a.branch ?? "?"}</div>
        {changes.length === 0 ?
          <span style={{ color: t.dim }}>clean</span> :
          changes.map((c, i) => (
            <div key={i} style={{ fontFamily: "Consolas, monospace", fontSize: 11 }}>
              <span style={{ color: c.index !== " " || c.worktree !== " " ? t.warn : t.dim }}>
                {c.index}{c.worktree}
              </span> {c.path}
            </div>))}
      </div>);
  }
  if (a.type === "browser") {
    return (
      <div style={card}>
        <div style={head}>browser - {a.url}</div>
        <div style={{ color: t.accent }}>{a.title}</div>
        <div style={{ color: t.dim, fontSize: 11 }}>
          {(a.text_head ?? "").slice(0, 220)}...</div>
      </div>);
  }
  if (a.type === "research") {
    return (
      <div style={card}>
        <div style={head}>research loop - {a.target}</div>
        <span style={{ color: a.disposition === "SUPPORTED" ? t.accent : t.warn,
                      fontWeight: 600 }}>{a.disposition}</span>
        <span style={{ color: t.dim }}> (gates: negative controls + reproduction)</span>
      </div>);
  }
  if (a.type === "workspace") {
    return (
      <div style={card}>
        <div style={head}>workspace</div>
        <span>{a.files} files, {a.dirs} directories</span>
      </div>);
  }
  if (a.type === "permission_request") {
    return (
      <div style={{ ...card, borderColor: t.warn }}>
        <div style={{ ...head, color: t.warn }}>authorization required</div>
        <div>{a.capability} - {a.reason}</div>
        <div style={{ marginTop: 8 }}>
          <GrantButton t={t} cap={a.capability!} onGranted={() => {
            say(`granted ${a.capability} - re-running your request`);
            onGranted();
          }} />
        </div>
      </div>);
  }
  if (a.type === "error") {
    return (
      <div style={{ ...card, borderColor: t.bad }}>
        <div style={{ ...head, color: t.bad }}>error</div>
        <div>{String(a.detail)}</div>
      </div>);
  }
  if (a.type === "info") {
    return (
      <div style={card}>
        <div style={head}>note</div>
        <div>{String(a.detail)}</div>
      </div>);
  }
  return null;
}

/* ---------------------------------------------- settings modal */

const ROLES = ["coordinator", "planner", "reasoning", "coding",
  "research", "browser", "terminal", "reviewer",
  "independent_reviewer", "falsification_reviewer",
  "report_writer", "security_researcher"];

const SESSION_CAPS = ["filesystem.read", "filesystem.write",
  "terminal.execute", "git.read", "git.write",
  "browser.read", "browser.navigate", "research.execute",
  "engine.cider", "engine.veritas", "engine.hydra",
  "engine.seek", "engine.frontier"];

function SettingsModal({ t, close, onProvidersChanged }: {
  t: ThemeT; close: () => void;
  onProvidersChanged: () => void;
}) {
  const [providers, setProviders] = useState<ProviderRec[]>([]);
  const [bindings, setBindings] = useState<Record<string, any>>({});
  const [caps, setCaps] = useState<any>(null);
  const [name, setName] = useState("");
  const [baseUrl, setBaseUrl] = useState("https://");
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState("");
  const [msg, setMsg] = useState("");

  const load = async () => {
    const ml = await api<any>("/api/models/list");
    setProviders(ml.providers);
    setBindings(ml.role_bindings);
    setCaps(await api<any>("/api/permissions"));
  };
  useEffect(() => { load(); }, []); // eslint-disable-line

  const grantedSet = new Set(
    (caps?.grants ?? []).map((g: any) => g.capability));

  const add = async (testOnly = false) => {
    try {
      const spec: any = {
        name, base_url: baseUrl, api_format: "openai",
        model_ids: models.split(",").map((m) => m.trim())
          .filter(Boolean),
      };
      if (testOnly) {
        if (!providers.some((p) => p.name === name)) {
          await api("/api/providers/with_key", {
            method: "POST",
            body: JSON.stringify({ spec, api_key: apiKey }),
          });
        }
        const res = await api<any>("/api/providers/test", {
          method: "POST",
          body: JSON.stringify({ name }),
        });
        if (res.ok) {
          setMsg(`connection OK - ${res.models.length} models visible`);
          if (res.models.length && !models) {
            setModels(res.models.slice(0, 12).join(", "));
          }
        } else setMsg(`connection failed: ${res.reason}`);
      } else {
        await api("/api/providers/with_key", {
          method: "POST",
          body: JSON.stringify({ spec, api_key: apiKey }),
        });
        setMsg(`provider ${name} added${apiKey ? " (key stored in OS credential vault)" : ""}`);
        setName(""); setBaseUrl("https://"); setApiKey(""); setModels("");
        await load();
        onProvidersChanged();
      }
    } catch (e) { setMsg(String(e)); }
  };

  const field = (v: string, set: (s: string) => void,
    ph: string, pw = false, flex = 1) => (
    <input value={v} placeholder={ph}
      type={pw ? "password" : "text"}
      style={{ flex, background: t.input, color: t.text,
        border: `1px solid ${t.border}`, borderRadius: 6,
        padding: "6px 9px", fontSize: 12, minWidth: 0 }}
      onChange={(e) => set(e.target.value)} />
  );

  return (
    <div style={{
      position: "fixed", inset: 0, background: "rgba(0,0,0,0.55)",
      display: "flex", alignItems: "center",
      justifyContent: "center", zIndex: 50,
    }} onClick={close}>
      <div style={{
        background: t.panel, border: `1px solid ${t.border}`,
        borderRadius: 12, width: "min(720px, 92vw)",
        maxHeight: "86vh", overflow: "auto", padding: 20,
      }} onClick={(e) => e.stopPropagation()}>
        <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 14 }}>
          Settings</div>

        {/* providers */}
        <div style={{ fontSize: 11, textTransform: "uppercase",
                      letterSpacing: 1, color: t.dim, margin: "4px 0 8px",
                      display: "flex", alignItems: "center" }}>
          <span style={{ marginRight: "auto" }}>
            providers (OpenAI-compatible)</span>
          <button onClick={async () => {
            const r = await api<any>(
              "/api/providers/discover", {
              method: "POST", body: "{}",
            });
            setMsg(`discovery: ` + (r.discovered ?? [])
              .map((d: any) => `${d.provider} (${d.models} models, ${d.live_catalog ? "live catalog" : "config"})`)
              .join(", ") + (r.default_binding ?
                ` | default -> ${r.default_binding.provider}/${r.default_binding.model_id}` : ""));
            await load();
            onProvidersChanged();
          }} style={{
            fontSize: 10, padding: "3px 10px", cursor: "pointer",
            background: t.accent, color: "#08120b", border: "none",
            borderRadius: 6, fontWeight: 600,
          }}>auto-discover</button>
        </div>
        {providers.map((p) => (
          <div key={p.name} style={{
            display: "flex", gap: 8, fontSize: 12,
            alignItems: "center", marginBottom: 4,
          }}>
            <b>{p.label ?? p.name}</b>
            <span style={{ color: t.dim }}>{p.base_url}</span>
            <span style={{ color: p.has_key ? t.accent : t.bad }}>
              {p.has_key ? "key in vault" : "no key"}</span>
            <span style={{ color: t.dim }}>{p.models.length} models</span>
            <button style={{
              fontSize: 10, padding: "2px 8px",
              background: t.input,
              color: p.disabled ? t.bad : t.accent,
              border: `1px solid ${t.border}`, borderRadius: 6,
            }} onClick={async () => {
              await api("/api/providers/test", {
                method: "POST",
                body: JSON.stringify({ name: p.name }),
              }).then((r: any) =>
                setMsg(r.ok ? `${p.name}: OK (${r.models.length} models)`
                  : `${p.name}: ${r.reason}`))
                .catch((e) => setMsg(String(e)));
            }}>test</button>
          </div>
        ))}
        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          {field(name, setName, "provider name")}
          {field(baseUrl, setBaseUrl, "https://api.provider.com/v1", false, 2)}
          {field(apiKey, setApiKey, "API key (stored in OS vault, never logged)", true, 2)}
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
          {field(models, setModels,
            "model ids, comma separated (or use test to fetch)", false, 3)}
          <button onClick={() => add(true)} style={{
            background: t.input, color: t.text,
            border: `1px solid ${t.border}`, borderRadius: 6,
            padding: "5px 12px", fontSize: 12, cursor: "pointer",
          }}>test / fetch models</button>
          <button onClick={() => add(false)} style={{
            background: t.accent, color: "#08120b",
            border: "none", borderRadius: 6,
            padding: "5px 12px", fontSize: 12,
            fontWeight: 600, cursor: "pointer",
          }}>add provider</button>
        </div>
        {msg ? <div style={{ fontSize: 11, color: t.dim, marginTop: 6 }}>{msg}</div> : null}

        {/* role bindings */}
        <div style={{ fontSize: 11, textTransform: "uppercase",
                      letterSpacing: 1, color: t.dim, margin: "18px 0 8px" }}>
          role bindings</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
          {ROLES.map((role) => {
            const b = bindings[role] ?? {};
            const providerList = providers.length ?
              providers : [];
            return (
              <div key={role} style={{ display: "flex", gap: 6,
                                        alignItems: "center", fontSize: 11 }}>
                <span style={{ width: 122, color: t.dim }}>{role}</span>
                <select value={b.provider ?? ""} style={{
                  flex: 1, background: t.input, color: t.text,
                  border: `1px solid ${t.border}`, borderRadius: 4,
                  padding: "3px 4px", fontSize: 11 }}
                  onChange={async (e) => {
                    const provider = e.target.value;
                    const model_id = provider ?
                      (providers.find((p) => p.name === provider)
                        ?.models[0] ?? "") : "";
                    await api("/api/providers/roles", {
                      method: "POST",
                      body: JSON.stringify({ role, provider, model_id }),
                    }).then(() => load())
                      .catch((err) => setMsg(String(err)));
                  }}>
                  <option value="">LOCAL (deterministic)</option>
                  {providerList.map((p) =>
                    <option key={p.name} value={p.name}>{p.name}</option>)}
                </select>
                {b.provider ? <span style={{ color: t.dim, fontSize: 10 }}>
                  {b.model_id}</span> : null}
              </div>);
          })}
        </div>

        {/* capabilities */}
        <div style={{ fontSize: 11, textTransform: "uppercase",
                      letterSpacing: 1, color: t.dim, margin: "18px 0 8px" }}>
          session capabilities (deny-by-default)</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {SESSION_CAPS.map((c) => (
            <button key={c} onClick={async () => {
              await api("/api/permissions/grant", {
                method: "POST",
                body: JSON.stringify({ capability: c, mode: "allow_session" }),
              });
              load();
            }} style={{
              fontSize: 10, padding: "3px 8px", cursor: "pointer",
              background: grantedSet.has(c) ? t.accentDim : t.input,
              color: grantedSet.has(c) ? t.accent : t.dim,
              border: `1px solid ${t.border}`, borderRadius: 12,
            }}>{c}{grantedSet.has(c) ? " ✓" : ""}</button>
          ))}
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end",
                      marginTop: 18 }}>
          <button onClick={close} style={{
            background: t.accent, color: "#08120b",
            border: "none", borderRadius: 6, padding: "6px 16px",
            fontSize: 12, fontWeight: 600, cursor: "pointer",
          }}>done</button>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------- model picker */

function ModelPicker({ t, value, onChange, openSettings }: {
  t: ThemeT; value: ModelPick;
  onChange: (m: ModelPick) => void;
  openSettings: () => void;
}) {
  const [providers, setProviders] = useState<ProviderRec[]>([]);
  const [info, setInfo] = useState<Record<string, any>>({});
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");

  const load = async () => {
    const m = await api<any>("/api/models/list");
    setProviders(m.providers);
    const map: Record<string, any> = {};
    m.providers.forEach((p: any) => {
      map[p.name] = p.model_info ?? {};
    });
    setInfo(map);
  };
  useEffect(() => { load(); }, [open]);

  const display = (p: string, m: string) =>
    info[p]?.[m]?.name && info[p][m].name !== m ?
      info[p][m].name : null;

  const label = value ?
    (display(value.provider, value.model_id) ??
     `${value.provider}/${value.model_id}`) : "LOCAL";
  const total = providers.reduce(
    (a, p) => a + p.models.length, 0);

  return (
    <div style={{ position: "relative" }}>
      <button onClick={() => { setOpen(!open); setFilter(""); }}
        style={{
          background: t.input,
          color: value ? t.accent : t.dim,
          border: `1px solid ${t.border}`,
          borderRadius: 14, padding: "3px 12px",
          fontSize: 11, cursor: "pointer",
          fontWeight: 600, whiteSpace: "nowrap",
          maxWidth: 260, overflow: "hidden",
          textOverflow: "ellipsis",
        }}>◈ {label} ▾</button>
      {open ? (
        <div style={{
          position: "absolute", bottom: "110%", left: 0,
          background: t.panel,
          border: `1px solid ${t.border}`,
          borderRadius: 8, width: 320, zIndex: 40,
          boxShadow: "0 8px 24px rgba(0,0,0,0.4)",
        }}>
          {total > 20 ? (
            <input value={filter} autoFocus
              placeholder={`filter ${total} models ...`}
              onChange={(e) => setFilter(e.target.value)}
              style={{
                width: "100%", boxSizing: "border-box",
                background: t.input, color: t.text,
                border: "none", borderBottom:
                  `1px solid ${t.border}`,
                padding: "8px 12px", fontSize: 12,
                borderRadius: "8px 8px 0 0",
                outline: "none",
              }} />
          ) : null}
          <div style={{
            maxHeight: 280, overflowY: "auto",
            borderRadius: "0 0 8px 8px",
          }}>
            <div onClick={() => {
              onChange(null); setOpen(false);
            }} style={{
              padding: "7px 12px", fontSize: 12,
              cursor: "pointer",
              color: value === null ? t.accent : t.text,
            }}>
              LOCAL (deterministic - real tools, no model)
            </div>
            {providers.map((p) => {
              const f = filter.toLowerCase();
              const models = f ?
                p.models.filter((m) =>
                  m.toLowerCase().includes(f) ||
                  (display(p.name, m) ?? "")
                    .toLowerCase().includes(f))
                : p.models;
              if (filter && models.length === 0)
                return null;
              return (
                <div key={p.name}>
                  <div style={{
                    padding: "5px 12px 2px", fontSize: 10,
                    color: t.dim, textTransform: "uppercase",
                    letterSpacing: 1,
                    display: "flex", gap: 6,
                  }}>
                    <span>{p.name}</span>
                    <span style={{ marginLeft: "auto" }}>
                      {p.models.length}</span>
                  </div>
                  {models.slice(0, 60).map((m) => (
                    <div key={m} onClick={() => {
                      onChange({
                        provider: p.name, model_id: m });
                      setOpen(false);
                    }} style={{
                      padding: "5px 16px", fontSize: 12,
                      cursor: "pointer",
                      color: value?.model_id === m &&
                        value?.provider === p.name ?
                        t.accent : t.text,
                    }}>
                      {display(p.name, m) ?? m}
                      {display(p.name, m) ? (
                        <span style={{
                          color: t.dim, fontSize: 10,
                          marginLeft: 6,
                        }}>{m}</span>) : null}
                    </div>
                  ))}
                  {models.length > 60 ? (
                    <div style={{
                      padding: "4px 16px 6px", fontSize: 10,
                      color: t.dim,
                    }}>+{models.length - 60} more -
                      use the filter</div>
                  ) : null}
                  {!p.has_key ? (
                    <div style={{
                      padding: "2px 16px 6px", fontSize: 10,
                      color: t.bad,
                    }}>no API key stored</div>
                  ) : null}
                </div>
              );
            })}
            <div onClick={() => {
              openSettings(); setOpen(false);
            }} style={{
              padding: "7px 12px", fontSize: 12,
              cursor: "pointer",
              borderTop: `1px solid ${t.border}`,
              color: t.dim,
            }}>Manage providers & models...</div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------- app */

export default function App() {
  const [theme, setTheme] = useState<Theme>("dark");
  const t = themes[theme];
  const [tasks, setTasks] = useState<TaskRec[]>([]);
  const [activeTask, setActiveTask] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [model, setModel] = useState<ModelPick>(null);
  const [taskModel, setTaskModel] = useState<ModelPick>(null);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [journalValid, setJournalValid] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [consoleMsg, setConsoleMsg] = useState<string[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastUserText = useRef("");

  const say = (m: string) => setConsoleMsg((l) => [...l.slice(-6), m]);

  const loadTasks = async () => {
    try {
      const list = await api<TaskRec[]>("/api/tasks");
      setTasks(list);
      setConnected(true);
      const j = await api<any>("/api/journal/verify");
      setJournalValid(j.valid);
    } catch { setConnected(false); }
  };

  const loadMessages = async (taskId: string) => {
    try {
      const r = await api<{ messages: Msg[] }>(
        `/api/chat/${taskId}/messages`);
      setMessages(r.messages);
    } catch { setMessages([]); }
  };

  useEffect(() => {
    loadTasks();
    const id = window.setInterval(loadTasks, 5000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (activeTask) {
      loadMessages(activeTask);
      api<any>(`/api/tasks/${activeTask}`).then((task) =>
        setTaskModel(task.model ?? null));
    } else setMessages([]);
  }, [activeTask]);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const newTask = async () => {
    const objective = draft.trim() ||
      "New conversation";
    const rec = await api<TaskRec>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ objective }),
    });
    setActiveTask(rec.task_id);
    setTasks((l) => [...l, rec]);
    const text = draft.trim();
    setDraft("");
    if (text) send(text, rec.task_id);
  };

  const send = async (textArg?: string, taskIdArg?: string) => {
    const text = (textArg ?? draft).trim();
    const tid = taskIdArg ?? activeTask;
    if (!text || !tid) return;
    lastUserText.current = text;
    if (!textArg) setDraft("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: text }]);
    try {
      const effective = taskModel ?? model;
      const out = await api<{ assistant: Msg }>(`/api/chat`, {
        method: "POST",
        body: JSON.stringify({
          task_id: tid, text,
          model: effective,
          set_task_model: !!effective,
        }),
      });
      await loadMessages(tid);
      if (effective) {
        await api(`/api/tasks/${tid}/model`, {
          method: "POST",
          body: JSON.stringify({ model: effective }),
        }).catch(() => { });
      }
      loadTasks();
    } catch (e) {
      setMessages((m) => [...m, {
        role: "assistant",
        content: `error: ${String(e)}`,
        mode: "error",
      }]);
    }
    setBusy(false);
  };

  const activeModel = taskModel ?? model;

  return (
    <div style={{
      display: "flex", height: "100vh",
      background: t.bg, color: t.text,
      fontFamily: "Inter, 'Segoe UI', sans-serif",
    }}>
      {/* ---------------- sidebar ---------------- */}
      <div style={{
        width: 240, background: t.side,
        borderRight: `1px solid ${t.border}`,
        display: "flex", flexDirection: "column",
      }}>
        <div style={{
          padding: "16px 14px 10px", fontSize: 20,
          fontWeight: 800, letterSpacing: 2,
        }}>CYR@</div>
        <div style={{ padding: "0 14px 12px" }}>
          <button onClick={newTask} style={{
            width: "100%", background: t.accent,
            color: "#08120b", border: "none",
            borderRadius: 8, padding: "9px 0",
            fontSize: 13, fontWeight: 700, cursor: "pointer",
          }}>+ New task</button>
        </div>
        <div style={{
          flex: 1, overflowY: "auto", padding: "0 8px",
        }}>
          {tasks.slice(-40).reverse().map((task) => (
            <div key={task.task_id} onClick={() =>
              setActiveTask(task.task_id)} style={{
              padding: "8px 10px", borderRadius: 7,
              cursor: "pointer", marginBottom: 2, fontSize: 12,
              background: activeTask === task.task_id ?
                t.panel : "transparent",
              border: activeTask === task.task_id ?
                `1px solid ${t.border}` : "1px solid transparent",
            }}>
              <div style={{
                overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap", fontWeight: 500,
              }}>{task.objective}</div>
              <div style={{ fontSize: 10, color: t.dim }}>
                <span style={{
                  color: task.state === "running" ? t.accent :
                    task.state === "paused" ? t.warn :
                    task.state === "cancelled" ? t.bad : t.dim,
                }}>{task.state}</span>
                {task.model ? ` - ${task.model.model_id}` : ""}
              </div>
            </div>
          ))}
        </div>
        <div style={{
          borderTop: `1px solid ${t.border}`,
          padding: 10, display: "flex", gap: 8,
        }}>
          <button onClick={() => setShowSettings(true)}
            style={{
              flex: 1, background: t.input, color: t.text,
              border: `1px solid ${t.border}`,
              borderRadius: 8, padding: "7px 0", fontSize: 12,
              cursor: "pointer",
            }}>Settings</button>
          <button onClick={() => setTheme(
            theme === "dark" ? "light" : "dark")}
            style={{
              background: t.input, color: t.text,
              border: `1px solid ${t.border}`,
              borderRadius: 8, padding: "7px 10px",
              fontSize: 12, cursor: "pointer",
            }}>{theme === "dark" ? "☀" : "☾"}</button>
        </div>
      </div>

      {/* ---------------- main ---------------- */}
      <div style={{
        flex: 1, display: "flex", flexDirection: "column",
        minWidth: 0,
      }}>
        {/* header */}
        <div style={{
          padding: "12px 20px", borderBottom:
            `1px solid ${t.border}`,
          display: "flex", alignItems: "center", gap: 12,
        }}>
          <div style={{
            flex: 1, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap",
            fontSize: 13, fontWeight: 600,
          }}>
            {activeTask ?
              tasks.find((x) => x.task_id === activeTask)?.objective
              ?? "conversation"
              : "CYR@ - start a new task"}
          </div>
          <span style={{
            fontSize: 10, color: connected ? t.accent : t.bad,
          }}>● {connected ? "local backend online" :
            "backend offline"}</span>
          <span style={{
            fontSize: 10, color: journalValid ? t.dim : t.bad,
          }}>journal {journalValid ? "valid" : "tampered"}</span>
        </div>

        {/* thread */}
        <div ref={scrollRef} style={{
          flex: 1, overflowY: "auto",
          display: "flex", justifyContent: "center",
        }}>
          <div style={{
            width: "min(780px, 100%)", padding: "20px 16px 8px",
          }}>
            {!activeTask ? (
              <div style={{
                textAlign: "center", marginTop: "12vh", color: t.dim,
              }}>
                <div style={{ fontSize: 44, fontWeight: 800,
                              letterSpacing: 3, color: t.text }}>
                  CYR@</div>
                <div style={{ marginTop: 8, fontSize: 13 }}>
                  Type a task below - I plan, authorize, and execute
                  with real tools (terminal, files, git, browser,
                  security research).</div>
                <div style={{ marginTop: 14, fontSize: 11, color: t.dim }}>
                  run `print('hi')` - show git status - research the
                  WebKit target - analyze this repo</div>
              </div>
            ) : null}
            {messages.map((m, i) => (
              <div key={i} style={{
                marginTop: 12,
                display: "flex",
                justifyContent: m.role === "user" ?
                  "flex-end" : "flex-start",
              }}>
                <div style={{
                  maxWidth: m.role === "user" ? "78%" : "100%",
                  background: m.role === "user" ? t.user : t.assistant,
                  border: m.role === "assistant" ?
                    `1px solid ${t.border}` : "none",
                  borderRadius: 12, padding: "10px 14px",
                  fontSize: 13.5,
                }}>
                  {m.role === "assistant" && (m.activity ?? []).map(
                    (a, j) => (
                      <ActivityCard key={j} a={a} t={t}
                        onGranted={() => {
                          // auto re-run after granting
                          send(lastUserText.current);
                        }}
                        say={say} />))}
                  <Md text={m.content} t={t} />
                  {m.role === "assistant" && m.mode === "LOCAL" ? (
                    <div style={{
                      fontSize: 10, color: t.dim, marginTop: 6,
                      borderTop: `1px dashed ${t.border}`,
                      paddingTop: 4,
                    }}>LOCAL mode - deterministic reply from real
                      tool results (configure a model in Settings
                      for model-composed replies)</div>
                  ) : null}
                  {m.role === "assistant" && m.mode === "remote" ? (
                    <div style={{
                      fontSize: 10, color: t.dim, marginTop: 6,
                    }}>{m.model}</div>
                  ) : null}
                </div>
              </div>
            ))}
            {busy ? (
              <div style={{
                marginTop: 10, color: t.dim, fontSize: 12,
                display: "flex", gap: 8, alignItems: "center",
              }}>
                <span className="pulse" style={{
                  width: 8, height: 8, borderRadius: 8,
                  background: t.accent, display: "inline-block",
                }} />
                working - executing tools ...
              </div>
            ) : null}
          </div>
        </div>

        {/* composer */}
        <div style={{
          borderTop: `1px solid ${t.border}`,
          padding: "12px 16px 16px",
          display: "flex", justifyContent: "center",
        }}>
          <div style={{
            width: "min(780px, 100%)",
            background: t.panel,
            border: `1px solid ${t.border}`,
            borderRadius: 14, padding: "10px 12px",
            display: "flex", flexDirection: "column", gap: 8,
          }}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  activeTask ? send() : newTask();
                }
              }}
              placeholder={activeTask ?
                "message CYR@ ... (Enter to send, Shift+Enter newline)" :
                "describe a task to start ..."}
              rows={2}
              style={{
                background: "transparent", color: t.text,
                border: "none", outline: "none", resize: "none",
                fontSize: 13.5, fontFamily: "inherit",
                maxHeight: 180,
              }} />
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <ModelPicker t={t} value={activeModel}
                onChange={(m) => {
                  setModel(m); setTaskModel(m);
                  if (activeTask) api(
                    `/api/tasks/${activeTask}/model`, {
                    method: "POST",
                    body: JSON.stringify({ model: m }),
                  }).catch(() => { });
                }}
                openSettings={() => setShowSettings(true)} />
              <span style={{
                fontSize: 10, color: t.dim,
              }}>loopback - deny-by-default auth</span>
              <button onClick={() =>
                activeTask ? send() : newTask()} disabled={busy}
                style={{
                  marginLeft: "auto",
                  background: busy ? t.accentDim : t.accent,
                  color: "#08120b", border: "none",
                  borderRadius: 9, padding: "7px 18px",
                  fontSize: 13, fontWeight: 700,
                  cursor: busy ? "default" : "pointer",
                }}>{busy ? "..." : "send"}</button>
            </div>
          </div>
        </div>

        {/* console strip */}
        {consoleMsg.length ? (
          <div style={{
            borderTop: `1px solid ${t.border}`,
            padding: "5px 16px", fontSize: 10, color: t.dim,
            maxHeight: 46, overflow: "hidden",
          }}>
            {consoleMsg.slice(-2).map((m, i) => <div key={i}>{m}</div>)}
          </div>
        ) : null}
      </div>

      {showSettings ? (
        <SettingsModal t={t} close={() => setShowSettings(false)}
          onProvidersChanged={() => { loadTasks(); }} />
      ) : null}
    </div>
  );
}
