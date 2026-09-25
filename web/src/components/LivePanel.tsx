import { useState } from "react";
import { api, type LiveResult } from "../api";
import { IExternal, IGlobe } from "../icons";

const STATUS: Record<string, { label: string; tone: string; line: string }> = {
  LIVE_REVIEW: { label: "LIVE REVIEW", tone: "t-live", line: "An authoritative notice may apply to this product. Review it before dispensing." },
  LIVE_CLEAR: { label: "LIVE CLEAR", tone: "t-pass", line: "No applicable alert was retrieved from the configured sources during this check." },
  LIVE_UNAVAILABLE: { label: "LIVE UNAVAILABLE", tone: "t-cannot", line: "The live check could not be completed. This does not change the verified result." },
  LIVE_NOT_CONFIGURED: { label: "NOT CONFIGURED", tone: "t-oos", line: "No reviewed regulator-source policy exists for this country or product." },
};

const MATCH: Record<string, string> = {
  lot_recall: "Recall naming this lot",
  product_recall: "Recall naming this product",
  safety_communication: "Safety communication",
  other_lot: "Same product, other lots",
  not_applicable: "Does not name this product",
  after_check_date: "Published after the check date",
  supply_notice: "Supply information",
};

export default function LivePanel({ caseId, initial, country, asOf }: { caseId: string; initial?: LiveResult; country: string | null; asOf: string | null }) {
  const [live, setLive] = useState<LiveResult | null>(initial ?? null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setBusy(true);
    setErr(null);
    try {
      setLive(await api.live(caseId));
    } catch (e) {
      setErr(String(e));
    }
    setBusy(false);
  };
  const st = live ? STATUS[live.status] : null;
  const applicable = live?.notices.filter((n) => ["lot_recall", "product_recall", "safety_communication"].includes(n.match_type)) ?? [];
  const others = live?.notices.filter((n) => !applicable.includes(n)) ?? [];
  return (
    <div className="card live-card">
      <div className="card-head">
        <div className="row" style={{ gap: 10 }}>
          <IGlobe className="" />
          <div>
            <h3>Live regulator intelligence</h3>
            <div className="sub">Separate from the verified result · Tavily Search + Extract on allowlisted regulator domains{country ? ` for ${country}` : ""}{asOf ? ` · as of ${asOf}` : ""}</div>
          </div>
        </div>
        <button className="btn live" onClick={run} disabled={busy}>{busy && <span className="spinner" />}{live ? "Re-run live check" : "Run live check"}</button>
      </div>
      <div className="explain">
        {err && <div className="error">{err}</div>}
        {!live && !busy && <div className="small muted">The rule pack is frozen and hashed. This check asks whether a regulator has published anything since, for this product and lot.</div>}
        {live && st && (
          <>
            <div className="row">
              <span className={`badge ${st.tone}`} style={{ fontSize: 12.5, padding: "4px 10px" }}>{st.label}</span>
              <span className="small">{live.statement ?? live.reason ?? st.line}</span>
            </div>
            {applicable.map((n, i) => (
              <div key={i} className="notice applicable">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <b>{n.title}</b>
                  <span className="badge t-live">{MATCH[n.match_type]}</span>
                </div>
                <div className="tiny muted">
                  {n.authority} · {n.source}{n.published_at ? ` · published ${n.published_at}` : ""} · matched {n.matched_fields.join(", ")}
                </div>
                {n.reason && <div className="small"><b>Reason:</b> {n.reason}</div>}
                {n.snippet && <div className="snip">{n.snippet}</div>}
                <a className="small" href={n.url} target="_blank" rel="noreferrer">Open the original source <IExternal className="" /></a>
              </div>
            ))}
            {others.length > 0 && (
              <details>
                <summary className="small muted" style={{ cursor: "pointer" }}>{others.length} retrieved notices did not apply</summary>
                <div className="stack" style={{ gap: 6, marginTop: 8 }}>
                  {others.map((n, i) => (
                    <div key={i} className="notice">
                      <div className="row" style={{ justifyContent: "space-between" }}>
                        <span className="small">{n.title}</span>
                        <span className="badge t-note">{MATCH[n.match_type]}</span>
                      </div>
                      {n.listed_lots.length > 0 && <div className="tiny muted">Lots listed: {n.listed_lots.slice(0, 8).join(", ")}</div>}
                      <a className="tiny" href={n.url} target="_blank" rel="noreferrer">{n.url}</a>
                    </div>
                  ))}
                </div>
              </details>
            )}
            <div className="searches">
              {live.searches.map((s, i) => (
                <div key={i}>
                  {s.ok ? "✓" : "✕"} {s.source}{s.query ? `: ${s.query}` : ""}{s.exact_match ? " · exact match" : ""}{s.results !== undefined ? ` · ${s.results} results` : ""}
                  {s.rejected_off_allowlist ? ` · ${s.rejected_off_allowlist} rejected off allowlist` : ""}{s.error ? ` · ${s.error}` : ""}
                </div>
              ))}
              <div>Policy {live.query_policy} · retrieved {live.retrieved_at}{(live as { cached?: boolean }).cached ? " (cached, refreshed every 6 hours)" : ""} · the live state never changes the deterministic verdict</div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
