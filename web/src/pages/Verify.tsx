import { useEffect, useRef, useState } from "react";
import { api, type DemoCase } from "../api";
import { STATE_META, fieldLabel } from "../labels";
import { IBottle, IMic, IRx, IUser } from "../icons";

function go(id: string) {
  window.location.hash = `#/case/${id}`;
}

function DemoLibrary() {
  const [cases, setCases] = useState<DemoCase[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.demoCases().then(setCases).catch((e) => setErr(String(e)));
  }, []);
  const run = async (id: string) => {
    setBusy(id);
    setErr(null);
    try {
      const { case_id } = await api.createDemo(id);
      go(case_id);
    } catch (e) {
      setErr(String(e));
      setBusy(null);
    }
  };
  return (
    <section className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h2>Demo library</h2>
          <p className="muted small">Photographed prescriptions and bottles. Running one executes the full pipeline.</p>
        </div>
      </div>
      {err && <div className="error">{err}</div>}
      <div className="demo-grid">
        {cases.map((c) => {
          const tone = STATE_META[c.expect].tone;
          return (
            <button key={c.id} className="demo" onClick={() => run(c.id)} disabled={!!busy}>
              <div className="thumbs">
                <img src={api.demoAssetUrl(c.id, "rx.jpg", 360)} alt="" loading="lazy" />
                <img src={api.demoAssetUrl(c.id, "label.jpg", 360)} alt="" loading="lazy" />
              </div>
              <div className="body">
                <div className="ttl">
                  <span className="id">{c.id}</span>
                  <span style={{ flex: 1 }}>{c.title}</span>
                  {busy === c.id ? <span className="spinner" /> : <span className={`badge t-${tone}`}>{STATE_META[c.expect].short}</span>}
                </div>
                <p>{c.summary}</p>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function Capture({ label, icon, file, onFile, hint }: { label: string; icon: React.ReactNode; file: File | null; onFile: (f: File | null) => void; hint: string }) {
  const ref = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) return setUrl(null);
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  return (
    <div className={`capture ${file ? "filled" : ""}`} onClick={() => ref.current?.click()} role="button" tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && ref.current?.click()}>
      <input ref={ref} type="file" accept="image/*" capture="environment" hidden onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
      {url ? (
        <>
          <img src={url} alt={label} />
          <div className="over">
            <span className="chip">{label}</span>
            <button className="btn small" onClick={(e) => { e.stopPropagation(); onFile(null); }}>Remove</button>
          </div>
        </>
      ) : (
        <>
          <span className="ico">{icon}</span>
          <div style={{ fontWeight: 650 }}>{label}</div>
          <div className="muted small">{hint}</div>
        </>
      )}
    </div>
  );
}

const ALLERGY_CHIPS = ["none", "penicillin", "cephalosporins", "sulfa drugs", "macrolides"];
const MED_CHIPS = ["none", "paracetamol", "ibuprofen", "warfarin", "methotrexate"];

function NewCase() {
  const [rx, setRx] = useState<File | null>(null);
  const [rxMode, setRxMode] = useState<"photo" | "fhir">("photo");
  const [fhirText, setFhirText] = useState("");
  const [fhirPreview, setFhirPreview] = useState<{ observations: { field: string; text: string }[]; note: string } | null>(null);
  const [fhirError, setFhirError] = useState<string | null>(null);
  const fhirLoad = useRef(0);
  const [med, setMed] = useState<File | null>(null);
  const [voice, setVoice] = useState<File | null>(null);
  const [recording, setRecording] = useState(false);
  const recRef = useRef<MediaRecorder | null>(null);
  const [f, setF] = useState({ weight: "", age: "", allergies: "", medications: "", indication: "" });
  const [country, setCountry] = useState("FR");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [voiceOk, setVoiceOk] = useState(false);
  const set = (k: keyof typeof f) => (v: string) => setF((p) => ({ ...p, [k]: v }));

  useEffect(() => {
    api.health().then((h) => setVoiceOk(Boolean(h.voice))).catch(() => setVoiceOk(false));
  }, []);

  const toggleRecord = async () => {
    if (recording) {
      recRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setVoice(new File(chunks, "note.webm", { type: rec.mimeType || "audio/webm" }));
        setRecording(false);
      };
      recRef.current = rec;
      rec.start();
      setRecording(true);
    } catch {
      setErr("Microphone is not available in this browser.");
    }
  };

  const submit = async () => {
    setBusy(true);
    setErr(null);
    const fd = new FormData();
    if (rxMode === "photo" && rx) fd.append("prescription", rx);
    if (rxMode === "fhir") fd.append("fhir", fhirText);
    if (med) fd.append("medicine", med);
    if (voice) fd.append("audio", voice);
    fd.append("patient", JSON.stringify({
      "patient.weight": f.weight ? (/[a-z]/i.test(f.weight) ? f.weight : `${f.weight} kg`) : "",
      "patient.age": f.age, "patient.allergies": f.allergies, "patient.medications": f.medications, "patient.indication": f.indication,
    }));
    fd.append("country", country);
    try {
      const { case_id } = await api.createCase(fd);
      go(case_id);
    } catch (e) {
      setErr(String(e));
      setBusy(false);
    }
  };

  return (
    <section className="stack">
      <div>
        <h2>New verification</h2>
        <p className="muted small">Photograph the prescription or import a FHIR order, attach the bottle photo, then add patient context.</p>
      </div>
      <div className="grid3">
        <div className="stack" style={{ gap: 8 }}>
          <div className="seg" aria-label="Prescription source">
            <button className={rxMode === "photo" ? "on" : ""} onClick={() => setRxMode("photo")}>Photo</button>
            <button className={rxMode === "fhir" ? "on" : ""} onClick={() => setRxMode("fhir")}>FHIR prescription</button>
          </div>
          {rxMode === "photo" ? <Capture label="Prescription" icon={<IRx />} file={rx} onFile={setRx} hint="Printed or handwritten" /> : (
            <div className="card pad stack" style={{ gap: 10 }}>
              <b>Import a FHIR R4 prescription</b>
              <input aria-label="FHIR prescription file" type="file" accept=".json,application/json,application/fhir+json" onChange={async (e) => {
                const loadId = ++fhirLoad.current;
                const file = e.target.files?.[0];
                setFhirPreview(null); setFhirError(null); setFhirText("");
                if (!file) return;
                if (file.size > 512 * 1024) { setFhirError("Use a JSON file smaller than 512 KB."); return; }
                try {
                  const text = await file.text();
                  const resource: unknown = JSON.parse(text);
                  const preview = await api.validateFhir(resource);
                  if (loadId !== fhirLoad.current) return;
                  setFhirText(text); setFhirPreview(preview);
                } catch (error) { if (loadId === fhirLoad.current) setFhirError(String(error)); }
              }} />
              <span className="tiny muted">One active MedicationRequest, with a fixed dose and schedule. Include its Medication in the Bundle or contained resources for concentration.</span>
              {fhirError && <div className="error">{fhirError}</div>}
              {fhirPreview && <>
                <dl className="small">{fhirPreview.observations.map((o) => <div key={o.field}><dt>{fieldLabel(o.field)}</dt><dd>{o.text}</dd></div>)}</dl>
                <span className="tiny muted">Imported as supplied. Verify patient context separately.</span>
              </>}
            </div>
          )}
        </div>
        <Capture label="Medicine" icon={<IBottle />} file={med} onFile={setMed} hint="Front label with strength, lot and expiry" />
        <div className="card pad stack" style={{ gap: 12 }}>
          <div className="row" style={{ gap: 8 }}><IUser className="ico" /><b>Patient context</b></div>
          <div className="row" style={{ gap: 10, flexWrap: "nowrap" }}>
            <label className="field" style={{ flex: 1 }}>Weight (kg)<input className="input" value={f.weight} onChange={(e) => set("weight")(e.target.value)} placeholder="9.5" inputMode="decimal" /></label>
            <label className="field" style={{ flex: 1 }}>Age<input className="input" value={f.age} onChange={(e) => set("age")(e.target.value)} placeholder="14 months" /></label>
          </div>
          <label className="field">Known allergies<input className="input" value={f.allergies} onChange={(e) => set("allergies")(e.target.value)} placeholder="none" /></label>
          <div className="quick">{ALLERGY_CHIPS.map((c) => <button key={c} className={f.allergies === c ? "on" : ""} onClick={() => set("allergies")(c)}>{c}</button>)}</div>
          <label className="field">Current medicines<input className="input" value={f.medications} onChange={(e) => set("medications")(e.target.value)} placeholder="none" /></label>
          <div className="quick">{MED_CHIPS.map((c) => <button key={c} className={f.medications === c ? "on" : ""} onClick={() => set("medications")(c)}>{c}</button>)}</div>
          <div className="row" style={{ gap: 10, flexWrap: "nowrap" }}>
            <label className="field" style={{ flex: 1 }}>Indication (optional)<input className="input" value={f.indication} onChange={(e) => set("indication")(e.target.value)} placeholder="otitis media" /></label>
            <label className="field" style={{ width: 110 }}>Country
              <select className="input" value={country} onChange={(e) => setCountry(e.target.value)}>
                {["FR", "US", "GB", "KE", "NG", "BR"].map((c) => <option key={c}>{c}</option>)}
              </select>
            </label>
          </div>
          {voiceOk ? (
            <>
              <button className="btn small" onClick={toggleRecord} type="button">
                <IMic /> {recording ? "Stop recording" : voice ? "Re-record voice note" : "Speak patient facts"}
              </button>
              {voice && <span className="chip">Voice note attached</span>}
            </>
          ) : (
            <span className="tiny muted" title="Token Factory serves no audio model">
              <IMic /> Voice notes run where Nemotron 3 Nano Omni is served (a Nebius AI Cloud endpoint or llama.cpp).
            </span>
          )}
        </div>
      </div>
      {err && <div className="error">{err}</div>}
      <div className="row">
        <button className="btn primary" disabled={busy || (rxMode === "photo" ? (!rx && !med) : (!fhirPreview || !med))} onClick={submit}>
          {busy ? <span className="spinner" /> : null} Verify
        </button>
        <span className="muted small">Images are hashed on arrival. Patient names are never needed.</span>
      </div>
    </section>
  );
}

export default function Verify() {
  return (
    <div className="page stack" style={{ gap: 28 }}>
      <div className="page-head">
        <div>
          <h1>Check the medicine against the prescription</h1>
          <p>
            NVIDIA Nemotron reads the photos. A deterministic kernel checks identity, concentration, weight-based dose,
            duration, allergies and interactions against a versioned WHO AWaRe rule pack. Every finding links to the pixels,
            the arithmetic and the rule that produced it.
          </p>
        </div>
      </div>
      <DemoLibrary />
      <div className="divider" />
      <NewCase />
    </div>
  );
}
