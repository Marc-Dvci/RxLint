import { useEffect, useMemo, useState } from "react";
import { api, type RulePackView, type RuleView } from "../api";
import { IRefresh } from "../icons";

const GROUPS: { title: string; match: (r: RuleView) => boolean }[] = [
  { title: "Scope", match: (r) => r.type.startsWith("scope_") },
  { title: "Product reconciliation", match: (r) => r.id.startsWith("RX-PRODUCT") },
  { title: "Dose, interval and maximum (WHO AWaRe Table 50.1)", match: (r) => ["weight_dose", "max_daily_dose", "frequency_allowed"].includes(r.type) },
  { title: "Duration by indication (WHO AWaRe infection chapters)", match: (r) => ["duration_allowed", "indication_option"].includes(r.type) },
  { title: "Allergy, age and duplicates (FDA labels)", match: (r) => r.id.startsWith("RX-ALLERGY") || r.id.startsWith("RX-DUP") || r.id.startsWith("RX-SXT") },
  { title: "Interactions (complete encoded set)", match: (r) => r.type === "interaction" },
];

function quotes(q: string | string[] | null): string[] {
  if (!q) return [];
  return Array.isArray(q) ? q : [q];
}

function loc(l: unknown): string {
  if (!l) return "";
  if (typeof l === "string") return l;
  const o = l as Record<string, unknown>;
  return [o.table && `Table ${o.table}`, o.row, o.printed_page && `p. ${o.printed_page}`, o.section].filter(Boolean).join(" · ");
}

function Drift() {
  const [d, setD] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.driftLast().then(setD).catch(() => undefined); }, []);
  const run = async () => { setBusy(true); try { setD(await api.drift()); } finally { setBusy(false); } };
  const findings = (d?.findings as { title: string; date: string; affected_rules: string[]; url: string; runtime_effect: string; action: string }[]) ?? [];
  const status = String(d?.status ?? "NOT_RUN");
  const tone = status === "RULE_SOURCE_DRIFT" ? "t-live" : status === "NO_DRIFT_DETECTED" ? "t-pass" : status === "NOT_RUN" ? "t-note" : "t-cannot";
  return (
    <div className="card live-card">
      <div className="card-head">
        <div>
          <h3>Rule-source drift</h3>
          <div className="sub">Tavily reads the WHO publication page and searches who.int for newer guidance on the topics the rules encode</div>
        </div>
        <button className="btn live" onClick={run} disabled={busy}>{busy ? <span className="spinner" /> : <IRefresh />}Check sources</button>
      </div>
      <div className="explain">
        <div className="row"><span className={`badge ${tone}`}>{status.replace(/_/g, " ")}</span>
          <span className="small muted">{String(d?.reason ?? (d?.checked_at ? `checked ${d.checked_at}` : "The installed rules never change at runtime. Drift opens a review for the next pack release."))}</span></div>
        {findings.map((f, i) => (
          <div key={i} className="notice applicable">
            <b>{f.title}</b>
            <div className="tiny muted">published {f.date} · affects {f.affected_rules.length ? f.affected_rules.join(", ") : "no installed rule"}</div>
            <div className="small">{f.runtime_effect} · {f.action}</div>
            {f.url && <a className="tiny" href={f.url} target="_blank" rel="noreferrer">{f.url}</a>}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function RulePack() {
  const [p, setP] = useState<RulePackView | null>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.rulepack().then(setP).catch((e) => setErr(String(e))); }, []);
  const filtered = useMemo(() => (p ? p.rules.filter((r) => !q || `${r.id} ${r.title} ${quotes(r.source.quote).join(" ")}`.toLowerCase().includes(q.toLowerCase())) : []), [p, q]);
  if (err) return <div className="page"><div className="error">{err}</div></div>;
  if (!p) return <div className="page"><span className="spinner" /></div>;
  const who = p.sources["WHO-AWARE-2022"] as Record<string, string>;
  return (
    <div className="page stack">
      <div className="page-head">
        <div>
          <h1>{p.title} <span className="muted" style={{ fontWeight: 500 }}>{p.version}</span></h1>
          <p>{p.summary}</p>
        </div>
        <div className="hashes"><span>sha256 <code>{p.sha256.slice(0, 16)}</code></span><span>effective {p.effective_date}</span></div>
      </div>
      <div className="grid3">
        <div className="card metric"><div className="v">{p.rules.length}</div><div className="l">rules, each with a version and a cited source</div></div>
        <div className="card metric"><div className="v">{p.quotes_verified}/{p.quotes_checked}</div><div className="l">source quotes found verbatim on the cited page (checked on every load)</div></div>
        <div className="card metric"><div className="v">{Object.keys(p.sources).length}</div><div className="l">sources: {who?.title} ({who?.edition}) and 7 FDA labels</div></div>
      </div>
      <div className="card pad stack" style={{ gap: 8 }}>
        <h3>Policies</h3>
        <p className="small muted">RxLint defaults that are not clinical guidance. An institution sets them; every calculation that uses one names it.</p>
        <table className="tbl"><tbody>
          {Object.entries(p.policies).map(([k, v]) => <tr key={k}><td className="mono">{k}</td><td><b>{v.title}</b><div className="small muted">{v.text}</div></td></tr>)}
        </tbody></table>
      </div>
      <Drift />
      <div className="row"><input className="input" style={{ maxWidth: 360 }} placeholder="Filter rules" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      {GROUPS.map((g) => {
        const rules = filtered.filter(g.match);
        if (!rules.length) return null;
        return (
          <div key={g.title} className="card">
            <div className="card-head"><h3>{g.title}</h3><span className="sub">{rules.length} rules</span></div>
            <div style={{ overflowX: "auto" }}>
              <table className="tbl">
                <thead><tr><th style={{ width: 190 }}>Rule</th><th>What it checks</th><th style={{ width: "42%" }}>Source quote</th></tr></thead>
                <tbody>
                  {rules.map((r) => (
                    <tr key={r.id}>
                      <td><div className="mono">{r.id}</div><div className="tiny muted">v{r.version} · {r.severity}</div></td>
                      <td><div>{r.title}</div>{r.explain && <div className="tiny muted">{r.explain}</div>}</td>
                      <td>
                        {quotes(r.source.quote).slice(0, 2).map((x, i) => <div key={i} className="small">&ldquo;{x}&rdquo;</div>)}
                        <div className="tiny muted" style={{ marginTop: 3 }}>
                          {r.source.ref === "PACK" ? "RxLint product reconciliation" : r.source.ref} {loc(r.source.locator)}
                          {r.quote_verified === true && <span className="badge t-pass" style={{ marginLeft: 6 }}>verbatim</span>}
                          {r.quote_verified === false && <span className="badge t-review" style={{ marginLeft: 6 }}>quote not found</span>}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}
