import { useEffect, useState } from "react";
import { api } from "../api";
import { fieldLabel } from "../labels";

type Row = Record<string, string | number | null>;
interface Summary {
  status?: string;
  generated_at?: string;
  description?: string;
  headline?: { label: string; value: string; note?: string }[];
  tables?: { title: string; note?: string; columns: string[]; rows: Row[] }[];
}

interface External {
  status: string; images?: number; label_images?: number; negative_controls?: number; failed_images?: number;
  field_results?: Record<string, { exact: number; total: number; autonomous: number; wrong_autonomous: number }>;
  limitations?: string[];
}

export default function Bench() {
  const [s, setS] = useState<Summary | null>(null);
  const [external, setExternal] = useState<External | null>(null);
  useEffect(() => { api.bench().then((x) => setS(x as Summary)).catch(() => setS({ status: "NOT_RUN" })); }, []);
  useEffect(() => { fetch("/api/bench/real-world").then((r) => r.json()).then(setExternal).catch(() => setExternal(null)); }, []);
  return (
    <div className="page stack">
      <div className="page-head">
        <div>
          <h1>RxLintBench</h1>
          <p>
            120 held-out prescription and bottle cases, with every verdict traceable to its evidence.
            Independent PP-OCRv6 checks, focused crop reads and a validation-calibrated reliability head keep uncertain values under review.
          </p>
        </div>
      </div>
      {!s && <span className="spinner" />}
      {s?.status === "NOT_RUN" && <div className="card empty">No benchmark results published in this deployment yet. Run <code>python -m rxlint.bench.evaluate</code>.</div>}
      {s?.headline && (
        <div className={s.headline.length === 4 ? "grid4" : "grid3"}>
          {s.headline.map((h) => (
            <div key={h.label} className="card metric"><div className="v">{h.value}</div><div className="l">{h.label}</div>{h.note && <div className="tiny faint">{h.note}</div>}</div>
          ))}
        </div>
      )}
      {s?.status === "ok" && <p className="small muted">
        The test fold uses rendered prescription and bottle photos with a held-out handwriting font, photo perturbation families and product.
        Confirmation is simulated from written ground truth. These results measure the prototype and do not establish clinical safety.
      </p>}
      {s?.tables?.map((t) => (
        <div key={t.title} className="card">
          <div className="card-head"><h3>{t.title}</h3>{t.note && <span className="sub">{t.note}</span>}</div>
          <div style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead><tr>{t.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{t.rows.map((r, i) => <tr key={i}>{t.columns.map((c) => <td key={c}>{cell(c, r[c])}</td>)}</tr>)}</tbody>
            </table>
          </div>
        </div>
      ))}
      {s?.generated_at && <div className="tiny muted">Generated {s.generated_at}. {s.description}</div>}
      {external?.status === "ok" && <div className="card">
        <div className="card-head"><h3>Public medicine photograph pilot</h3><span className="sub">{external.images} real photos · perception only</span></div>
        <div className="pad stack small">
          <p>Perception was also checked on {external.label_images} openly licensed package photos and {external.negative_controls} negative controls from Wikimedia Commons, with author attribution and source hashes.</p>
          <table className="tbl"><thead><tr><th>Field</th><th>Exact reading</th><th>Accepted by parser and gates</th><th>Wrong accepted</th></tr></thead>
            <tbody>{Object.entries(external.field_results ?? {}).map(([field, c]) => <tr key={field}><td>{fieldLabel(field)}</td><td>{c.exact}/{c.total}</td><td>{c.autonomous}/{c.total}</td><td>{c.wrong_autonomous}</td></tr>)}</tbody>
          </table>
          <p>Liquid concentration is exact on 4/5 packages; solid strength is 0/4, giving 4/9 across both forms.
            This single-annotator development pilot measures field reading; paired prescriptions and independent pharmacist assessment are the next validation stage.
            {external.failed_images} failed control read is included.</p>
          <a href="/api/bench/real-world" target="_blank" rel="noreferrer">View complete pilot results and limitations</a>
        </div>
      </div>}
    </div>
  );
}

/** Rates as percentages, AUC as three decimals, counts and labels as published. */
function cell(column: string, v: unknown): string {
  if (typeof v !== "number") return v == null ? "" : String(v);
  if (/auc/i.test(column)) return v.toFixed(3);
  if (/false accepts|readings|wrong/i.test(column) || (Number.isInteger(v) && v > 1)) return String(v);
  return v >= 0 && v <= 1 ? `${(v * 100).toFixed(1)}%` : String(v);
}
