import React, { useEffect, useRef, useState } from "react";

/* CYR@ - modern local agent app. Chat-first, Codex-like.
   Every control hits the real backend. */

const API = "http://127.0.0.1:8765";

async function api<T>(p: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + p, {
    headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 300)}`);
  return r.json() as Promise<T>;
}

type Theme = "dark" | "light";
const themes = {
  dark: {
    bg: "#0d1117", side: "#0a0e14", panel: "#151b26",
    surface: "#111722", border: "#232d3d",
    text: "#e6edf3", dim: "#8b98ab", faint: "#5c6a7e",
    accent: "#34e2b2", accentText: "#052e21",
    grad: "linear-gradient(135deg,#22c59f 0%,#0d9474 100%)",
    warn: "#e3b34e", bad: "#f26d6d", input: "#151b26",
    user: "#1b2735", assistant: "#10161f",
    shadow: "0 8px 28px rgba(0,0,0,0.45)",
  },
  light: {
    bg: "#f6f8fb", side: "#eef1f6", panel: "#ffffff",
    surface: "#f4f6fa", border: "#dde3ec",
    text: "#1a2230", dim: "#5d6b80", faint: "#93a1b3",
    accent: "#0e9e6e", accentText: "#ffffff",
    grad: "linear-gradient(135deg,#14b88a 0%,#0b7a5e 100%)",
    warn: "#8a6200", bad: "#c0392b", input: "#f4f6fa",
    user: "#dceaf7", assistant: "#f8fafc",
    shadow: "0 8px 28px rgba(30,50,80,0.12)",
  },
};
type T = typeof themes.dark;

type TaskRec = { task_id: string; objective: string; state: string;
  model?: { provider: string; model_id: string } | null };
type Act = {
  type: string; [k: string]: unknown;
  command?: string; exit_code?: number | null; output?: string;
  branch?: string; changes?: { path: string; index: string; worktree: string }[];
  title?: string; text_head?: string; url?: string;
  disposition?: string; target?: string;
  capability?: string; reason?: string;
  files?: number; dirs?: number;
};
type Msg = { role: "user" | "assistant"; content: string; ts?: string;
  mode?: string; model?: string | null; activity?: Act[] };
type ModelPick = { provider: string; model_id: string } | null;
type ProviderRec = { name: string; base_url: string; disabled: boolean;
  has_key: boolean; models: string[]; label?: string;
  model_info?: Record<string, any> };

/* ---------------------------------------------------- logo mark */

function Mark({ size = 34 }: { size?: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: size * 0.24,
      background: "linear-gradient(135deg,#22c59f 0%,#0d9474 70%,#072822 100%)",
      display: "flex", alignItems: "center",
      justifyContent: "center", flexShrink: 0,
      boxShadow: "0 3px 12px rgba(13,148,116,0.35)",
    }}>
      <svg width={size * 0.62} height={size * 0.62}
        viewBox="0 0 24 24" fill="none">
        <path d="M19 12a7 7 0 1 1-2.05-4.95"
          stroke="#e9fdf7" strokeWidth="2.6"
          strokeLinecap="round" />
        <circle cx="12" cy="12" r="2.6" fill="#34e2b2" />
        <path d="M17.5 10.5c.6 2.2.3 4.3-1 6.2"
          stroke="#e9fdf7" strokeWidth="2.2"
          strokeLinecap="round" />
      </svg>
    </div>);
}

/* ---------------------------------------------------- markdown */

function Md({ text, t }: { text: string; t: T }) {
  const nodes: React.ReactNode[] = [];
  let k = 0;
  text.split(/```/).forEach((seg, i) => {
    if (i % 2 === 1) {
      const nl = seg.indexOf("\n");
      nodes.push(<pre key={k++} style={{
        background: t.surface, border: `1px solid ${t.border}`,
        borderRadius: 10, padding: "10px 12px", fontSize: 12,
        fontFamily: "Consolas, monospace", overflowX: "auto",
        margin: "8px 0",
      }}>{nl >= 0 ? seg.slice(nl + 1) : seg}</pre>);
    } else {
      seg.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).forEach((c) => {
        if (!c) return;
        if (c.startsWith("**")) {
          nodes.push(<strong key={k++}>{c.slice(2, -2)}</strong>);
        } else if (c.length > 2 && c.startsWith("`")) {
          nodes.push(<code key={k++} style={{
            background: t.surface, borderRadius: 5,
            padding: "1px 6px", fontSize: 12,
            fontFamily: "Consolas, monospace",
            border: `1px solid ${t.border}`,
          }}>{c.slice(1, -1)}</code>);
        } else nodes.push(<span key={k++}>{c}</span>);
      });
    }
  });
  return <div style={{ lineHeight: 1.6 }}>{nodes}</div>;
}

/* ---------------------------------------------------- cards */

function GrantBtn({ t, cap, done }: {
  t: T; cap: string; done: () => void }) {
  const [ok, setOk] = useState(false);
  return (
    <button style={{
      fontSize: 11, fontWeight: 600, padding: "5px 14px",
      cursor: ok ? "default" : "pointer", border: "none",
      borderRadius: 7,
      background: ok ? t.surface : t.accent,
      color: ok ? t.accent : t.accentText,
      transition: "all .18s",
    }} onClick={async () => {
      if (ok) return;
      await api("/api/permissions/grant", {
        method: "POST",
        body: JSON.stringify({ capability: cap, mode: "allow_session" }),
      });
      setOk(true);
      setTimeout(done, 350);
    }}>{ok ? "granted ✓" : `Grant ${cap}`}</button>);
}

function Card({ a, t, onGranted }: {
  a: Act; t: T; onGranted: () => void }) {
  const base: React.CSSProperties = {
    background: t.surface, border: `1px solid ${t.border}`,
    borderRadius: 12, padding: "10px 12px", margin: "6px 0",
    fontSize: 12, animation: "slideUp .25s ease",
  };
  const head: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 8,
    fontSize: 10, textTransform: "uppercase",
    letterSpacing: 1.2, color: t.dim,
    fontWeight: 600, marginBottom: 6,
  };
  if (a.type === "terminal") {
    return (
      <div style={base}>
        <div style={head}>terminal
          {a.exit_code != null && (
            <span style={{ color: a.exit_code === 0 ? t.accent : t.bad,
                           background: a.exit_code === 0 ?
                             "rgba(52,226,178,.1)" :
                             "rgba(242,109,109,.1)",
                           padding: "1px 8px", borderRadius: 8,
                           textTransform: "none" }}>
              exit {a.exit_code}</span>)}
        </div>
        <pre style={{ margin: 0, fontSize: 11.5,
                      fontFamily: "Consolas, monospace",
                      whiteSpace: "pre-wrap",
                      maxHeight: 220, overflowY: "auto",
                      color: t.text }}>
          {(a.output ?? "").trim() || "(no output)"}</pre>
      </div>);
  }
  if (a.type === "git_status") {
    const ch: any[] = (a.changes ?? []).slice(0, 10);
    return (
      <div style={base}>
        <div style={head}>
          <span style={{ color: t.accent }}>⑂</span> git
          <span style={{ textTransform: "none", color: t.text }}>
            {a.branch ?? ""}</span>
        </div>
        {ch.length === 0 ?
          <span style={{ color: t.dim }}>working tree clean</span> :
          ch.map((c, i) => (
            <div key={i} style={{
              fontFamily: "Consolas, monospace", fontSize: 11.5,
              display: "flex", gap: 8,
            }}>
              <span style={{ color: t.warn }}>
                {(c.index !== " " || c.worktree !== " ") ?
                  `${c.index}${c.worktree}` : "  "}</span>
              <span style={{ color: t.dim, textDecoration:
                "line-through opacity(.5)" }}>{c.path}</span>
            </div>))}
      </div>);
  }
  if (a.type === "browser") {
    return (
      <div style={base}>
        <div style={head}>◍ browser</div>
        <div style={{ fontWeight: 600, color: t.accent }}>
          {a.title}</div>
        <div style={{ color: t.dim, fontSize: 11, marginTop: 2 }}>
          {(a.text_head ?? "").slice(0, 200)}…</div>
      </div>);
  }
  if (a.type === "research") {
    return (
      <div style={base}>
        <div style={head}>⬡ research loop</div>
        <span style={{ fontWeight: 700,
          color: a.disposition === "SUPPORTED" ? t.accent : t.warn,
        }}>{a.disposition}</span>
        <span style={{ color: t.faint, marginLeft: 8 }}>
          {a.target} — negative controls + reproduction gates</span>
      </div>);
  }
  if (a.type === "workspace") {
    return (
      <div style={base}>
        <div style={head}>▤ workspace</div>
        <span>{a.files} files · {a.dirs} directories</span>
      </div>);
  }
  if (a.type === "permission_request") {
    return (
      <div style={{ ...base, borderColor: t.warn,
                    background: "rgba(227,179,78,.06)" }}>
        <div style={{ ...head, color: t.warn }}>⚠ authorization</div>
        <div style={{ marginBottom: 8 }}>
          <b>{a.capability}</b>
          <span style={{ color: t.dim }}> — {a.reason}</span></div>
        <GrantBtn t={t} cap={a.capability!} done={onGranted} />
      </div>);
  }
  if (a.type === "error") {
    return (
      <div style={{ ...base, borderColor: t.bad }}>
        <div style={{ ...head, color: t.bad }}>✕ error</div>
        <div>{String(a.detail)}</div></div>);
  }
  return null;
}

/* ---------------------------------------------------- model picker */

function ModelPicker({ t, value, onChange, openSettings }: {
  t: T; value: ModelPick;
  onChange: (m: ModelPick) => void; openSettings: () => void }) {
  const [providers, setProviders] = useState<ProviderRec[]>([]);
  const [info, setInfo] = useState<Record<string, any>>({});
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const load = async () => {
    try {
      const m = await api<any>("/api/models/list");
      setProviders(m.providers);
      const map: Record<string, any> = {};
      m.providers.forEach((p: any) => { map[p.name] = p.model_info ?? {}; });
      setInfo(map);
    } catch { /* backend offline */ }
  };
  useEffect(() => { if (open) { setFilter(""); load(); } }, [open]);
  const disp = (p: string, m: string) =>
    info[p]?.[m]?.name && info[p][m].name !== m ? info[p][m].name : null;
  const total = providers.reduce((a, p) => a + p.models.length, 0);
  return (
    <div style={{ position: "relative" }}>
      <button onClick={() => setOpen(!open)} style={{
        background: t.surface, border: `1px solid ${t.border}`,
        color: value ? t.accent : t.dim, borderRadius: 20,
        padding: "5px 14px", fontSize: 11.5, fontWeight: 600,
        cursor: "pointer", whiteSpace: "nowrap",
        maxWidth: 250, overflow: "hidden", textOverflow: "ellipsis",
        transition: "border-color .15s",
      }}>◈ {value ? (disp(value.provider, value.model_id) ??
        `${value.provider} · ${value.model_id}`) : "LOCAL"} ▾</button>
      {open && (
        <>
          <div onClick={() => setOpen(false)}
            style={{ position: "fixed", inset: 0, zIndex: 39 }} />
          <div className="anim-down" style={{
            position: "absolute", bottom: "115%", left: 0,
            background: t.panel, border: `1px solid ${t.border}`,
            borderRadius: 12, width: 330, zIndex: 40,
            boxShadow: t.shadow, overflow: "hidden",
          }}>
            {total > 15 && (
              <input value={filter} autoFocus
                placeholder={`filter ${total} models…`}
                onChange={(e) => setFilter(e.target.value)}
                style={{ width: "100%",
                  background: t.surface, color: t.text,
                  border: "none", borderBottom: `1px solid ${t.border}`,
                  padding: "9px 14px", fontSize: 12 }} />)}
            <div style={{ maxHeight: 280, overflowY: "auto" }}>
              <div onClick={() => { onChange(null); setOpen(false); }}
                style={{ padding: "8px 14px", fontSize: 12,
                  cursor: "pointer", fontWeight: 500,
                  color: value === null ? t.accent : t.text,
                  transition: "background .12s" }}
                onMouseEnter={(e) => e.currentTarget.style.background = t.surface}
                onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                LOCAL <span style={{ color: t.faint, fontWeight: 400 }}>
                  — deterministic, no model</span>
              </div>
              {providers.map((p) => {
                const f = filter.toLowerCase();
                const models = f ? p.models.filter((m) =>
                  m.toLowerCase().includes(f) ||
                  (disp(p.name, m) ?? "").toLowerCase().includes(f))
                  : p.models;
                if (f && !models.length) return null;
                return (
                  <div key={p.name}>
                    <div style={{
                      padding: "7px 14px 3px", fontSize: 10,
                      color: t.faint, textTransform: "uppercase",
                      letterSpacing: 1.2, fontWeight: 700,
                      display: "flex" }}>
                      <span>{p.label ?? p.name}</span>
                      <span style={{ marginLeft: "auto" }}>
                        {p.models.length}</span>
                    </div>
                    {models.slice(0, 50).map((m) => (
                      <div key={m} onClick={() => {
                        onChange({ provider: p.name, model_id: m });
                        setOpen(false);
                      }} style={{
                        padding: "5px 16px", fontSize: 12,
                        cursor: "pointer",
                        color: value?.model_id === m &&
                          value?.provider === p.name ?
                          t.accent : t.text,
                        transition: "background .12s",
                      }}
                        onMouseEnter={(e) => e.currentTarget.style.background = t.surface}
                        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                        {disp(p.name, m) ?? m}
                        {disp(p.name, m) && (
                          <span style={{ color: t.faint,
                                         fontSize: 10, marginLeft: 7 }}>
                            {m}</span>)}
                      </div>))}
                    {models.length > 50 && (
                      <div style={{ padding: "4px 16px 6px",
                                    fontSize: 10, color: t.faint }}>
                        +{models.length - 50} more — use filter</div>)}
                    {!p.has_key && (
                      <div style={{ padding: "2px 16px 6px",
                                    fontSize: 10, color: t.bad }}>
                        no API key in vault</div>)}
                  </div>);
              })}
              <div onClick={() => { openSettings(); setOpen(false); }}
                style={{ padding: "8px 14px", fontSize: 12,
                  cursor: "pointer", color: t.dim,
                  borderTop: `1px solid ${t.border}`,
                  fontWeight: 500 }}>
                Manage providers…
              </div>
            </div>
          </div>
        </>)}
    </div>);
}

/* ---------------------------------------------------- settings */

const ROLES = ["coordinator", "planner", "reasoning", "coding",
  "research", "browser", "terminal", "reviewer",
  "independent_reviewer", "falsification_reviewer",
  "report_writer", "security_researcher"];

function Section({ t, title, children }: {
  t: T; title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 22 }}>
      <div style={{
        fontSize: 10.5, textTransform: "uppercase", letterSpacing: 1.5,
        color: t.faint, fontWeight: 700, margin: "0 0 10px",
        display: "flex", alignItems: "center", gap: 8,
      }}>{title}<span style={{ flex: 1, height: 1,
        background: t.border }} /></div>
      {children}
    </div>);
}

function SettingsModal({ t, close }: { t: T; close: () => void }) {
  const [providers, setProviders] = useState<ProviderRec[]>([]);
  const [bindings, setBindings] = useState<Record<string, any>>({});
  const [caps, setCaps] = useState<any>(null);
  const [discovery, setDiscovery] = useState<any>(null);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("https://");
  const [key, setKey] = useState("");
  const [models, setModels] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const ml = await api<any>("/api/models/list");
      setProviders(ml.providers);
      setBindings(ml.role_bindings);
      setDiscovery(ml.discovery);
      setCaps(await api<any>("/api/permissions"));
    } catch { }
  };
  useEffect(() => { load(); }, []);
  const granted = new Set((caps?.grants ?? [])
    .map((g: any) => g.capability));

  const inp = (v: string, s: (x: string) => void,
    ph: string, pw = false) => (
    <input value={v} placeholder={ph} type={pw ? "password" : "text"}
      onChange={(e) => s(e.target.value)} style={{
        flex: 1, minWidth: 110, background: t.surface, color: t.text,
        border: `1px solid ${t.border}`, borderRadius: 8,
        padding: "8px 11px", fontSize: 12.5,
        transition: "border-color .15s",
      }} />);

  return (
    <div onClick={close} className="anim-fade" style={{
      position: "fixed", inset: 0, zIndex: 60,
      background: "rgba(2,6,12,0.65)", backdropFilter: "blur(3px)",
      display: "flex", alignItems: "center",
      justifyContent: "center",
    }}>
      <div onClick={(e) => e.stopPropagation()} className="anim-in"
        style={{
          background: t.panel, border: `1px solid ${t.border}`,
          borderRadius: 16, width: "min(760px, 94vw)",
          maxHeight: "88vh", overflowY: "auto", padding: 24,
          boxShadow: t.shadow,
        }}>
        <div style={{ display: "flex", alignItems: "center",
                      gap: 12, marginBottom: 20 }}>
          <Mark size={30} />
          <div style={{ fontSize: 17, fontWeight: 700 }}>Settings</div>
          <button onClick={close} style={{
            marginLeft: "auto", background: t.surface,
            color: t.dim, border: "none", borderRadius: 8,
            width: 30, height: 30, cursor: "pointer", fontSize: 15,
          }}>✕</button>
        </div>

        <Section t={t} title="providers">
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <button onClick={async () => {
              setBusy(true);
              try {
                const r = await api<any>(
                  "/api/providers/discover", {
                  method: "POST", body: "{}" });
                setDiscovery(r);
                setMsg(r.discovered?.length ?
                  `discovered: ${r.discovered.map((d: any) =>
                    `${d.provider} (${d.models} models)`).join(", ")}` :
                  "no new providers found");
                await load();
              } catch (e) { setMsg(String(e)); }
              setBusy(false);
            }} disabled={busy} style={{
              background: t.accent, color: t.accentText,
              border: "none", borderRadius: 8, padding: "7px 14px",
              fontSize: 12, fontWeight: 600, cursor: "pointer",
            }}>{busy ? "discovering…" : "⟳ Auto-discover providers"}</button>
          </div>
          {providers.map((p) => (
            <div key={p.name} style={{
              display: "flex", alignItems: "center", gap: 10,
              fontSize: 12.5, padding: "8px 10px",
              borderRadius: 10, marginBottom: 4,
              background: t.surface,
              border: `1px solid ${t.border}`,
            }}>
              <b>{p.label ?? p.name}</b>
              <span style={{ color: t.faint, fontSize: 11,
                overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap", flex: 1 }}>
                {p.base_url}</span>
              <span style={{
                fontSize: 10.5, fontWeight: 600,
                color: p.has_key ? t.accent : t.bad,
                background: p.has_key ?
                  "rgba(52,226,178,.1)" : "rgba(242,109,109,.1)",
                padding: "2px 9px", borderRadius: 10,
              }}>{p.has_key ? "key ✓" : "no key"}</span>
              <span style={{ color: t.dim, fontSize: 11 }}>
                {p.models.length} models</span>
            </div>))}
          <div style={{ marginTop: 12, display: "flex",
                        gap: 8, flexWrap: "wrap" }}>
            {inp(name, setName, "provider name")}
            {inp(url, setUrl, "https://api.example.com/v1")}
            {inp(key, setKey, "API key → vault", true)}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            {inp(models, setModels, "model ids (comma separated)")}
            <button onClick={async () => {
              try {
                await api("/api/providers/with_key", {
                  method: "POST",
                  body: JSON.stringify({
                    spec: { name, base_url: url,
                      api_format: "openai" },
                    api_key: key,
                    models: models.split(",")
                      .map((m) => m.trim()).filter(Boolean),
                  }) });
                setMsg(`${name} added`);
                setName(""); setUrl("https://");
                setKey(""); setModels("");
                load();
              } catch (e) { setMsg(String(e)); }
            }} style={{
              background: t.accent, color: t.accentText,
              border: "none", borderRadius: 8,
              padding: "7px 16px", fontSize: 12,
              fontWeight: 600, cursor: "pointer",
            }}>Add</button>
          </div>
          {msg ? <div style={{ fontSize: 11.5, color: t.dim,
                               marginTop: 8 }}>{msg}</div> : null}
        </Section>

        <Section t={t} title="role bindings (which model works each job)">
          <div style={{ display: "grid",
                        gridTemplateColumns: "1fr 1fr", gap: 6 }}>
            {ROLES.map((role) => {
              const b = bindings[role] ?? {};
              return (
                <div key={role} style={{
                  display: "flex", gap: 8, alignItems: "center",
                  fontSize: 11.5,
                }}>
                  <span style={{ width: 130, color: t.dim }}>
                    {role}</span>
                  <select value={b.provider ?? ""} style={{
                    flex: 1, background: t.surface, color: t.text,
                    border: `1px solid ${t.border}`,
                    borderRadius: 6, padding: "4px 6px",
                    fontSize: 11 }}
                    onChange={async (e) => {
                      const prov = e.target.value;
                      const mid = prov ?
                        providers.find((p) => p.name === prov)
                          ?.models[0] ?? "" : "";
                      await api("/api/providers/roles", {
                        method: "POST",
                        body: JSON.stringify({
                          role, provider: prov, model_id: mid }),
                      }).catch(() => { });
                      load();
                    }}>
                    <option value="">LOCAL</option>
                    {providers.map((p) =>
                      <option key={p.name} value={p.name}>
                        {p.label ?? p.name}</option>)}
                  </select>
                  {b.provider && (
                    <span style={{ color: t.faint, fontSize: 10 }}>
                      {b.model_id}</span>)}
                </div>);
            })}
          </div>
        </Section>

        <Section t={t} title="permissions">
          <div style={{
            fontSize: 12, color: t.dim, marginBottom: 10,
          }}>
            {granted.size} active grants (session). High-risk
            operations (git push, deletes, computer control)
            always ask per-operation.
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {["filesystem.read", "filesystem.write",
              "filesystem.execute", "terminal.execute",
              "git.read", "git.write", "browser.read",
              "browser.navigate", "browser.interact",
              "research.execute", "engine.veritas",
              "engine.cider", "engine.seek", "engine.hydra",
              "engine.frontier"].map((c) => (
              <span key={c} style={{
                fontSize: 10.5, padding: "3px 10px",
                borderRadius: 11,
                background: granted.has(c) ?
                  "rgba(52,226,178,.12)" : t.surface,
                color: granted.has(c) ? t.accent : t.faint,
                border: `1px solid ${granted.has(c) ?
                  "rgba(52,226,178,.3)" : t.border}`,
                fontWeight: 600,
              }}>{c}{granted.has(c) ? " ✓" : ""}</span>))}
          </div>
        </Section>

        {discovery && discovery.discovered?.length ? (
          <div style={{ fontSize: 11, color: t.faint }}>
            last discovery: {discovery.discovered.map((d: any) =>
              `${d.provider} (${d.models} models)`).join(", ")}
          </div>) : null}
      </div>
    </div>);
}

/* ---------------------------------------------------- app */

const EXAMPLES = [
  "run print('hello CYR@')",
  "show git status",
  "research the WebKit target",
  "analyze this repo",
];

export default function App() {
  const [theme, setTheme] = useState<Theme>("dark");
  const t = themes[theme];
  const [tasks, setTasks] = useState<TaskRec[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [model, setModel] = useState<ModelPick>(null);
  const [taskModel, setTaskModel] = useState<ModelPick>(null);
  const [busy, setBusy] = useState(false);
  const [conn, setConn] = useState<"off" | "starting" | "on">("off");
  const [settings, setSettings] = useState(false);
  const [showJournal, setShowJournal] = useState(false);
  const [journal, setJournal] = useState<any[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastText = useRef("");

  const poll = async () => {
    try {
      await api<any>("/api/health");
      setConn("on");
      const list = await api<TaskRec[]>("/api/tasks");
      setTasks(list);
    } catch {
      setConn((c) => c === "on" ? "starting" : "starting");
    }
  };
  useEffect(() => {
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (active) {
      api<{ messages: Msg[] }>(`/api/chat/${active}/messages`)
        .then((r) => setMessages(r.messages));
      api<any>(`/api/tasks/${active}`)
        .then((task) => setTaskModel(task.model ?? null));
    } else setMessages([]);
  }, [active]);
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: busy ? "auto" : "smooth" });
  }, [messages, busy]);

  const send = async (textArg?: string, tidArg?: string) => {
    const text = (textArg ?? draft).trim();
    const tid = tidArg ?? active;
    if (!text || !tid) return;
    lastText.current = text;
    if (!textArg) setDraft("");
    setBusy(true);
    setMessages((m) => [...m, { role: "user", content: text }]);
    try {
      const effective = taskModel ?? model;
      const out = await api<{ assistant: Msg }>("/api/chat", {
        method: "POST",
        body: JSON.stringify({ task_id: tid, text,
          model: effective, set_task_model: !!effective }),
      });
      await api<{ messages: Msg[] }>(
        `/api/chat/${tid}/messages`)
        .then((r) => setMessages(r.messages));
      poll();
    } catch (e) {
      setMessages((m) => [...m, {
        role: "assistant",
        content: `error: ${String(e)}` }]);
    }
    setBusy(false);
  };

  const newTask = async (text?: string) => {
    try {
      const rec = await api<TaskRec>("/api/tasks", {
        method: "POST",
        body: JSON.stringify({
          objective: text?.slice(0, 60) ?? "New conversation" }),
      });
      setActive(rec.task_id);
      setTasks((l) => [...l, rec]);
      if (text) send(text, rec.task_id);
    } catch { }
  };

  /* -------- connecting splash -------- */
  if (conn !== "on" && !tasks.length) {
    return (
      <div style={{
        height: "100vh", display: "flex",
        flexDirection: "column", alignItems: "center",
        justifyContent: "center", gap: 18, background: t.bg,
      }}>
        <Mark size={72} />
        <div style={{ fontSize: 22, fontWeight: 800,
                      letterSpacing: 2 }}>CYR@</div>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          <span className="spin" style={{
            width: 16, height: 16, borderRadius: 16,
            border: `2.5px solid ${t.border}`,
            borderTopColor: t.accent, display: "inline-block",
          }} />
          <span style={{ color: t.dim, fontSize: 13.5 }}>
            {conn === "off" ?
              "connecting to local backend…" :
              "starting local backend… (first launch takes ~20s)"}
          </span>
        </div>
      </div>);
  }

  return (
    <div style={{
      display: "flex", height: "100vh", background: t.bg,
      color: t.text, overflow: "hidden",
      fontFamily: "Inter, 'Segoe UI', system-ui, sans-serif",
    }}>
      {/* -------- sidebar -------- */}
      <div style={{
        width: 250, background: t.side,
        borderRight: `1px solid ${t.border}`,
        display: "flex", flexDirection: "column",
      }}>
        <div style={{ padding: "16px 14px 10px",
                      display: "flex", alignItems: "center", gap: 10 }}>
          <Mark size={30} />
          <div>
            <div style={{ fontSize: 17, fontWeight: 800,
                          letterSpacing: 1.5, lineHeight: 1 }}>
              CYR@</div>
            <div style={{ fontSize: 10, color: t.faint,
                          marginTop: 3 }}>local agent</div>
          </div>
        </div>
        <div style={{ padding: "4px 14px 14px" }}>
          <button onClick={() => { setActive(null); setMessages([]); }}
            style={{
            width: "100%", background: t.accent,
            color: t.accentText, border: "none",
            borderRadius: 10, padding: "10px 0", fontSize: 13,
            fontWeight: 700, cursor: "pointer",
            transition: "filter .15s, transform .1s",
          }}
            onMouseEnter={(e) =>
              e.currentTarget.style.filter = "brightness(1.08)"}
            onMouseLeave={(e) =>
              e.currentTarget.style.filter = "none"}>
            + New task</button>
        </div>
        <div style={{ flex: 1, overflowY: "auto", padding: "0 10px" }}>
          {tasks.slice(-50).reverse().map((task) => (
            <div key={task.task_id} onClick={() =>
              setActive(task.task_id)} style={{
              padding: "8px 10px", borderRadius: 10,
              cursor: "pointer", marginBottom: 2, fontSize: 12.5,
              background: active === task.task_id ?
                t.panel : "transparent",
              border: `1px solid ${active === task.task_id ?
                t.border : "transparent"}`,
              display: "flex", alignItems: "center", gap: 8,
              transition: "background .15s",
            }}>
              <span className={task.state === "running" ? "pulse" : ""}
                style={{
                width: 7, height: 7, borderRadius: 7,
                background: task.state === "running" ? t.accent :
                  task.state === "paused" ? t.warn :
                  task.state === "cancelled" ? t.bad : t.faint,
                flexShrink: 0,
              }} />
              <div style={{ flex: 1, overflow: "hidden" }}>
                <div style={{
                  whiteSpace: "nowrap", overflow: "hidden",
                  textOverflow: "ellipsis", fontWeight: 500,
                }}>{task.objective}</div>
                <div style={{ fontSize: 10, color: t.faint }}>
                  {task.state}{task.model ?
                    ` · ${task.model.model_id}` : ""}</div>
              </div>
              <button onClick={async (e) => {
                e.stopPropagation();
                await api(`/api/tasks/${task.task_id}`, {
                  method: "DELETE" }).catch(() => { });
                setTasks((l) => l.filter((x) =>
                  x.task_id !== task.task_id));
                if (active === task.task_id) setActive(null);
              }} style={{
                background: "transparent", border: "none",
                color: t.faint, cursor: "pointer", fontSize: 13,
                opacity: 0, transition: "opacity .15s",
              }}
                onMouseEnter={(e) =>
                  e.currentTarget.style.opacity = "1"}
                onMouseLeave={(e) =>
                  e.currentTarget.style.opacity = "0"}>✕</button>
            </div>))}
        </div>
        <div style={{
          borderTop: `1px solid ${t.border}`, padding: 10,
          display: "flex", gap: 8,
        }}>
          <button onClick={() => setSettings(true)} style={{
            flex: 1, background: t.surface, color: t.text,
            border: `1px solid ${t.border}`, borderRadius: 9,
            padding: "8px 0", fontSize: 12, fontWeight: 600,
            cursor: "pointer", transition: "border-color .15s",
          }}>⚙ Settings</button>
          <button onClick={() => {
            setTheme(theme === "dark" ? "light" : "dark");
          }} style={{
            background: t.surface, color: t.text,
            border: `1px solid ${t.border}`, borderRadius: 9,
            padding: "8px 12px", fontSize: 12, cursor: "pointer",
          }}>{theme === "dark" ? "☀" : "☾"}</button>
          <button onClick={() => {
            setShowJournal(!showJournal);
            if (!showJournal) api<any[]>("/api/journal?limit=40")
              .then((j) => setJournal(j.slice().reverse()));
          }} style={{
            background: showJournal ? t.accent : t.surface,
            color: showJournal ? t.accentText : t.text,
            border: `1px solid ${t.border}`, borderRadius: 9,
            padding: "8px 12px", fontSize: 12, cursor: "pointer",
          }}>≡</button>
        </div>
      </div>

      {/* -------- main -------- */}
      <div style={{ flex: 1, display: "flex",
                    flexDirection: "column", minWidth: 0 }}>
        <div style={{
          padding: "12px 20px", borderBottom: `1px solid ${t.border}`,
          display: "flex", alignItems: "center", gap: 12,
          fontSize: 12,
        }}>
          <div style={{ flex: 1, fontWeight: 600, fontSize: 13.5,
            overflow: "hidden", textOverflow: "ellipsis",
            whiteSpace: "nowrap" }}>
            {active ? tasks.find((x) =>
              x.task_id === active)?.objective ?? "conversation"
              : "New task"}
          </div>
          <span style={{
            display: "flex", alignItems: "center", gap: 6,
            color: conn === "on" ? t.accent : t.warn,
            fontSize: 11,
          }}>
            <span className={conn === "on" ? "" : "pulse"}
              style={{
              width: 8, height: 8, borderRadius: 8,
              background: conn === "on" ? t.accent : t.warn,
            }} />
            {conn === "on" ? "backend online" : "connecting"}
          </span>
        </div>

        {showJournal ? (
          <div style={{
            borderBottom: `1px solid ${t.border}`,
            maxHeight: 200, overflowY: "auto",
            padding: "8px 20px", fontSize: 10.5,
            background: t.side, color: t.dim,
          }}>
            {journal.map((e, i) => (
              <div key={i} style={{ display: "flex", gap: 10 }}>
                <span style={{ color: t.faint }}>
                  {e.ts?.slice(11, 19)}</span>
                <span>{e.action}</span>
              </div>))}
          </div>) : null}

        <div ref={scrollRef} style={{
          flex: 1, overflowY: "auto",
          display: "flex", justifyContent: "center",
        }}>
          <div style={{
            width: "min(780px, 100%)", padding: "24px 18px 10px",
          }}>
            {!active && !busy ? (
              <div style={{
                textAlign: "center", marginTop: "10vh",
              }}>
                <div style={{ animation: "slideUp .5s ease" }}>
                  <div style={{
                    display: "flex", justifyContent: "center",
                    marginBottom: 18,
                  }}><Mark size={64} /></div>
                  <div style={{ fontSize: 30, fontWeight: 800,
                                letterSpacing: 2 }}>CYR@</div>
                  <div style={{ marginTop: 10, color: t.dim,
                                fontSize: 13.5, lineHeight: 1.6 }}>
                    I plan, authorize, and execute with real tools —
                    terminal, files, git, browser, and the
                    security-research engines.</div>
                  <div style={{
                    display: "flex", gap: 8,
                    justifyContent: "center",
                    flexWrap: "wrap", marginTop: 22,
                  }}>
                    {EXAMPLES.map((ex, i) => (
                      <button key={i} onClick={() => newTask(ex)}
                        className="anim-in"
                        style={{
                          animationDelay: `${i * 0.07}s`,
                          background: t.surface,
                          border: `1px solid ${t.border}`,
                          borderRadius: 20, color: t.text,
                          padding: "8px 16px", fontSize: 12,
                          cursor: "pointer", fontWeight: 500,
                          transition: "all .15s",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.borderColor = t.accent;
                          e.currentTarget.style.color = t.accent;
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.borderColor = t.border;
                          e.currentTarget.style.color = t.text;
                        }}>{ex}</button>))}
                  </div>
                </div>
              </div>) : null}

            {messages.map((m, i) => (
              <div key={i} className="anim-in" style={{
                marginTop: 14, display: "flex", gap: 10,
                flexDirection: m.role === "user" ?
                  "row-reverse" : "row",
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: 8,
                  flexShrink: 0, display: "flex",
                  alignItems: "center", justifyContent: "center",
                  fontSize: 11, fontWeight: 700,
                  background: m.role === "user" ?
                    t.user : t.grad,
                  color: m.role === "user" ? t.text : "#fff",
                }}>
                  {m.role === "user" ? "you" :
                    <span style={{ fontSize: 13 }}>◈</span>}
                </div>
                <div style={{
                  maxWidth: m.role === "user" ? "72%" : "100%",
                  background: m.role === "user" ?
                    t.user : t.assistant,
                  border: `1px solid ${m.role === "user" ?
                    "transparent" : t.border}`,
                  borderRadius: 14,
                  padding: "10px 14px", fontSize: 13.5,
                }}>
                  {m.role === "assistant" &&
                    (m.activity ?? []).map((a, j) => (
                      <Card key={j} a={a} t={t}
                        onGranted={() => send(lastText.current)} />))}
                  <Md text={m.content} t={t} />
                  {m.role === "assistant" && m.mode === "LOCAL" && (
                    <div style={{
                      fontSize: 10, color: t.faint, marginTop: 8,
                      borderTop: `1px dashed ${t.border}`,
                      paddingTop: 6, display: "flex",
                      alignItems: "center", gap: 6,
                    }}>
                      LOCAL — deterministic reply from real tool
                      results
                      <button onClick={() =>
                        navigator.clipboard?.writeText(m.content)}
                        style={{
                        marginLeft: "auto", background: "none",
                        border: "none", color: t.faint,
                        cursor: "pointer", fontSize: 11,
                      }}>copy</button>
                    </div>)}
                  {m.role === "assistant" && m.mode === "remote" && (
                    <div style={{ fontSize: 10, color: t.faint,
                                  marginTop: 8, display: "flex" }}>
                      <span>{m.model}</span>
                      <button onClick={() =>
                        navigator.clipboard?.writeText(m.content)}
                        style={{
                        marginLeft: "auto", background: "none",
                        border: "none", color: t.faint,
                        cursor: "pointer", fontSize: 11,
                      }}>copy</button>
                    </div>)}
                </div>
              </div>))}

            {busy && (
              <div className="anim-in" style={{
                display: "flex", gap: 10, marginTop: 14,
              }}>
                <div style={{
                  width: 28, height: 28, borderRadius: 8,
                  background: t.grad, display: "flex",
                  alignItems: "center", justifyContent: "center",
                  color: "#fff", fontSize: 13,
                }}>◈</div>
                <div style={{
                  border: `1px solid ${t.border}`,
                  borderRadius: 14, padding: "12px 16px",
                  display: "flex", gap: 5, alignItems: "center",
                  background: t.assistant,
                }}>
                  <span className="dot" /><span className="dot" />
                  <span className="dot" />
                  <span style={{ color: t.faint, fontSize: 11.5,
                                 marginLeft: 8 }}>
                    executing tools…</span>
                </div>
              </div>)}
          </div>
        </div>

        {/* composer */}
        <div style={{
          borderTop: `1px solid ${t.border}`,
          padding: "14px 18px 18px",
          display: "flex", justifyContent: "center",
          background: t.bg,
        }}>
          <div style={{
            width: "min(780px, 100%)",
          }}>
            <div style={{
              background: t.panel,
              border: `1px solid ${t.border}`,
              borderRadius: 16, padding: "12px 14px",
              display: "flex", flexDirection: "column", gap: 10,
              transition: "border-color .2s, box-shadow .2s",
              animation: "glow 3s infinite",
            }}>
              <textarea value={draft} rows={2}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    active ? send() : newTask(draft.trim() || undefined);
                  }
                }}
                placeholder={active ?
                  "message CYR@…  (Enter ⏎ send · Shift+Enter newline)" :
                  "describe a task…"}
                style={{
                  background: "transparent", color: t.text,
                  border: "none", outline: "none",
                  resize: "none", fontSize: 13.5,
                  fontFamily: "inherit", maxHeight: 170,
                  lineHeight: 1.5,
                }} />
              <div style={{
                display: "flex", alignItems: "center", gap: 10,
              }}>
                <ModelPicker t={t}
                  value={taskModel ?? model}
                  onChange={(m) => {
                    setModel(m); setTaskModel(m);
                    if (active) api(`/api/tasks/${active}/model`, {
                      method: "POST",
                      body: JSON.stringify({ model: m }),
                    }).catch(() => { });
                  }}
                  openSettings={() => setSettings(true)} />
                <span style={{ fontSize: 10, color: t.faint }}>
                  local · loopback · full audit trail</span>
                <button onClick={() =>
                  active ? send() : newTask(draft.trim())}
                  disabled={busy || !draft.trim()} style={{
                  marginLeft: "auto",
                  background: busy || !draft.trim() ?
                    t.surface : t.grad,
                  color: busy || !draft.trim() ? t.faint : "#fff",
                  border: "none", borderRadius: 11,
                  padding: "8px 22px", fontSize: 13,
                  fontWeight: 700,
                  cursor: busy || !draft.trim() ?
                    "default" : "pointer",
                  transition: "all .2s",
                }}>{busy ? "…" : "send ⏎"}</button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {settings && (
        <SettingsModal t={t} close={() => setSettings(false)} />)}
    </div>);
}
