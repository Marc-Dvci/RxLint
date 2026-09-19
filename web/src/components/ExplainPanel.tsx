import { useEffect, useState } from "react";
import { api, type Explanation } from "../api";

const LANGS = [
  { code: "en", label: "English" },
  { code: "fr", label: "Français" },
  { code: "ar", label: "العربية" },
  { code: "sw", label: "Kiswahili" },
];

export default function ExplainPanel({ caseId, resultHash }: { caseId: string; resultHash: string }) {
  const [lang, setLang] = useState("en");
  const [aud, setAud] = useState<"caregiver" | "professional">("caregiver");
  const [ex, setEx] = useState<Explanation | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setBusy(true);
    setErr(null);
    api.explain(caseId, lang, aud)
      .then((r) => live && setEx(r))
      .catch((e) => live && setErr(String(e)))
      .finally(() => live && setBusy(false));
    return () => { live = false; };
  }, [caseId, lang, aud, resultHash]);

  return (
    <div className="card">
      <div className="card-head">
        <h3>Explanation</h3>
        <div className="seg">
          <button className={aud === "caregiver" ? "on" : ""} onClick={() => setAud("caregiver")}>Caregiver</button>
          <button className={aud === "professional" ? "on" : ""} onClick={() => setAud("professional")}>Pharmacist</button>
        </div>
      </div>
      <div className="explain">
        <div className="seg" style={{ justifySelf: "start" }}>
          {LANGS.map((l) => <button key={l.code} className={lang === l.code ? "on" : ""} onClick={() => setLang(l.code)}>{l.label}</button>)}
        </div>
        {err && <div className="error">{err}</div>}
        {busy && !ex && <div className="row small muted"><span className="spinner" /> Writing the explanation…</div>}
        {ex && (
          <>
            <div className="text" dir={ex.direction} lang={ex.language} style={{ opacity: busy ? 0.5 : 1 }}>{ex.text}</div>
            <div className="row tiny muted" style={{ gap: 8 }}>
              {ex.source === "model" ? (
                <>
                  <span className="badge t-pass">integrity checked</span>
                  <span>Written by {ex.model}{ex.replayed ? " (recorded)" : ""}. Numbers, medicine names and the action come from the verified result.</span>
                </>
              ) : (
                <>
                  <span className="badge t-note">deterministic template</span>
                  <span>
                    {ex.model_rejected ? `Model text rejected: ${ex.model_rejected.problems.join("; ")}.` : "Phrase table in four languages; the verdict and the action are fixed text."}
                  </span>
                </>
              )}
            </div>
            <div className="tiny faint">The explanation describes an established result. It never changes a finding and never gives a new dose.</div>
          </>
        )}
      </div>
    </div>
  );
}
