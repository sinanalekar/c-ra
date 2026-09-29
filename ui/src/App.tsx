import React, { useEffect, useState } from "react";

/* VERITAS environment - vertical-slice dashboard.
   Codex-like research console: engines, targets, hypotheses,
   experiments, evidence, journal. All states are real API
   responses; unavailable engines display unavailable. */

type Engine = {
  name: string; version: string; available: boolean;
  capabilities: string[]; experiment_types: string[];
  risk_level: string;
};
type Target = { target_id: string; product: string;
                parent_category: string;
                coverage_state: string };
type JournalEntry = { ts: string; action: string;
                      [k: string]: unknown };
type Status = {
  engines: Engine[];
  providers: { roles: Record<string, { provider: string }> };
  authorization: { capabilities: Record<string, boolean> };
  coverage: { total_targets: number;
              untested_count: number };
  journal: { valid: boolean; entries: number };
};

const box: React.CSSProperties = {
  border: "1px solid #2a3140", borderRadius: 6,
  padding: "10px 12px", margin: 8, background: "#161b24",
};
const h: React.CSSProperties = {
  margin: "2px 0 6px", fontSize: 12, color: "#7f8ea3",
  textTransform: "uppercase", letterSpacing: 1,
};
const ok = { color: "#6fd08c" };
const bad = { color: "#e06c6c" };
const warn = { color: "#d8b64a" };

function dispositionColor(d: string) {
  if (d === "SUPPORTED" || d === "VALIDATED") return ok;
  if (d === "BLOCKED" || d === "REFUTED") return bad;
  return warn;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json() as Promise<T>;
}

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [targets, setTargets] = useState<Target[]>([]);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [research, setResearch] = useState<any>(null);
  const [log, setLog] = useState<string[]>([]);

  const refresh = async () => {
    try {
      const st = await api<Status>("/api/status");
      setStatus(st);
      const tg = await api<Target[]>("/api/targets/search",
        { method: "POST", body: JSON.stringify({ query: "" }) });
      setTargets(tg.slice(0, 25));
      const j = await api<JournalEntry[]>("/api/journal?limit=30");
      setJournal(j.slice().reverse());
      const rs = await api<any>("/api/research/status");
      setResearch(rs);
    } catch (e) {
      setLog((l) => [...l, `error: ${String(e)}`]);
    }
  };

  useEffect(() => { refresh(); }, []);

  const say = (m: string) => setLog((l) => [...l, m]);

  const runSlice = async () => {
    say("granting experimental_execution ...");
    await api("/api/authorization/grant", {
      method: "POST",
      body: JSON.stringify({
        capability: "experimental_execution" }) });
    say("registering hypothesis on T-authentication-face-id ...");
    const hyp = await api<{ hypothesis_id: string }>(
      "/api/hypotheses", { method: "POST", body: JSON.stringify({
        claim: "A session-state machine flaw violates its " +
               "auth invariant and CIDER's monitor detects it " +
               "with the repaired control staying clean",
        target_id: "T-authentication-face-id",
        engine: "cider",
        falsification: "the repaired control also trips the " +
                       "monitor, or the result is not reproducible",
        params: { experiment: "exp_invariant_session" } }) });
    say(`hypothesis ${hyp.hypothesis_id} registered; running ...`);
    try {
      const rec = await api<any>(
        `/api/hypotheses/${hyp.hypothesis_id}/run`, {
          method: "POST", body: JSON.stringify({ params: {} }) });
      say(`disposition: ${rec.disposition} | controls: ${
        rec.negative_controls_pass} | reproduced: ${
        rec.reproduced}`);
    } catch (e) {
      say(`run result: ${String(e)}`);
    }
    refresh();
  };

  if (!status) {
    return <div style={box}>
      <div style={h}>VERITAS environment</div>
      connecting to local backend (127.0.0.1:8765) ...
    </div>;
  }

  return (
    <div style={{ padding: 12, maxWidth: 1100, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "baseline",
                    gap: 10 }}>
        <div style={{ fontSize: 20, fontWeight: 700 }}>
          VERITAS <span style={{ color: "#7f8ea3" }}>
            environment</span></div>
        <div style={{ fontSize: 12, color: "#7f8ea3" }}>
          local-first autonomous security-research console
        </div>
        <div style={{ marginLeft: "auto", fontSize: 12 }}>
          journal {status.journal.entries} entries
          <span style={status.journal.valid ? ok : bad}>
            {status.journal.valid ? " VALID" : " TAMPERED"}
          </span>
        </div>
      </div>

      {/* status bar */}
      <div style={{ ...box, display: "flex", gap: 16,
                    fontSize: 12, color: "#7f8ea3" }}>
        <span>authorization: deny-by-default</span>
        <span>model: {Object.values(
          status.providers.roles)[0]?.provider ?? "LOCAL"}</span>
        <span>targets: {status.coverage.total_targets}
          {" "}({status.coverage.untested_count} untested)</span>
        <button onClick={refresh}
          style={{ marginLeft: "auto" }}>refresh</button>
        <button onClick={runSlice}>run vertical slice</button>
      </div>

      <div style={{ display: "grid",
                    gridTemplateColumns: "1fr 1fr" }}>
        {/* engines */}
        <div style={box}>
          <div style={h}>Engines</div>
          {status.engines.map((e) => (
            <div key={e.name} style={{
              display: "flex", gap: 8, fontSize: 13,
              padding: "3px 0" }}>
              <span style={{ fontWeight: 600 }}>{e.name}</span>
              <span style={e.available ? ok : bad}>
                {e.available ? "online" : "unavailable"}</span>
              <span style={{ color: "#7f8ea3" }}>
                v{e.version} · {e.experiment_types.length} exp
                types · risk {e.risk_level}</span>
            </div>
          ))}
        </div>

        {/* research state */}
        <div style={box}>
          <div style={h}>Hypotheses / Experiments</div>
          {(research?.hypotheses ?? []).map((x: any) => (
            <div key={x.id} style={{ fontSize: 13 }}>
              {x.id}
              <span style={dispositionColor(x.state)}>
                {" "}{x.state}</span>
              <span style={{ color: "#7f8ea3" }}>
                {" "}{x.claim.slice(0, 60)}...</span>
            </div>
          ))}
          {(research?.experiments ?? []).map((x: any) => (
            <div key={x.id} style={{ fontSize: 13 }}>
              {x.id}
              <span style={dispositionColor(x.disposition)}>
                {" "}{x.disposition}</span>
              <span style={{ color: "#7f8ea3" }}>
                {" "}via {x.engine}</span>
            </div>
          ))}
          {(!research ||
           (!research.hypotheses?.length &&
            !research.experiments?.length)) ? (
            <div style={{ color: "#7f8ea3", fontSize: 12 }}>
              no research yet - run the vertical slice
            </div>) : null}
        </div>

        {/* targets */}
        <div style={box}>
          <div style={h}>Targets (Apple universe, first 25)</div>
          {targets.map((t) => (
            <div key={t.target_id} style={{ fontSize: 12,
                                            display: "flex",
                                            gap: 8 }}>
              <span style={{ color: "#7f8ea3" }}>
                {t.parent_category}</span>
              <span>{t.product}</span>
              <span style={{
                marginLeft: "auto",
                ...(t.coverage_state === "untested" ? warn : ok) }}>
                {t.coverage_state}</span>
            </div>
          ))}
        </div>

        {/* journal */}
        <div style={box}>
          <div style={h}>Activity journal (newest first)</div>
          {journal.map((e, i) => (
            <div key={i} style={{ fontSize: 12,
                                  display: "flex", gap: 8 }}>
              <span style={{ color: "#7f8ea3" }}>
                {e.ts.slice(11, 19)}</span>
              <span>{e.action}</span>
              {"experiment_id" in e ? (
                <span style={{ color: "#7f8ea3" }}>
                  {String(e.experiment_id)}</span>) : null}
            </div>
          ))}
        </div>
      </div>

      {/* console log */}
      <div style={box}>
        <div style={h}>Console</div>
        {log.map((l, i) => (
          <div key={i} style={{ fontSize: 12 }}>{l}</div>))}
      </div>
    </div>
  );
}
