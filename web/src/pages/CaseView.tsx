import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { api, type CaseEnvelope, type CaseResult, type Evidence, type Finding, type Health } from "../api";
import { ACTION_LABEL, STATE_META, factValue, fieldLabel, modelName } from "../labels";
import { IChevron, IDown, IFile, StateIcon } from "../icons";
import ExplainPanel from "../components/ExplainPanel";
import LivePanel from "../components/LivePanel";

const STEPS = [
  { key: "quality", title: "Photo checks", desc: "blur, glare, exposure" },
  { key: "extract", title: "Nemotron 3 Nano Omni", desc: "reads both photos" },
  { key: "normalize", title: "Grounding and parsing", desc: "OCR corroboration, unit grammar" },
  { key: "verify", title: "Deterministic kernel", desc: "rule pack checks" },
  { key: "clarify", title: "Nemotron 3 Ultra", desc: "smallest clarification" },
];

function Pipeline({ events, result }: { events: string[]; result?: CaseResult }) {
  const has = (k: string) => events.some((e) => e.startsWith(k));
  const done = (k: string) => {
    if (k === "extract") return has("extract.done") || !!result;
    if (k === "clarify") return has("clarify.done") || (!!result && !result.clarification) || (!!result && result.clarification?.source !== undefined);
    return has(k) || !!result;
  };
  const running = (k: string) => !done(k) && (k === "extract" ? has("extract.start") : k === "clarify" ? has("clarify.start") : false);
  const t = result?.timings_ms ?? {};
  const detail: Record<string, string> = {
    quality: t.quality !== undefined ? `${t.quality} ms` : "",
    extract: t.perception !== undefined ? `${(t.perception / 1000).toFixed(1)} s` : "",
    normalize: t.normalize !== undefined ? `${t.normalize} ms` : "",
    verify: t.verify !== undefined ? `${t.verify} ms, no model call` : "",
    clarify: result && !result.clarification ? "not needed"
      : result?.clarification?.source === "deterministic" ? "kernel default used"
      : t.clarify !== undefined ? `${(t.clarify / 1000).toFixed(1)} s` : "",
  };
  return (
    <div className="card pipeline">
      {STEPS.map((s, i) => (
        <div key={s.key} className={`step ${done(s.key) ? "done" : running(s.key) ? "run" : ""}`}>
          <span className="n">{running(s.key) ? <span className="spinner" style={{ width: 12, height: 12 }} /> : i + 1}</span>
          <div style={{ minWidth: 0 }}>
            <div className="t">{s.title}</div>
            <div className="d">{detail[s.key] || s.desc}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Verdict({ result }: { result: CaseResult }) {
  const v = result.verification;
  const meta = STATE_META[v.state];
  const s = v.summary;
  return (
    <div className={`verdict ${meta.tone}`}>
      <div className="mark"><StateIcon state={v.state} /></div>
      <div>
        <div className="state">{meta.short}</div>
        <div className="small" style={{ color: "var(--ink-2)" }}>{meta.line}</div>
        <div className="counts">
          {s.review > 0 && <span className="badge t-review">{s.review} require review</span>}
          {s.cannot_verify > 0 && <span className="badge t-cannot">{s.cannot_verify} cannot verify</span>}
          {s.out_of_scope > 0 && <span className="badge t-oos">{s.out_of_scope} out of scope</span>}
          <span className="badge t-pass">{s.passed} checks passed</span>
          {s.notes > 0 && <span className="badge t-note">{s.notes} notes</span>}
        </div>
      </div>
      <div className="hashes">
        <span>Rule pack {v.rulepack.version} <code>{v.rulepack.sha256.slice(0, 10)}</code></span>
        <span>Snapshot <code>{v.snapshot_sha256.slice(0, 10)}</code></span>
        <span>Result <code>{v.result_sha256.slice(0, 10)}</code></span>
        <span>{v.engine}</span>
      </div>
    </div>
  );
}

/** Walk parents to every primary node that carries a box on an image. */
function boxesFor(ids: string[], ev: Record<string, Evidence>): { asset: string; bbox: number[]; id: string }[] {
  const out: { asset: string; bbox: number[]; id: string }[] = [];
  const seen = new Set<string>();
  const stack = [...ids];
  while (stack.length) {
    const id = stack.pop()!;
    if (seen.has(id) || !ev[id]) continue;
    seen.add(id);
    const n = ev[id];
    if (n.source?.asset_id && n.source.bbox) out.push({ asset: n.source.asset_id, bbox: n.source.bbox, id });
    stack.push(...n.parents);
  }
  return out;
}

function Viewer({ caseId, result, highlight, tone, selectedAsset, setAsset }: {
  caseId: string; result: CaseResult; highlight: { asset: string; bbox: number[] }[]; tone: "hot" | "warn";
  selectedAsset: string; setAsset: (a: string) => void;
}) {
  const images = result.assets.filter((a) => a.kind !== "audio");
  const shown = selectedAsset === "both" ? images.map((a) => a.id) : [selectedAsset];
  const q = selectedAsset === "both" ? undefined : result.quality[selectedAsset];
  const ext = result.extractions.find((e) => e.asset_id === selectedAsset);
  return (
    <div className="card" style={{ overflow: "hidden" }}>
      <div className="viewer-tabs">
        <div className="seg">
          {images.length > 1 && <button className={selectedAsset === "both" ? "on" : ""} onClick={() => setAsset("both")}>Both</button>}
          {images.map((a) => (
            <button key={a.id} className={selectedAsset === a.id ? "on" : ""} onClick={() => setAsset(a.id)}>
              {a.kind === "prescription" ? "Prescription" : "Medicine"}
              {highlight.some((h) => h.asset === a.id) ? " •" : ""}
            </button>
          ))}
        </div>
        <span style={{ flex: 1 }} />
        {q?.checks.filter((c) => !c.ok).map((c) => <span key={c.id} className="badge t-cannot" title={c.message}>{c.id}</span>)}
        {q && q.checks.every((c) => c.ok) && <span className="badge t-pass">photo checks ok</span>}
        {ext?.model && <span className="chip tiny" title={ext.model}>{ext.replayed ? "recorded" : "live"} · {((ext.latency_ms ?? 0) / 1000).toFixed(1)} s</span>}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: `repeat(${shown.length}, minmax(0, 1fr))`, gap: 2, background: "#0b0f14" }}>
        {shown.map((aid) => {
          const obs = result.observations.filter((o) => o.asset_id === aid && o.bbox && o.method !== "rapidocr (second reader)");
          const hot = highlight.filter((h) => h.asset === aid);
          return (
            <div key={aid} className="viewer" style={{ borderRadius: 0 }}>
              <img src={api.assetUrl(caseId, aid)} alt={aid} />
              <svg className="boxes" viewBox="0 0 1 1" preserveAspectRatio="none">
                {obs.map((o, i) => {
                  const [x0, y0, x1, y1] = o.bbox!;
                  return <rect key={i} className={`box ${o.requires_confirmation || o.corroboration === "contradicted" ? "warn" : "dim"}`} x={x0} y={y0} width={x1 - x0} height={y1 - y0} />;
                })}
                {hot.map((h, i) => {
                  const [x0, y0, x1, y1] = h.bbox;
                  const pad = 0.006;
                  return (
                    <g key={`h${i}`}>
                      <rect className={`boxfill ${tone}`} x={x0 - pad} y={y0 - pad} width={x1 - x0 + 2 * pad} height={y1 - y0 + 2 * pad} />
                      <rect className={`box ${tone}`} x={x0 - pad} y={y0 - pad} width={x1 - x0 + 2 * pad} height={y1 - y0 + 2 * pad} rx="0.004" />
                    </g>
                  );
                })}
              </svg>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const FACT_ORDER = ["rx.product", "dispensed.product", "rx.strength", "dispensed.strength", "rx.dose", "rx.frequency", "rx.duration_days",
  "rx.indication", "patient.weight_kg", "patient.age_months", "patient.allergies", "patient.current_medications", "dispensed.volume_ml",
  "dispensed.lot", "dispensed.expiry", "rx.dosage_form", "dispensed.dosage_form", "rx.route"];

function FactsTable({ result, selected, onSelect }: { result: CaseResult; selected: string | null; onSelect: (k: string, ids: string[]) => void }) {
  const ev = result.verification.evidence;
  const rows = FACT_ORDER.map((k) => ev[`ev_${k.replace(/\./g, "_")}`]).filter(Boolean) as Evidence[];
  const readerOf = (n: Evidence) => {
    const kinds = new Set<string>();
    const stack = [...n.parents];
    const seen = new Set<string>();
    while (stack.length) {
      const id = stack.pop()!;
      if (seen.has(id) || !ev[id]) continue;
      seen.add(id);
      const p = ev[id];
      if (p.kind === "VISUAL_OBSERVATION") kinds.add(p.method?.includes("rapidocr") ? "OCR" : "photo");
      else if (p.kind === "USER_ENTERED_FACT") kinds.add(p.method === "confirmation" ? "confirmed" : "typed");
      else if (p.kind === "SPOKEN_OBSERVATION") kinds.add("voice");
      stack.push(...p.parents);
    }
    return [...kinds];
  };
  return (
    <div className="card" style={{ overflow: "hidden" }}>
      <div className="card-head"><h3>Extracted facts</h3><span className="sub">click a row to locate it</span></div>
      <table className="facts">
        <thead><tr><th>Fact</th><th>Value</th><th>Source</th></tr></thead>
        <tbody>
          {rows.map((n) => {
            const status = n.status;
            const tone = status === "ambiguous" ? "t-cannot" : status === "unrecognised" ? "t-oos" : status === "derived" ? "t-note" : "t-pass";
            return (
              <tr key={n.id} className={selected === n.name ? "sel" : ""} onClick={() => onSelect(n.name, [n.id])}>
                <td>{fieldLabel(n.name)}</td>
                <td>
                  <div className="val">{status === "ambiguous" ? <span className="muted">unresolved</span> : factValue(n.name, n.value) || <span className="muted">none</span>}</div>
                  {n.notes.length > 0 && <div className="tiny muted" style={{ marginTop: 2 }}>{n.notes[0]}</div>}
                </td>
                <td>
                  <div className="row" style={{ gap: 4 }}>
                    {readerOf(n).map((r) => <span key={r} className="chip tiny">{r}</span>)}
                    {status !== "normalized" && <span className={`badge corr ${tone}`}>{status}</span>}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function sevTone(f: Finding): string {
  if (f.status === "cannot_evaluate") return "t-cannot";
  if (f.status === "out_of_scope") return "t-oos";
  if (f.status === "pass") return "t-pass";
  if (f.severity === "advisory") return "t-note";
  return "t-review";
}

function Locator({ loc }: { loc: unknown }) {
  if (!loc) return null;
  if (typeof loc === "string") return <span>{loc}</span>;
  const o = loc as Record<string, unknown>;
  const parts = [];
  if (o.table) parts.push(`Table ${o.table}`);
  if (o.row) parts.push(String(o.row));
  if (o.printed_page) parts.push(`p. ${o.printed_page}`);
  if (o.section) parts.push(String(o.section));
  if (o.chapter) parts.push(`chapter ${o.chapter}`);
  return <span>{parts.join(" · ")}</span>;
}

function FindingCard({ f, open, onToggle, onLocate, also = [] }: { f: Finding; open: boolean; onToggle: () => void; onLocate: () => void; also?: Finding[] }) {
  const src = f.source.primary;
  return (
    <div className={`finding ${f.status} sev-${f.severity ?? "none"}`}>
      <button className="head" onClick={() => { onToggle(); onLocate(); }}>
        <div>
          <div className="row" style={{ gap: 8, marginBottom: 3 }}>
            <span className={`badge ${sevTone(f)}`}>{f.status === "fail" ? (f.severity ?? "fail").toUpperCase() : f.status.replace(/_/g, " ").toUpperCase()}</span>
            <span className="rule">{f.rule_id} v{f.rule_version}</span>
            <span className="small muted">{f.title}</span>
          </div>
          <div className="msg">{f.message}</div>
          {also.length > 0 && <div className="tiny muted" style={{ marginTop: 4 }}>Same cause also blocks {also.map((a) => a.rule_id).join(", ")}</div>}
        </div>
        <IChevron className="" />
      </button>
      {open && (
        <div className="body">
          {Object.keys(f.facts).length > 0 && (
            <div className="sect">
              <span className="upper">Observed</span>
              <dl className="kv" style={{ margin: 0 }}>
                {Object.entries(f.facts).filter(([, v]) => typeof v !== "object").map(([k, v]) => (
                  <Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{String(v)}</dd></Fragment>
                ))}
              </dl>
            </div>
          )}
          {f.calculations.length > 0 && (
            <div className="sect">
              <span className="upper">Calculation</span>
              <div className="stack" style={{ gap: 8 }}>
                {f.calculations.map((c) => (
                  <div key={c.name} className="calc">
                    <span className="f">{c.name} = {c.formula}</span>
                    {c.steps.map((s, i) => <span key={i}>{s}</span>)}
                  </div>
                ))}
              </div>
            </div>
          )}
          {src && (
            <div className="sect">
              <span className="upper">Rule source</span>
              <div className="stack" style={{ gap: 6 }}>
                <div className="small">
                  <b>{src.title}</b>{src.edition ? ` (${src.edition})` : ""} · <Locator loc={src.locator} />
                  {src.url && <> · <a href={src.url} target="_blank" rel="noreferrer">source</a></>}
                </div>
                {src.quotes.slice(0, 3).map((q, i) => <blockquote key={i} className="q">&ldquo;{q}&rdquo;</blockquote>)}
                {f.policies.length > 0 && <div className="tiny muted">Policies applied: {f.policies.join(", ")} (RxLint defaults, institution-configurable)</div>}
                {f.source.explain && <div className="tiny muted">{f.source.explain}</div>}
              </div>
            </div>
          )}
          <div className="sect">
            <span className="upper">Action</span>
            <div>{f.action && f.action !== "none" ? <b>{ACTION_LABEL[f.action] ?? f.action}</b> : <span className="muted">none</span>}</div>
          </div>
        </div>
      )}
    </div>
  );
}

function cropStyle(url: string, bbox: number[]): React.CSSProperties {
  const [x0, y0, x1, y1] = bbox;
  const padX = (x1 - x0) * 0.25, padY = (y1 - y0) * 0.6;
  const a = Math.max(0, x0 - padX), b = Math.max(0, y0 - padY), c = Math.min(1, x1 + padX), d = Math.min(1, y1 + padY);
  const w = c - a, h = d - b;
  return {
    backgroundImage: `url(${url})`,
    backgroundSize: `${100 / w}% ${100 / h}%`,
    backgroundPosition: `${w >= 1 ? 0 : (a / (1 - w)) * 100}% ${h >= 1 ? 0 : (b / (1 - h)) * 100}%`,
  };
}

const CONFIRMABLE: Record<string, string> = {
  "rx.dose": "rx.dose", "rx.strength": "rx.strength", "rx.patient_weight": "patient.weight", "dispensed.strength": "dispensed.strength",
  "rx.frequency": "rx.frequency", "rx.duration": "rx.duration", "dispensed.expiry": "dispensed.expiry", "dispensed.drug": "dispensed.drug",
  "rx.drug": "rx.drug", "rx.patient_age": "patient.age",
};
const FACT_TO_FIELDS: Record<string, string[]> = {
  "rx.dose": ["rx.dose"], "rx.strength": ["rx.strength"], "patient.weight_kg": ["rx.patient_weight"], "dispensed.strength": ["dispensed.strength"],
  "rx.frequency": ["rx.frequency"], "rx.duration_days": ["rx.duration"], "dispensed.expiry": ["dispensed.expiry"], "dispensed.product": ["dispensed.drug"],
  "rx.product": ["rx.drug"], "patient.age_months": ["rx.patient_age"],
};

function ConfirmPanel({ caseId, result, onDone }: { caseId: string; result: CaseResult; onDone: (r: CaseResult) => void }) {
  const clar = result.clarification;
  const blocked = clar?.fields ?? [];
  const items = blocked.flatMap((fact) => (FACT_TO_FIELDS[fact] ?? []).map((field) => ({
    fact, field, obs: result.observations.find((o) => o.field === field && o.asset_id && o.method !== "rapidocr (second reader)"),
  })));
  const [vals, setVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!clar) return null;
  const confirmAll = async () => {
    setBusy(true);
    setErr(null);
    const body: Record<string, string> = {};
    for (const it of items) {
      const v = vals[it.field] ?? "";
      if (v.trim()) body[CONFIRMABLE[it.field] ?? it.field] = v.trim();
    }
    try {
      onDone(await api.confirm(caseId, body));
    } catch (e) {
      setErr(String(e));
    }
    setBusy(false);
  };
  return (
    <div className="confirm">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <div className="upper" style={{ color: "var(--cannot)" }}>{ACTION_LABEL[clar.action] ?? clar.action}</div>
          <div style={{ fontWeight: 600, marginTop: 2 }}>{clar.message ?? clar.reason}</div>
          <div className="tiny muted" style={{ marginTop: 2 }}>
            {clar.source === "model" ? `Chosen by ${modelName(clar.model)}` : "Chosen by the kernel"}. A confirmation re-runs the rules without another model call.
          </div>
        </div>
      </div>
      {items.map((it) => (
        <div key={it.field} className="item">
          {it.obs?.bbox && it.obs.asset_id ? <div className="crop" style={cropStyle(api.assetUrl(caseId, it.obs.asset_id), it.obs.bbox)} /> : <div className="crop" />}
          <div className="stack" style={{ gap: 4 }}>
            <b>{fieldLabel(it.field)}</b>
            {it.obs && (
              <span className="small muted">
                Model read <b style={{ color: "var(--ink)" }}>{it.obs.text}</b>
                {it.obs.ocr_text ? <> · OCR read <b style={{ color: "var(--ink)" }}>{it.obs.ocr_text}</b></> : " · OCR could not confirm"}
              </span>
            )}
            <div className="quick">
              {it.obs && <button onClick={() => setVals((p) => ({ ...p, [it.field]: it.obs!.text }))}>use {it.obs.text}</button>}
              {(it.obs?.alternatives ?? []).slice(0, 2).map((a) => <button key={a} onClick={() => setVals((p) => ({ ...p, [it.field]: a }))}>use {a}</button>)}
            </div>
          </div>
          <input className="input" style={{ width: 160 }} value={vals[it.field] ?? ""} placeholder="value as written"
            onChange={(e) => setVals((p) => ({ ...p, [it.field]: e.target.value }))} />
        </div>
      ))}
      {err && <div className="error">{err}</div>}
      {items.length > 0 && (
        <div className="row">
          <button className="btn primary" onClick={confirmAll} disabled={busy}>{busy && <span className="spinner" />}Confirm and re-check</button>
          <span className="tiny muted">Your entry is recorded as a pharmacist confirmation in the evidence graph.</span>
        </div>
      )}
    </div>
  );
}

function ModelCalls({ result }: { result: CaseResult }) {
  if (!result.model_calls.length) return null;
  return (
    <div className="card">
      <div className="card-head"><h3>Model calls</h3><span className="sub">every call is logged with model, provider and latency</span></div>
      <div style={{ overflowX: "auto" }}>
        <table className="tbl">
          <thead><tr><th>Role</th><th>Model</th><th>Provider</th><th>Purpose</th><th>Latency</th><th>Tokens</th></tr></thead>
          <tbody>
            {result.model_calls.map((c, i) => (
              <tr key={i}>
                <td>{c.role}</td>
                <td className="mono tiny">{modelName(c.model)}</td>
                <td>{c.replayed ? <span title={`recorded ${c.recorded_at}`}>replay of {c.provider}</span> : c.provider}{!c.ok && <span className="badge t-review" style={{ marginLeft: 6 }}>{c.error}</span>}</td>
                <td className="tiny">{c.purpose}</td>
                <td>{c.latency_ms ? `${(c.latency_ms / 1000).toFixed(1)} s` : ""}</td>
                <td className="tiny">{c.prompt_tokens ? `${c.prompt_tokens} / ${c.completion_tokens}` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function CaseView({ id }: { id: string; health: Health | null }) {
  const [env, setEnv] = useState<CaseEnvelope | null>(null);
  const [events, setEvents] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CaseResult | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [hl, setHl] = useState<string[]>([]);
  const [hlTone, setHlTone] = useState<"hot" | "warn">("hot");
  const [selFact, setSelFact] = useState<string | null>(null);
  const [asset, setAsset] = useState<string>("rx");
  const [showPasses, setShowPasses] = useState(false);

  const load = useCallback(async () => {
    const e = await api.getCase(id);
    setEnv(e);
    if (e.result) setResult(e.result);
    return e;
  }, [id]);

  useEffect(() => {
    let es: EventSource | null = null;
    load().then((e) => {
      if (e.status === "done") return;
      es = new EventSource(`/api/cases/${id}/events`);
      const on = (name: string) => (msg: MessageEvent) => {
        setEvents((p) => [...p, name]);
        if (name === "done") { es?.close(); load(); }
        if (name === "error") { es?.close(); setError(JSON.parse(msg.data).message); }
      };
      ["created", "quality", "extract.start", "extract.done", "normalize", "verify", "clarify.start", "clarify.done", "done", "error"]
        .forEach((n) => es!.addEventListener(n, on(n) as EventListener));
    }).catch((err) => setError(String(err)));
    return () => es?.close();
  }, [id, load]);

  const v = result?.verification;
  const findings = useMemo(() => (v ? v.findings : []), [v]);
  const issues = findings.filter((f) => f.status === "fail" || f.status === "cannot_evaluate" || f.status === "out_of_scope");
  // Rules blocked by the same missing fact are shown once, with the others listed.
  const grouped = useMemo(() => {
    const out: { f: Finding; also: Finding[] }[] = [];
    const byCause = new Map<string, { f: Finding; also: Finding[] }>();
    for (const f of issues) {
      if (f.status === "cannot_evaluate" && f.missing.length) {
        const k = [...f.missing].sort().join("|");
        const g = byCause.get(k);
        if (g) { g.also.push(f); continue; }
        const ng = { f, also: [] as Finding[] };
        byCause.set(k, ng);
        out.push(ng);
      } else out.push({ f, also: [] });
    }
    return out;
  }, [issues]);
  const passes = findings.filter((f) => f.status === "pass");
  const highlight = useMemo(() => (v ? boxesFor(hl, v.evidence) : []), [hl, v]);

  useEffect(() => {
    // Open and locate the most severe finding once the verdict arrives.
    if (v && issues.length && open === null) {
      const top = issues[0];
      setOpen(top.finding_id);
      setHl(top.evidence);
      setHlTone(top.status === "fail" ? "hot" : "warn");
      const b = boxesFor(top.evidence, v.evidence);
      if (new Set(b.map((x) => x.asset)).size > 1) setAsset("both");
      else if (b.length) setAsset(b[0].asset);
    }
  }, [v]); // eslint-disable-line react-hooks/exhaustive-deps

  const locate = (f: Finding) => {
    setHl(f.evidence);
    setHlTone(f.status === "fail" ? "hot" : "warn");
    setSelFact(null);
    if (v) {
      const b = boxesFor(f.evidence, v.evidence);
      if (new Set(b.map((x) => x.asset)).size > 1) setAsset("both");
      else if (b.length && asset !== "both" && !b.some((x) => x.asset === asset)) setAsset(b[0].asset);
    }
  };

  const demo = env?.input.meta?.demo;
  return (
    <div className="page stack">
      <div className="page-head">
        <div>
          <div className="row" style={{ gap: 8 }}>
            <a href="#/" className="small">Verify</a><span className="faint">/</span>
            <span className="mono small muted">{id}</span>
          </div>
          <h1 style={{ marginTop: 4 }}>{demo ? `${demo.id} · ${demo.title}` : "Verification"}</h1>
          {demo && <p>{demo.summary}</p>}
        </div>
        {result && (
          <div className="row">
            <a className="btn" href={`/api/cases/${id}/report`} target="_blank" rel="noreferrer"><IFile /> Report</a>
            <a className="btn" href={`/api/cases/${id}/report?format=json`}><IDown /> JSON</a>
          </div>
        )}
      </div>

      <Pipeline events={events} result={result ?? undefined} />
      {error && <div className="error">{error}</div>}
      {!result && !error && <div className="card empty"><span className="spinner" style={{ display: "inline-block", marginRight: 8, verticalAlign: "middle" }} />Reading the photos…</div>}

      {result && v && (
        <>
          <Verdict result={result} />
          {result.untrusted_text_flagged && (
            <div className="card pad row" style={{ borderColor: "var(--live-line)" }}>
              <span className="badge t-live">UNTRUSTED TEXT</span>
              <span className="small">The photo contains text addressed to a machine. It was transcribed as data and has no path to the verdict.</span>
            </div>
          )}
          {result.clarification && <ConfirmPanel caseId={id} result={result} onDone={(r) => { setResult(r); setOpen(null); }} />}

          <div className="grid2">
            <div className="stack">
              <Viewer caseId={id} result={result} highlight={highlight} tone={hlTone} selectedAsset={asset} setAsset={setAsset} />
              <FactsTable result={result} selected={selFact} onSelect={(k, ids) => {
                setSelFact(k); setHl(ids); setHlTone("hot");
                const b = boxesFor(ids, v.evidence);
                if (b.length) setAsset(b[0].asset);
              }} />
            </div>
            <div className="stack">
              <div className="stack" style={{ gap: 10 }}>
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <h2>Findings</h2>
                  <span className="small muted">{v.rulepack.rules} rules installed · {findings.length} evaluated for this case</span>
                </div>
                {issues.length === 0 && <div className="card pad small">No rule failed. {v.state === "PASS" ? "PASS covers the checks listed below, within the installed pack." : ""}</div>}
                {grouped.map(({ f, also }) => (
                  <FindingCard key={f.finding_id} f={f} also={also} open={open === f.finding_id}
                    onToggle={() => setOpen(open === f.finding_id ? null : f.finding_id)} onLocate={() => locate(f)} />
                ))}
                <button className="btn ghost small" onClick={() => setShowPasses(!showPasses)} style={{ justifySelf: "start" }}>
                  {showPasses ? "Hide" : "Show"} {passes.length} passed checks
                </button>
                {showPasses && passes.map((f) => (
                  <FindingCard key={f.finding_id} f={f} open={open === f.finding_id}
                    onToggle={() => setOpen(open === f.finding_id ? null : f.finding_id)} onLocate={() => locate(f)} />
                ))}
                {(v.coverage.current_medicines_not_covered.length > 0) && (
                  <div className="tiny muted">Interaction coverage: {v.coverage.interaction_pairs} encoded pairs. Not covered: {v.coverage.current_medicines_not_covered.join(", ")}.</div>
                )}
              </div>
              <ExplainPanel caseId={id} resultHash={v.result_sha256} />
            </div>
          </div>

          <LivePanel caseId={id} initial={env?.live} country={env?.input.country ?? null} asOf={env?.input.dispense_date ?? null} />
          <ModelCalls result={result} />
        </>
      )}
    </div>
  );
}
