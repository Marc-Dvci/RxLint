import { type LiveResult } from "../api";
import { IExternal, IGlobe } from "../icons";

// A clear search reports what was searched; search recall is not exhaustive, so it never says "no recall".
export const LIVE_STATUS: Record<string, { label: string; tone: string; line: string }> = {
  LIVE_REVIEW: { label: "LIVE REVIEW", tone: "t-live", line: "An authoritative notice may apply to this product or lot. Do not dispense until a pharmacist has reviewed it." },
  LIVE_CLEAR: { label: "NO NOTICE FOUND", tone: "t-oos", line: "No applicable notice was found in the searched regulator sources during this check. Search coverage is not exhaustive, so this does not prove that no recall applies." },
  LIVE_UNAVAILABLE: { label: "LIVE UNAVAILABLE", tone: "t-cannot", line: "The live check could not be completed. Check the regulator directly before dispensing." },
  LIVE_NOT_CONFIGURED: { label: "NOT CONFIGURED", tone: "t-oos", line: "No reviewed regulator-source policy exists for this country. Check recalls directly before dispensing." },
};

export const APPLICABLE = ["lot_recall", "product_recall", "safety_communication"];

export const MATCH: Record<string, string> = {
  lot_recall: "Recall naming this lot",
  product_recall: "Recall naming this product",
  safety_communication: "Safety communication",
  other_lot: "Same product, other lots",
  not_applicable: "Does not name this product",
  after_check_date: "Published after the check date",
  supply_notice: "Supply information",
};

export default function LivePanel({ live, busy, err, onRun, country, asOf }: {
  live: LiveResult | null; busy: boolean; err: string | null; onRun: () => void; country: string | null; asOf: string | null;
}) {
  const st = live ? LIVE_STATUS[live.status] : null;
  const applicable = live?.notices.filter((n) => APPLICABLE.includes(n.match_type)) ?? [];
  const others = live?.notices.filter((n) => !applicable.includes(n)) ?? [];
  return (
    <div className="card live-card" id="live-panel">
      <div className="card-head">
        <div className="row" style={{ gap: 10 }}>
          <IGlobe className="" />
          <div>
            <h3>Live regulator intelligence</h3>
            <div className="sub">Separate from the verified result · Tavily Search + Extract on allowlisted regulator domains{country ? ` for ${country}` : ""}{asOf ? ` · as of ${asOf}` : ""}</div>
          </div>
        </div>
        <button className="btn live" onClick={onRun} disabled={busy}>{busy && <span className="spinner" />}{live ? "Re-run live check" : "Run live check"}</button>
      </div>
      <div className="explain">
        {err && <div className="error">{err}</div>}
        {!live && !busy && <div className="small muted">The rule pack is frozen and hashed. This check asks whether a regulator has published anything since, for this product and lot.</div>}
        {live && st && (
          <>
            <div className="row">
              <span className={`badge ${st.tone}`} style={{ fontSize: 12.5, padding: "4px 10px" }}>{st.label}</span>
              <span className="small">{live.status === "LIVE_CLEAR" ? st.line : live.statement ?? live.reason ?? st.line}</span>
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
              <div>Policy {live.query_policy} · retrieved {live.retrieved_at}{(live as { cached?: boolean }).cached ? " (cached, refreshed every 6 hours)" : ""} · shown beside the deterministic verdict, never folded into it</div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
