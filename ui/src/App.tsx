import React, { useEffect, useRef, useState } from "react";

/* CYR@ - local AI operating environment.
   Neutral professional design; green is semantic only.
   Truth-first: every capability/status comes from the
   backend's authoritative registry. */

const API = "http://127.0.0.1:8765";

async function api<T>(p: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + p, {
    headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 240)}`);
  return r.json() as Promise<T>;
}

type T = {
  bg: string; side: string; panel: string; surface: string;
  border: string; text: string; dim: string; faint: string;
  accent: string; ok: string; warn: string; bad: string;
  input: string; user: string; assistant: string;
};
const themes = {
  dark: {
    bg: "#0f0f11", side: "#131316", panel: "#17171a",
    surface: "#1d1d21", border: "#26262b",
    text: "#dcdce0", dim: "#8f8f96", faint: "#5c5c64",
    accent: "#8ab4d8", ok: "#5fb26a", warn: "#d8b45e",
    bad: "#d87a6a", input: "#1d1d21",
    user: "#232730", assistant: "#15151a",
  },
  light: {
    bg: "#f4f4f5", side: "#ebebee", panel: "#ffffff",
    surface: "#f0f0f2", border: "#d9d9de",
    text: "#1c1c20", dim: "#5f5f68", faint: "#9a9aa2",
    accent: "#3572a5", ok: "#2c8a3f", warn: "#9a6b00",
    bad: "#b3261e", input: "#ffffff",
    user: "#dfe8f5", assistant: "#f7f7f9",
  },
};

type TaskRec = { task_id: string; objective: string; state: string;
  model?: { provider: string; model_id: string } | null };
type Act = {
  type: string; [k: string]: unknown;
  exit_code?: number | null; output?: string; branch?: string;
  changes?: { path: string; index: string; worktree: string }[];
  title?: string; text_head?: string; disposition?: string;
  target?: string; capability?: string; reason?: string;
  files?: number; dirs?: number;
};
type Msg = { role: "user" | "assistant"; content: string;
  ts?: string; mode?: string; model?: string | null;
  activity?: Act[] };
type ModelPick = { provider: string; model_id: string } | null;
type ProviderRec = { name: string; base_url: string;
  has_key: boolean; models: string[]; label?: string;
  model_info?: Record<string, any> };
type CapRec = { capability: string; implementation: string;
  available: boolean; authorization: string; note: string };

const NAV = ["Home", "Tasks", "Research", "Tools", "Agents",
  "Memory", "Settings", "Diagnostics"] as const;
type Nav = typeof NAV[number];

/* ---------------------------------------------- error boundary */

class Boundary extends React.Component<
  { t: T; children: React.ReactNode },
  { err: string | null }> {
  constructor(props: any) {
    super(props);
    this.state = { err: null };
  }
  static getDerivedStateFromError(e: any) {
    return { err: String(e) };
  }
  render() {
    if (this.state.err) {
      return (
        <div style={{
          padding: 20, color: this.props.t.dim,
          fontSize: 13,
        }}>
          <b style={{ color: this.props.t.bad }}>
            view error</b><br />
          {this.state.err.slice(0, 300)}<br />
          <button onClick={() =>
            this.setState({ err: null })}
            style={{
              marginTop: 10, padding: "6px 14px",
              background: this.props.t.surface,
              color: this.props.t.text,
              border: `1px solid ${
                this.props.t.border}`,
              borderRadius: 6, cursor: "pointer",
            }}>retry</button>
        </div>);
    }
    return this.props.children;
  }
}

function Empty({ t, what }: { t: T; what: string }) {
  return (
    <div style={{
      padding: "26px 8px", textAlign: "center",
      color: t.faint, fontSize: 12.5,
    }}>
      {what}</div>);
}

/* ---------------------------------------------- mark */

function Mark({ size = 26 }: { size?: number }) {
  return (
    <div style={{
      width: size, height: size, borderRadius: 6,
      background: "#23262e", border: "1px solid #33363f",
      display: "flex", alignItems: "center",
      justifyContent: "center", flexShrink: 0,
    }}>
      <svg width={size * 0.6} height={size * 0.6}
        viewBox="0 0 24 24" fill="none">
        <path d="M19 12a7 7 0 1 1-2.05-4.95"
          stroke="#dcdce0" strokeWidth="2.4"
          strokeLinecap="round" />
        <circle cx="12" cy="12" r="2.4" fill="#8ab4d8" />
      </svg>
    </div>);
}

/* ---------------------------------------------- md */

function Md({ text, t }: { text: string; t: T }) {
  const nodes: React.ReactNode[] = [];
  let k = 0;
  text.split(/```/).forEach((seg, i) => {
    if (i % 2 === 1) {
      const nl = seg.indexOf("\n");
      nodes.push(<pre key={k++} style={{
        background: t.surface, borderRadius: 6,
        border: `1px solid ${t.border}`,
        padding: "8px 10px", fontSize: 12,
        fontFamily: "'Cascadia Code', monospace",
        overflowX: "auto", margin: "6px 0",
      }}>{nl >= 0 ? seg.slice(nl + 1) : seg}</pre>);
    } else {
      seg.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).forEach((c) => {
        if (!c) return;
        if (c.startsWith("**")) {
          nodes.push(<strong key={k++}>{c.slice(2, -2)}</strong>);
        } else if (c.length > 2 && c.startsWith("`")) {
          nodes.push(<code key={k++} style={{
            background: t.surface, borderRadius: 4,
            padding: "1px 5px", fontSize: 12,
            fontFamily: "'Cascadia Code', monospace",
          }}>{c.slice(1, -1)}</code>);
        } else nodes.push(<span key={k++}>{c}</span>);
      });
    }
  });
  return <div style={{ lineHeight: 1.6 }}>{nodes}</div>;
}

/* ---------------------------------------------- cards */

function Card({ a, t, onGranted }: {
  a: Act; t: T; onGranted: () => void }) {
  const base: React.CSSProperties = {
    background: t.surface, border: `1px solid ${t.border}`,
    borderRadius: 8, padding: "8px 10px", margin: "4px 0",
    fontSize: 12, animation: "slideUp .18s ease",
  };
  const head: React.CSSProperties = {
    fontSize: 10, textTransform: "uppercase",
    letterSpacing: 1, color: t.dim, fontWeight: 600,
    marginBottom: 4,
  };
  if (a.type === "terminal") {
    return (
      <div style={base}>
        <div style={head}>terminal
          {a.exit_code != null && (
            <span style={{
              color: a.exit_code === 0 ? t.ok : t.bad,
              marginLeft: 8,
            }}>exit {a.exit_code}</span>)}
        </div>
        <pre style={{ margin: 0, fontSize: 11.5,
          fontFamily: "'Cascadia Code', monospace",
          whiteSpace: "pre-wrap", maxHeight: 200,
          overflowY: "auto", color: t.text }}>
          {(a.output ?? "").trim() || "(no output)"}</pre>
      </div>);
  }
  if (a.type === "git_status") {
    return (
      <div style={base}>
        <div style={head}>git · {a.branch}</div>
        {(a.changes ?? []).length === 0 ?
          <span style={{ color: t.faint }}>clean</span> :
          (a.changes ?? []).slice(0, 8).map((c: any, i) => (
            <div key={i} style={{
              fontFamily: "'Cascadia Code', monospace",
              fontSize: 11.5, color: t.dim }}>
              <span style={{ color: t.warn }}>
                {c.index}{c.worktree} </span>{c.path}</div>))}
      </div>);
  }
  if (a.type === "research") {
    return (
      <div style={base}>
        <div style={head}>research · {a.target}</div>
        <span style={{
          fontWeight: 600,
          color: a.disposition === "SUPPORTED" ?
            t.ok : t.warn }}>
          {a.disposition}</span>
        <span style={{ color: t.faint, marginLeft: 6,
                       fontSize: 11 }}>
          controls + reproduction gates</span>
      </div>);
  }
  if (a.type === "permission_request") {
    return (
      <div style={{ ...base, borderColor: t.warn }}>
        <div style={{ ...head, color: t.warn }}>
          authorization required</div>
        <div style={{ marginBottom: 6 }}>
          <b>{a.capability}</b>
          <span style={{ color: t.dim }}> — {a.reason}</span>
        </div>
        <button style={{
          fontSize: 11, fontWeight: 600, padding: "4px 12px",
          cursor: "pointer", border: "none",
          borderRadius: 5, background: t.accent,
          color: "#0f0f11",
        }} onClick={async () => {
          await api("/api/permissions/grant", {
            method: "POST",
            body: JSON.stringify({
              capability: a.capability,
              mode: "allow_session" }) });
          onGranted();
        }}>Grant {a.capability}</button>
      </div>);
  }
  if (a.type === "error") {
    return (
      <div style={{ ...base, borderColor: t.bad }}>
        <div style={{ ...head, color: t.bad }}>error</div>
        <div>{String(a.detail)}</div></div>);
  }
  if (a.type === "workspace") {
    return (
      <div style={base}>
        <div style={head}>workspace</div>
        <span style={{ color: t.dim }}>{a.files} files
          · {a.dirs} directories</span>
      </div>);
  }
  if (a.type === "browser") {
    return (
      <div style={base}>
        <div style={head}>browser</div>
        <div style={{ color: t.accent, fontWeight: 600 }}>
          {a.title}</div>
        <div style={{ color: t.faint, fontSize: 11 }}>
          {(a.text_head ?? "").slice(0, 160)}…</div>
      </div>);
  }
  return null;
}

/* ---------------------------------------------- model picker */

function ModelPicker({ t, value, onChange, manage }: {
  t: T; value: ModelPick;
  onChange: (m: ModelPick) => void; manage: () => void }) {
  const [providers, setProviders] = useState<ProviderRec[]>([]);
  const [info, setInfo] = useState<Record<string, any>>({});
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const load = async () => {
    try {
      const m = await api<any>("/api/models/list");
      setProviders(m.providers);
      const map: Record<string, any> = {};
      m.providers.forEach((p: any) =>
        { map[p.name] = p.model_info ?? {}; });
      setInfo(map);
    } catch { }
  };
  useEffect(() => { if (open) { setFilter(""); load(); } },
    [open]);
  const disp = (p: string, m: string) =>
    info[p]?.[m]?.name && info[p][m].name !== m ?
    info[p][m].name : m;
  const total = providers.reduce((a, p) =>
    a + p.models.length, 0);
  return (
    <div style={{ position: "relative" }}>
      <button onClick={() => setOpen(!open)} style={{
        background: t.surface, color: value ? t.text : t.dim,
        border: `1px solid ${t.border}`, borderRadius: 6,
        padding: "4px 10px", fontSize: 11.5,
        cursor: "pointer", whiteSpace: "nowrap",
        maxWidth: 220, overflow: "hidden",
        textOverflow: "ellipsis",
      }}>◈ {value ? disp(value.provider, value.model_id)
        : "LOCAL"} ▾</button>
      {open && (<>
        <div onClick={() => setOpen(false)}
          style={{ position: "fixed", inset: 0,
                   zIndex: 39 }} />
        <div className="anim-in" style={{
          position: "absolute", bottom: "115%", left: 0,
          background: t.panel, borderRadius: 8,
          border: `1px solid ${t.border}`,
          width: 300, zIndex: 40, overflow: "hidden",
        }}>
          {total > 15 && (
            <input value={filter} autoFocus
              placeholder={`filter ${total} models…`}
              onChange={(e) => setFilter(e.target.value)}
              style={{ width: "100%", boxSizing: "border-box",
                background: t.surface, color: t.text,
                border: "none",
                borderBottom: `1px solid ${t.border}`,
                padding: "8px 12px", fontSize: 12 }} />)}
          <div style={{ maxHeight: 260, overflowY: "auto" }}>
            <div onClick={() => { onChange(null);
              setOpen(false); }} style={{
              padding: "6px 12px", fontSize: 12,
              cursor: "pointer",
              color: value === null ? t.accent : t.text }}>
              LOCAL <span style={{ color: t.faint }}>
                deterministic</span></div>
            {providers.map((p) => {
              const f = filter.toLowerCase();
              const models = f ? p.models.filter((m) =>
                m.toLowerCase().includes(f) ||
                disp(p.name, m).toLowerCase().includes(f))
                : p.models;
              if (f && !models.length) return null;
              return (
                <div key={p.name}>
                  <div style={{
                    padding: "5px 12px 2px", fontSize: 9.5,
                    color: t.faint, textTransform: "uppercase",
                    letterSpacing: 1, fontWeight: 700,
                  }}>{p.label ?? p.name} ({p.models.length})</div>
                  {models.slice(0, 40).map((m) => (
                    <div key={m} onClick={() => {
                      onChange({ provider: p.name, model_id: m });
                      setOpen(false); }} style={{
                      padding: "4px 14px", fontSize: 12,
                      cursor: "pointer",
                      color: value?.model_id === m &&
                        value?.provider === p.name ?
                        t.accent : t.text }}>
                      {disp(p.name, m)}</div>))}
                  {models.length > 40 && (
                    <div style={{ padding: "3px 14px 5px",
                      fontSize: 10, color: t.faint }}>
                      +{models.length - 40} more</div>)}
                </div>);
            })}
            <div onClick={() => { manage(); setOpen(false); }}
              style={{ padding: "7px 12px", fontSize: 12,
                cursor: "pointer", color: t.dim,
                borderTop: `1px solid ${t.border}` }}>
              Manage providers…</div>
          </div>
        </div>
      </>)}
    </div>);
}

/* ---------------------------------------------- reinitialize */

function ReinitPanel({ t, onDone }: {
  t: T; onDone: () => void }) {
  const [model, setModel] = useState<ModelPick>(null);
  const [session, setSession] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [manifest, setManifest] = useState<any>(null);
  const [selected, setSelected] =
    useState<Record<string, boolean>>({});
  const REPOS = ["veritas", "hydra", "seek", "cider",
    "frontier", "cyr"];

  useEffect(() => {
    api<any>("/api/reinitialize/manifest")
      .then(setManifest).catch(() => { });
  }, []);

  const repoOn = (r: string) => selected[r] !== false;

  const start = async () => {
    setRunning(true);
    try {
      const out = await api<any>(
        "/api/reinitialize/start", {
        method: "POST",
        body: JSON.stringify({
          model: model ?? undefined,
          repos: REPOS.filter(repoOn),
        }),
      });
      setSession(out);
    } catch (e) {
      setSession({ state: "FAILED", error: String(e) });
    }
    setRunning(false);
    onDone();
  };

  const line = (e: any, i: number) => (
    <div key={i} style={{
      display: "flex", gap: 8, fontSize: 12,
      color: e.kind === "error" ? t.bad :
        e.kind === "warn" ? t.warn :
        e.kind === "ok" ? t.ok : t.dim,
      animation: "slideUp .18s ease",
    }}>
      <span>{e.kind === "error" ? "✕" :
        e.kind === "warn" ? "⚠" :
        e.kind === "ok" ? "✓" : "→"}</span>
      <span>{e.text}</span>
    </div>);

  return (
    <div style={{
      border: `1px solid ${t.border}`, borderRadius: 10,
      padding: 16, background: t.panel,
    }}>
      <div style={{ fontSize: 13.5, fontWeight: 700,
                    marginBottom: 4 }}>
        Reinitialize</div>
      <div style={{ fontSize: 12, color: t.dim,
                    marginBottom: 14 }}>
        Start a fresh AI initialization session and check the
        selected research repositories for updates. Safe
        automatic integration; push stays disabled.</div>

      <div style={{ display: "flex", gap: 10,
                    alignItems: "center", marginBottom: 10 }}>
        <span style={{ fontSize: 11, color: t.dim,
                       width: 52 }}>Model</span>
        <ModelPicker t={t} value={model}
          onChange={setModel}
          manage={() => { }} />
      </div>
      <div style={{ display: "flex", gap: 10,
                    alignItems: "center", marginBottom: 10,
                    flexWrap: "wrap" }}>
        <span style={{ fontSize: 11, color: t.dim,
                       width: 52 }}>Repos</span>
        {REPOS.map((r) => (
          <button key={r} onClick={() =>
            setSelected({ ...selected,
              [r]: !repoOn(r) })} style={{
            fontSize: 11, padding: "3px 10px",
            borderRadius: 9, cursor: "pointer",
            border: `1px solid ${
              repoOn(r) ? t.accent : t.border}`,
            background: repoOn(r) ?
              t.surface : "transparent",
            color: repoOn(r) ? t.text : t.faint,
          }}>{repoOn(r) ? "☑" : "☐"} {r}</button>))}
        <button onClick={() =>
          setSelected({})} style={{
          fontSize: 10, color: t.faint,
          background: "transparent", border: "none",
          cursor: "pointer",
        }}>select all</button>
      </div>
      <div style={{ display: "flex", gap: 10,
                    alignItems: "center" }}>
        <span style={{ fontSize: 11, color: t.dim,
                       width: 52 }}>Policy</span>
        <span style={{ fontSize: 11, color: t.dim }}>
          safe automatic integration · push: never
          automatically</span>
      </div>
      <button onClick={start} disabled={running} style={{
        marginTop: 14, background: running ?
          t.surface : t.accent,
        color: running ? t.dim : "#0f0f11",
        border: "none", borderRadius: 7,
        padding: "8px 18px", fontSize: 12.5,
        fontWeight: 700,
        cursor: running ? "default" : "pointer",
      }}>{running ? "running…" :
        "Start Reinitialization"}</button>

      {session && (
        <div style={{
          marginTop: 16,
          borderTop: `1px solid ${t.border}`,
          paddingTop: 12,
        }}>
          <div style={{
            fontSize: 11, fontWeight: 700,
            marginBottom: 8,
            color: session.state === "COMPLETED" ? t.ok :
              session.state === "FAILED" ? t.bad : t.text,
          }}>session {session.state}</div>
          {(session.timeline ?? []).map(line)}
          {session.review_required?.length ? (
            <div style={{ marginTop: 8, fontSize: 12,
                          color: t.warn }}>
              SYNC REVIEW REQUIRED: {
                session.review_required.join(", ")}</div>) : null}
          {session.blocked?.length ? (
            <div style={{ marginTop: 4, fontSize: 12,
                          color: t.bad }}>
              BLOCKED (confidential): {
                session.blocked.join(", ")}</div>) : null}
          {session.applied?.length ? (
            <div style={{ marginTop: 4, fontSize: 12,
                          color: t.ok }}>
              applied: {session.applied.length}</div>) : null}
        </div>)}
    </div>);
}

/* ---------------------------------------------- diagnostics */

function Diagnostics({ t }: { t: T }) {
  const [d, setD] = useState<any>(null);
  useEffect(() => {
    api<any>("/api/diagnostics")
      .then(setD).catch(() => { });
  }, []);
  if (!d) return (
    <Empty t={t} what="loading diagnostics — is the backend online?" />);
  if (d.error) return (
    <Empty t={t} what={"diagnostics unavailable: " +
      String(d.error).slice(0, 200)} />);
  return (
    <div>
      <div style={{ display: "grid",
        gridTemplateColumns: "1fr 1fr", gap: 10,
        marginBottom: 16 }}>
        {[["version", d.version],
          ["backend", d.backend],
          ["runtime", d.desktop_runtime],
          ["journal",
           `chain ${d.journal.valid ? "VALID" :
             "TAMPERED"} (${d.journal.entries} entries)`],
          ["storage", `${d.storage.tasks} tasks · ` +
            `${d.storage.artifacts} artifacts`],
          ["providers", d.providers.configured.length ?
            d.providers.configured.join(", ") : "none"],
        ].map(([k, v], i) => (
          <div key={i} style={{
            background: t.panel, borderRadius: 8,
            border: `1px solid ${t.border}`,
            padding: "8px 12px",
          }}>
            <div style={{ fontSize: 10, color: t.faint,
              textTransform: "uppercase",
              letterSpacing: 1 }}>{k}</div>
            <div style={{ fontSize: 12.5, marginTop: 2 }}>
              {String(v)}</div>
          </div>))}
      </div>
      <div style={{ fontSize: 11, color: t.faint,
        textTransform: "uppercase", letterSpacing: 1,
        marginBottom: 6 }}>architecture</div>
      {(d.nodes ?? []).map((n: any, i: number) => (
        <div key={i} style={{
          display: "flex", gap: 10, alignItems: "center",
          padding: "5px 10px", fontSize: 12,
          borderBottom: `1px solid ${t.border}`,
        }}>
          <span className={
            n.status === "running" || n.status === "online" ?
              "" : "pulse"}
            style={{
            width: 6, height: 6, borderRadius: 6,
            background:
              n.status === "running" ||
                n.status === "online" ? t.ok : t.bad,
          }} />
          <b style={{ width: 150 }}>{n.node}</b>
          <span style={{ color: t.dim }}>{n.detail}</span>
        </div>))}
    </div>);
}

/* ---------------------------------------------- registry view */

function CapabilityList({ t }: { t: T }) {
  const [caps, setCaps] = useState<CapRec[] | null>(null);
  useEffect(() => {
    api<any>("/api/capabilities")
      .then((r) => setCaps(r.capabilities)).catch(() =>
        setCaps([]));
  }, []);
  if (caps === null) return (
    <Empty t={t} what="loading capability registry…" />);
  if (!caps.length) return (
    <Empty t={t} what="capability registry unavailable — is the backend online?" />);
  return (
    <div>
      {caps.map((c) => (
        <div key={c.capability} style={{
          display: "flex", gap: 10, fontSize: 12,
          padding: "5px 8px",
          borderBottom: `1px solid ${t.border}`,
          alignItems: "center",
        }}>
          <span style={{
            width: 7, height: 7, borderRadius: 7,
            background: c.available ?
              (c.authorization === "granted" ? t.ok : t.warn) :
              t.bad, flexShrink: 0,
          }} />
          <b style={{ width: 170 }}>{c.capability}</b>
          <span style={{ color: c.implementation ===
            "IMPLEMENTED" ? t.dim : t.warn,
            width: 88 }}>{c.implementation}</span>
          <span style={{ color: t.faint, flex: 1 }}>
            {c.note}</span>
        </div>))}
    </div>);
}

/* ---------------------------------------------- settings */

function Settings({ t }: { t: T }) {
  const [tab, setTab] = useState("Models");
  const [providers, setProviders] = useState<ProviderRec[]>([]);
  const [bindings, setBindings] = useState<Record<string, any>>({});
  const [msg, setMsg] = useState("");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("https://");
  const [key, setKey] = useState("");
  const load = async () => {
    try {
      const m = await api<any>("/api/models/list");
      setProviders(m.providers);
      setBindings(m.role_bindings);
    } catch { }
  };
  useEffect(() => { load(); }, []);
  const inp = (v: string, s: (x: string) => void,
    ph: string, pw = false) => (
    <input value={v} placeholder={ph}
      type={pw ? "password" : "text"}
      onChange={(e) => s(e.target.value)} style={{
        flex: 1, minWidth: 100, background: t.surface,
        color: t.text, borderRadius: 6,
        border: `1px solid ${t.border}`,
        padding: "7px 10px", fontSize: 12 }} />);
  return (
    <div>
      <div style={{ display: "flex", gap: 4, marginBottom: 14,
                    flexWrap: "wrap" }}>
        {["Models", "Permissions", "Appearance"].map((x) => (
          <button key={x} onClick={() => setTab(x)} style={{
            background: tab === x ? t.surface : "transparent",
            color: tab === x ? t.text : t.dim,
            border: `1px solid ${tab === x ?
              t.border : "transparent"}`,
            borderRadius: 6, padding: "5px 12px",
            fontSize: 12, cursor: "pointer",
          }}>{x}</button>))}
      </div>
      {tab === "Models" && (<>
        <div style={{ fontSize: 12, color: t.dim,
                      marginBottom: 8 }}>
          Providers auto-discovered from your environment and
          opencode config (keys in the Windows vault —
          never files).</div>
        {providers.map((p) => (
          <div key={p.name} style={{
            display: "flex", gap: 10, alignItems: "center",
            fontSize: 12.5, padding: "7px 10px",
            marginBottom: 4, background: t.panel,
            border: `1px solid ${t.border}`,
            borderRadius: 8,
          }}>
            <b>{p.label ?? p.name}</b>
            <span style={{ color: t.faint, flex: 1,
              overflow: "hidden",
              textOverflow: "ellipsis" }}>
              {p.base_url}</span>
            <span style={{ color: p.has_key ? t.ok : t.bad,
                           fontSize: 11 }}>
              {p.has_key ? "key ✓" : "no key"}</span>
            <span style={{ color: t.dim, fontSize: 11 }}>
              {p.models.length} models</span>
          </div>))}
        <div style={{ marginTop: 12, display: "flex",
                      gap: 8, flexWrap: "wrap" }}>
          {inp(name, setName, "provider name")}
          {inp(url, setUrl, "https://…/v1")}
          {inp(key, setKey, "API key → vault", true)}
          <button onClick={async () => {
            try {
              await api("/api/providers/with_key", {
                method: "POST",
                body: JSON.stringify({
                  spec: { name, base_url: url,
                    api_format: "openai" },
                  api_key: key, models: [] }) });
              setMsg(`${name} added`);
              setName(""); setUrl("https://"); setKey("");
              load();
            } catch (e) { setMsg(String(e)); }
          }} style={{
            background: t.accent, color: "#0f0f11",
            border: "none", borderRadius: 6,
            padding: "7px 16px", fontSize: 12,
            fontWeight: 600, cursor: "pointer",
          }}>Add</button>
        </div>
        {msg ? <div style={{ fontSize: 11.5, color: t.dim,
                             marginTop: 8 }}>{msg}</div> : null}
        <div style={{ fontSize: 11, color: t.faint,
                      textTransform: "uppercase",
                      letterSpacing: 1, margin: "16px 0 8px" }}>
          role bindings</div>
        <div style={{ display: "grid",
                      gridTemplateColumns: "1fr 1fr", gap: 4 }}>
          {Object.entries(bindings).map(([role, b]: any) => (
            <div key={role} style={{ display: "flex",
              alignItems: "center", gap: 8, fontSize: 11.5 }}>
              <span style={{ width: 128, color: t.dim }}>
                {role}</span>
              <span style={{ color: b.provider ?
                t.text : t.faint }}>
                {b.provider === "LOCAL (unconfigured)" ?
                  "LOCAL" :
                  `${b.provider}/${b.model_id ?? ""}`}</span>
            </div>))}
        </div>
      </>)}
      {tab === "Permissions" && (<>
        <div style={{ fontSize: 12, color: t.dim,
                      marginBottom: 8 }}>
          Authoritative capability registry — implementation
          status, grant state, and honest availability.
          High-risk operations (push, delete, computer
          control) always confirm per-operation.</div>
        <CapabilityList t={t} />
      </>)}
      {tab === "Appearance" && (<>
        <div style={{ fontSize: 12, color: t.dim }}>
          Theme follows the system shell toggle in the
          sidebar. Green is used only for verified/success
          semantics; everything else stays neutral.</div>
      </>)}
    </div>);
}

/* ---------------------------------------------- app */

export default function App() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const t = themes[theme];
  const [nav, setNav] = useState<Nav>("Home");
  const [tasks, setTasks] = useState<TaskRec[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [model, setModel] = useState<ModelPick>(null);
  const [taskModel, setTaskModel] = useState<ModelPick>(null);
  const [busy, setBusy] = useState(false);
  const [conn, setConn] = useState(false);
  const [caps, setCaps] = useState<CapRec[]>([]);
  const [journal, setJournal] = useState<any[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const lastText = useRef("");

  const poll = async () => {
    try {
      await api<any>("/api/health");
      setConn(true);
      setTasks(await api<TaskRec[]>("/api/tasks"));
    } catch { setConn(false); }
  };
  useEffect(() => {
    poll();
    api<any>("/api/capabilities")
      .then((r) => setCaps(r.capabilities)).catch(() => { });
    const id = setInterval(poll, 2500);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (active) {
      api<{ messages: Msg[] }>(
        `/api/chat/${active}/messages`)
        .then((r) => setMessages(r.messages));
      api<any>(`/api/tasks/${active}`)
        .then((task) => setTaskModel(task.model ?? null));
      api<any>("/api/journal?limit=50")
        .then((j) => setJournal(j.slice().reverse()));
    } else setMessages([]);
  }, [active]);

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
      await api<{ assistant: Msg }>("/api/chat", {
        method: "POST",
        body: JSON.stringify({ task_id: tid, text,
          model: effective,
          set_task_model: !!effective }),
      });
      const r = await api<{ messages: Msg[] }>(
        `/api/chat/${tid}/messages`);
      setMessages(r.messages);
      poll();
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant",
        content: `error: ${String(e)}` }]);
    }
    setBusy(false);
  };

  const newTask = async (text?: string) => {
    try {
      const rec = await api<TaskRec>("/api/tasks", {
        method: "POST",
        body: JSON.stringify({
          objective: text?.slice(0, 60) ??
            "New conversation" }),
      });
      setActive(rec.task_id);
      setTasks((l) => [...l, rec]);
      setNav("Home");
      if (text) send(text, rec.task_id);
    } catch { }
  };

  const cap = (name: string) =>
    caps.find((c) => c.capability === name);

  /* connecting splash */
  if (!conn && !tasks.length) {
    return (
      <div style={{
        height: "100vh", display: "flex",
        flexDirection: "column", alignItems: "center",
        justifyContent: "center", gap: 14, background: t.bg,
      }}>
        <Mark size={56} />
        <div style={{ fontSize: 19, fontWeight: 800,
                      letterSpacing: 2 }}>CYR@</div>
        <div style={{ display: "flex", gap: 8,
                      alignItems: "center" }}>
          <span className="spin" style={{
            width: 14, height: 14, borderRadius: 14,
            border: `2px solid ${t.border}`,
            borderTopColor: t.accent }} />
          <span style={{ color: t.dim, fontSize: 13 }}>
            starting local backend… (first launch ~20s)</span>
        </div>
      </div>);
  }

  const toolCount = caps.filter((c) =>
    c.implementation === "IMPLEMENTED").length;

  return (
    <div style={{ display: "flex", height: "100vh",
                  background: t.bg, color: t.text,
                  overflow: "hidden",
      fontFamily: "'Segoe UI', system-ui, sans-serif" }}>
      {/* rail */}
      <div style={{
        width: 56, background: t.side,
        borderRight: `1px solid ${t.border}`,
        display: "flex", flexDirection: "column",
        alignItems: "center", padding: "10px 0",
        gap: 2,
      }}>
        <div style={{ marginBottom: 10 }}>
          <Mark size={30} /></div>
        {NAV.map((n) => (
          <button key={n} onClick={() => setNav(n)} title={n}
            style={{
            width: 38, height: 38, borderRadius: 8,
            background: nav === n ? t.surface :
              "transparent",
            border: "none", cursor: "pointer",
            fontSize: nav === n ? 15 : 14,
            color: nav === n ? t.text : t.dim,
            transition: "background .12s",
          }}>{n === "Home" ? "⌂" :
            n === "Tasks" ? "≡" :
            n === "Research" ? "⬡" :
            n === "Tools" ? "⚒" :
            n === "Agents" ? "◈" :
            n === "Memory" ? "▤" :
            n === "Settings" ? "⚙" : "OSC"}</button>))}
        <div style={{ marginTop: "auto" }}>
          <button onClick={() =>
            setTheme(theme === "dark" ? "light" : "dark")}
            style={{
            width: 38, height: 38, borderRadius: 8,
            background: "transparent", border: "none",
            cursor: "pointer", fontSize: 13,
            color: t.dim,
          }}>{theme === "dark" ? "☀" : "☾"}</button>
        </div>
      </div>

      {/* context sidebar */}
      {nav === "Home" && (
        <div style={{
          width: 210, background: t.side,
          borderRight: `1px solid ${t.border}`,
          display: "flex", flexDirection: "column",
        }}>
          <div style={{ padding: 12 }}>
            <button onClick={() => { setActive(null);
              setDraft(""); }} style={{
              width: "100%", background: t.accent,
              color: "#0f0f11", border: "none",
              borderRadius: 7, padding: "9px 0",
              fontSize: 12.5, fontWeight: 700,
              cursor: "pointer",
            }}>+ New task</button>
          </div>
          <div style={{ flex: 1, overflowY: "auto",
                        padding: "0 8px" }}>
            {tasks.slice(-30).reverse().map((task) => (
              <div key={task.task_id} onClick={() => {
                setActive(task.task_id); setNav("Home");
              }} style={{
                padding: "7px 9px", borderRadius: 7,
                cursor: "pointer", marginBottom: 1,
                fontSize: 12,
                background: active === task.task_id ?
                  t.panel : "transparent",
              }}>
                <div style={{
                  whiteSpace: "nowrap", overflow: "hidden",
                  textOverflow: "ellipsis",
                }}>{task.objective}</div>
                <div style={{ fontSize: 10, color: t.faint }}>
                  {task.state}</div>
              </div>))}
          </div>
        </div>)}

      {/* main */}
      <div style={{ flex: 1, display: "flex",
                    flexDirection: "column", minWidth: 0 }}>
        {/* header */}
        <div style={{
          padding: "10px 16px",
          borderBottom: `1px solid ${t.border}`,
          display: "flex", alignItems: "center", gap: 12,
          fontSize: 12,
        }}>
          <b style={{ fontSize: 13 }}>{nav}</b>
          <span style={{ color: conn ? t.ok : t.warn,
                         fontSize: 11 }}>
            ● {conn ? "backend online" : "offline"}</span>
          <span style={{ color: t.faint, fontSize: 11 }}>
            {toolCount} capabilities implemented</span>
          <span style={{ marginLeft: "auto",
                         color: t.faint, fontSize: 11 }}>
            v1.3.0 · loopback · audit trail on</span>
        </div>

        <div style={{ flex: 1, overflowY: "auto",
                      display: "flex",
                      justifyContent: "center" }}>
          <div style={{
            width: "min(760px, 100%)",
            padding: "18px 16px 8px",
          }}>
            {/* ---------------- HOME = chat */}
            {nav === "Home" && (<>
              {!active && !busy && (
                <div style={{ textAlign: "center",
                              marginTop: "8vh" }}>
                  <div style={{
                    display: "flex",
                    justifyContent: "center",
                    marginBottom: 14 }}>
                    <Mark size={52} /></div>
                  <div style={{ fontSize: 26,
                                fontWeight: 800,
                                letterSpacing: 2 }}>CYR@</div>
                  <div style={{ marginTop: 8, color: t.dim,
                    fontSize: 13, lineHeight: 1.6 }}>
                    A local AI operating environment with real
                    tools and a research kernel (VERITAS +
                    CIDER/SEEK/HYDRA/Frontier).</div>
                  <div style={{ display: "flex", gap: 6,
                    justifyContent: "center",
                    flexWrap: "wrap", marginTop: 18 }}>
                    {["run print('hello')", "show git status",
                      "research the WebKit target"]
                      .map((ex, i) => (
                        <button key={i} onClick={() =>
                          newTask(ex)}
                          className="anim-in"
                          style={{
                            animationDelay: `${i * 0.06}s`,
                            background: t.panel,
                            border: `1px solid ${t.border}`,
                            borderRadius: 16, color: t.dim,
                            padding: "6px 14px",
                            fontSize: 12, cursor: "pointer",
                          }}>{ex}</button>))}
                  </div>
                </div>)}
              {messages.map((m, i) => (
                <div key={i} className="anim-in" style={{
                  marginTop: 12, display: "flex", gap: 9,
                  flexDirection:
                    m.role === "user" ?
                      "row-reverse" : "row",
                }}>
                  <div style={{
                    width: 24, height: 24, borderRadius: 6,
                    flexShrink: 0,
                    display: "flex", alignItems: "center",
                    justifyContent: "center",
                    fontSize: 9.5, fontWeight: 700,
                    background: m.role === "user" ?
                      t.user : "#23262e",
                    color: m.role === "user" ?
                      t.text : "#dcdce0",
                  }}>{m.role === "user" ? "you" : "◈"}</div>
                  <div style={{
                    maxWidth: m.role === "user" ?
                      "72%" : "100%",
                    background: m.role === "user" ?
                      t.user : t.assistant,
                    border: `1px solid ${
                      m.role === "user" ?
                        "transparent" : t.border}`,
                    borderRadius: 10, padding: "9px 13px",
                    fontSize: 13.5,
                  }}>
                    {m.role === "assistant" &&
                      (m.activity ?? []).map((a, j) => (
                        <Card key={j} a={a} t={t}
                          onGranted={() =>
                            send(lastText.current)} />))}
                    <Md text={m.content} t={t} />
                  </div>
                </div>))}
              {busy && (
                <div className="anim-in" style={{
                  display: "flex", gap: 9, marginTop: 12 }}>
                  <div style={{
                    width: 24, height: 24, borderRadius: 6,
                    background: "#23262e",
                    display: "flex", alignItems: "center",
                    justifyContent: "center",
                    color: "#dcdce0", fontSize: 11 }}>◈</div>
                  <div style={{
                    border: `1px solid ${t.border}`,
                    borderRadius: 10, padding: "10px 14px",
                    background: t.assistant, color: t.faint,
                    fontSize: 12 }}>
                    <span className="pulse">executing tools…</span>
                  </div>
                </div>)}
            </>)}

            {nav === "Tasks" && (
              tasks.slice(-30).reverse().map((task) => (
                <div key={task.task_id} style={{
                  padding: "9px 12px", marginBottom: 6,
                  background: t.panel, borderRadius: 8,
                  border: `1px solid ${t.border}`,
                  display: "flex", gap: 10,
                  alignItems: "center", fontSize: 12.5,
                }}>
                  <span style={{
                    width: 7, height: 7, borderRadius: 7,
                    background: task.state === "running" ?
                      t.ok : task.state === "paused" ?
                      t.warn : t.faint,
                  }} />
                  <b>{task.task_id}</b>
                  <span style={{ flex: 1, color: t.dim }}>
                    {task.objective}</span>
                  <span style={{ color: t.faint }}>
                    {task.state}</span>
                  {["pause", "resume", "stop"].map((op) => (
                    <button key={op} onClick={async () => {
                      await api(`/api/tasks/${
                        task.task_id}/${op}`, {
                        method: "POST", body: "{}",
                      }).catch(() => { });
                      poll();
                    }} style={{
                      fontSize: 10.5, padding: "2px 8px",
                      background: t.surface,
                      color: t.dim, cursor: "pointer",
                      border: `1px solid ${t.border}`,
                      borderRadius: 5,
                    }}>{op}</button>))}
                </div>)))}
            {nav === "Tasks" && !tasks.length ? (
              <Empty t={t} what="no tasks yet — start one from Home" />) : null}

            {nav === "Research" && (<>
              <ReinitPanel t={t} onDone={poll} />
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: 11, color: t.faint,
                  textTransform: "uppercase",
                  letterSpacing: 1, marginBottom: 6 }}>
                  research activity (journal)</div>
                {journal.length ? journal.map((e, i) => (
                  <div key={i} style={{
                    display: "flex", gap: 10, fontSize: 11.5,
                    padding: "3px 6px",
                    color: t.dim,
                  }}>
                    <span style={{ color: t.faint }}>
                      {e.ts?.slice(11, 19)}</span>
                    <span>{e.action}</span>
                  </div>)) : (
                  <Empty t={t} what="no research activity recorded yet — open a task or run Reinitialize" />)}
              </div>
            </>)}

            {nav === "Tools" && (<>
              <div style={{ fontSize: 12, color: t.dim,
                            marginBottom: 10 }}>
                Tool runtimes with real implementation
                status. Use chat to drive them.</div>
              {caps.length ?
                <CapabilityList t={t} /> :
                <Empty t={t} what="loading capability registry — is the backend online?" />}
            </>)}

            {nav === "Agents" && (<>
              <div style={{ fontSize: 12, color: t.dim,
                            marginBottom: 10 }}>
                Agent controls + capability truth. Agents run
                with stable run IDs and real pause/stop.</div>
              {caps.length ?
                <CapabilityList t={t} /> :
                <Empty t={t} what="loading capabilities…" />}
            </>)}

            {nav === "Memory" && <MemoryView t={t} />}

            {nav === "Settings" && (
              <Boundary t={t}>
                <Settings t={t} />
              </Boundary>)}

            {nav === "Diagnostics" && (
              <Boundary t={t}>
                <Diagnostics t={t} />
              </Boundary>)}
          </div>
        </div>

        {/* composer (Home only) */}
        {nav === "Home" && (
          <div style={{
            borderTop: `1px solid ${t.border}`,
            padding: "12px 16px 16px",
            display: "flex", justifyContent: "center",
            background: t.bg,
          }}>
            <div style={{ width: "min(760px, 100%)" }}>
              <div style={{
                background: t.panel,
                border: `1px solid ${t.border}`,
                borderRadius: 12, padding: "10px 12px",
                display: "flex", flexDirection: "column",
                gap: 8,
              }}>
                <textarea value={draft} rows={2}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey
                        && !busy) {
                      e.preventDefault();
                      active ? send() :
                        newTask(draft.trim() || undefined);
                    }
                  }}
                  placeholder={active ?
                    (busy ?
                      "steer the running session… (Enter to steer)" :
                      "message CYR@… (Enter send)") :
                    "describe a task…"}
                  style={{
                    background: "transparent", color: t.text,
                    border: "none", outline: "none",
                    resize: "none", fontSize: 13.5,
                    fontFamily: "inherit", maxHeight: 160,
                  }} />
                <div style={{ display: "flex",
                              alignItems: "center", gap: 8 }}>
                  <ModelPicker t={t}
                    value={taskModel ?? model}
                    onChange={(m) => {
                      setModel(m); setTaskModel(m);
                      if (active) api(
                        `/api/tasks/${active}/model`, {
                        method: "POST",
                        body: JSON.stringify({ model: m }),
                      }).catch(() => { });
                    }}
                    manage={() => setNav("Settings")} />
                  <span style={{ fontSize: 10,
                                 color: t.faint }}>
                    local · loopback · evidence-first</span>
                  {busy && active ? (<>
                    <button onClick={async () => {
                      if (!draft.trim()) return;
                      const r = await api<any>(
                        `/api/tasks/${active}/steer`, {
                        method: "POST",
                        body: JSON.stringify(
                          { text: draft.trim() }) });
                      setDraft("");
                    }} disabled={!draft.trim()} style={{
                      marginLeft: "auto",
                      background: t.surface,
                      color: t.text,
                      border: `1px solid ${t.border}`,
                      borderRadius: 8, padding: "7px 14px",
                      fontSize: 12, fontWeight: 600,
                      cursor: draft.trim() ?
                        "pointer" : "default",
                    }}>steer ⇪</button>
                    <button onClick={async () => {
                      await api(
                        `/api/tasks/${active}/abort`, {
                        method: "POST", body: "{}",
                      }).catch(() => { });
                      setBusy(false);
                    }} style={{
                      background: "#3a2528",
                      color: t.bad,
                      border: `1px solid ${t.bad}`,
                      borderRadius: 8, padding: "7px 14px",
                      fontSize: 12, fontWeight: 700,
                      cursor: "pointer",
                    }}>abort ⏹</button>
                  </>) : (<button onClick={() => active ? send() :
                    newTask(draft.trim())}
                    disabled={busy || !draft.trim()} style={{
                    marginLeft: "auto",
                    background: busy || !draft.trim() ?
                      t.surface : t.accent,
                    color: busy || !draft.trim() ?
                      t.faint : "#0f0f11",
                    border: "none", borderRadius: 8,
                    padding: "7px 18px", fontSize: 12.5,
                    fontWeight: 700,
                    cursor: busy || !draft.trim() ?
                      "default" : "pointer",
                  }}>{busy ? "…" : "send ⏎"}</button>)}
                </div>
              </div>
            </div>
          </div>)}
      </div>
    </div>);
}

/* ---------------------------------------------- memory view */

function MemoryView({ t }: { t: T }) {
  const [mem, setMem] = useState<any>(null);
  const [arts, setArts] = useState<any[]>([]);
  useEffect(() => {
    api<any>("/api/memory").then(setMem).catch(() => { });
    api<any>("/api/artifacts").then((a) =>
      setArts(Array.isArray(a) ? a : [])).catch(() => { });
  }, []);
  return (
    <div>
      <div style={{ fontSize: 12, color: t.dim,
                    marginBottom: 10 }}>
        Local persistent memory by kind + content-hashed
        artifacts. Secrets are redacted on write.</div>
      {mem && Object.keys(mem).length ? (
        <div style={{ display: "flex", gap: 8,
                      marginBottom: 14, flexWrap: "wrap" }}>
          {Object.entries(mem).map(([k, v]: any) => (
            <span key={k} style={{
              fontSize: 11.5, padding: "4px 12px",
              borderRadius: 8, background: t.panel,
              border: `1px solid ${t.border}`,
            }}>{k}: {v}</span>))}
        </div>) : (
        <Empty t={t} what="no memory recorded yet — chat,
          run tools, or do research to build memory" />)}
      {(arts ?? []).length ? arts.slice(-15).reverse()
        .map((a: any) => (
        <div key={a.artifact_id} style={{
          display: "flex", gap: 10, fontSize: 11.5,
          padding: "5px 8px",
          borderBottom: `1px solid ${t.border}`,
        }}>
          <span style={{ color: t.faint }}>
            {a.artifact_id}</span>
          <span>{a.type}</span>
          <span style={{ marginLeft: "auto",
                        color: t.faint }}>
            {a.sha256?.slice(0, 12)}</span>
        </div>)) : (
        <Empty t={t} what="no artifacts yet — tool runs and
          reports produce content-hashed artifacts" />)}
    </div>);
}
