import { useEffect, useState } from "react";
import { api } from "../api";

type Row = Record<string, string | number | null>;
interface Summary {
  status?: string;
  generated_at?: string;
  description?: string;
  headline?: { label: string; value: string; note?: string }[];
  tables?: { title: string; note?: string; columns: string[]; rows: Row[] }[];
}

export default function Bench() {
  const [s, setS] = useState<Summary | null>(null);
  useEffect(() => { api.bench().then((x) => setS(x as Summary)).catch(() => setS({ status: "NOT_RUN" })); }, []);
  return (
    <div className="page stack">
      <div className="page-head">
        <div>
          <h1>RxLintBench</h1>
          <p>
            Synthetic prescription and bottle photos with exact ground truth, one injected error per case, held out by handwriting font,
            photo perturbation and product. The headline metric is the false-safe rate: cases with a real error that come back PASS.
          </p>
        </div>
      </div>
      {!s && <span className="spinner" />}
      {s?.status === "NOT_RUN" && <div className="card empty">No benchmark results published in this deployment yet. Run <code>python -m rxlint.bench.evaluate</code>.</div>}
      {s?.headline && (
        <div className="grid3">
          {s.headline.map((h) => (
            <div key={h.label} className="card metric"><div className="v">{h.value}</div><div className="l">{h.label}</div>{h.note && <div className="tiny faint">{h.note}</div>}</div>
          ))}
        </div>
      )}
      {s?.tables?.map((t) => (
        <div key={t.title} className="card">
          <div className="card-head"><h3>{t.title}</h3>{t.note && <span className="sub">{t.note}</span>}</div>
          <div style={{ overflowX: "auto" }}>
            <table className="tbl">
              <thead><tr>{t.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{t.rows.map((r, i) => <tr key={i}>{t.columns.map((c) => <td key={c}>{r[c] ?? ""}</td>)}</tr>)}</tbody>
            </table>
          </div>
        </div>
      ))}
      {s?.generated_at && <div className="tiny muted">Generated {s.generated_at}. {s.description}</div>}
    </div>
  );
}
