export default function About() {
  return (
    <div className="page stack" style={{ gap: 22 }}>
      <div className="page-head">
        <div>
          <h1>How RxLint works</h1>
          <p>
            A compiler does not ask whether code sounds plausible. It parses the input, applies deterministic rules, points at the
            exact location of a violation, and refuses to declare success when information is missing. RxLint does the same for the
            medicine handed to a child.
          </p>
        </div>
      </div>

      <div className="arch">
        <div className="node nv">
          <span className="upper">Reads</span>
          <b>Transcription + Nemotron 3 Nano</b>
          <span className="small muted">A vision model on Token Factory transcribes the photo line by line. Nemotron 3 Nano assigns lines to fields, and every value must be copied verbatim from the line it cites. Where Nemotron 3 Nano Omni is served, it reads the photo in one call.</span>
        </div>
        <div className="node det">
          <span className="upper">Corroborates</span>
          <b>PP-OCRv6 + reliability head</b>
          <span className="small muted">Independent OCR checks high-risk photo readings, focused crops recover small print, and a calibrated head refers uncertain values for confirmation. Conflicting readings require an explicit choice.</span>
        </div>
        <div className="node det">
          <span className="upper">Proves</span>
          <b>Deterministic kernel</b>
          <span className="small muted">Strict unit grammar, decimal arithmetic, 59 versioned rules transcribed from WHO AWaRe and FDA labels. Same snapshot, same hash.</span>
        </div>
        <div className="node nv">
          <span className="upper">Clarifies and explains</span>
          <b>Nemotron 3 Ultra</b>
          <span className="small muted">Picks the smallest clarification from a closed set. All reviewed values can be confirmed together without another model call. Explanations use locked values and a Nano audit in English, French and Arabic; Swahili uses reviewed phrases.</span>
        </div>
      </div>

      <div className="card pad stack" style={{ gap: 8 }}>
        <h2>Bring the prescription directly from a structured order</h2>
        <p className="small">FHIR R4 MedicationRequest import supplies fixed medicine, concentration, dose and schedule facts with JSON-path evidence.
          Upload the bottle photo and add patient context to run the same deterministic checks. Unsupported conditional orders are rejected.</p>
      </div>

      <div className="card pad stack" style={{ gap: 10 }}>
        <h2>Two planes, never merged</h2>
        <div className="grid2">
          <div className="stack" style={{ gap: 6 }}>
            <span className="badge t-pass" style={{ justifySelf: "start" }}>PLANE A · VERIFIED RULES</span>
            <p className="small">Prescription + medicine + patient → structured evidence → deterministic kernel → PASS, REVIEW, CANNOT VERIFY or OUT OF SCOPE.
              The rule pack is hashed; the report records the hash.</p>
          </div>
          <div className="stack" style={{ gap: 6 }}>
            <span className="badge t-live" style={{ justifySelf: "start" }}>PLANE B · LIVE INTELLIGENCE</span>
            <p className="small">Identified product + lot + country → Tavily Search restricted to the country's regulators → Extract on a shortlist →
              deterministic lot and product matching → LIVE REVIEW, LIVE CLEAR or LIVE UNAVAILABLE. A web page never edits a rule.</p>
          </div>
        </div>
      </div>

      <div className="grid2">
        <div className="card pad stack" style={{ gap: 8 }}>
          <h2>What a model may and may not do</h2>
          <table className="tbl"><tbody>
            <tr><td>Transcribe text and speech</td><td><span className="badge t-pass">yes</span></td></tr>
            <tr><td>Report competing readings of a smudged digit</td><td><span className="badge t-pass">yes</span></td></tr>
            <tr><td>Choose a clarification from a closed list</td><td><span className="badge t-pass">yes</span></td></tr>
            <tr><td>Write the sentences around locked values</td><td><span className="badge t-pass">yes</span></td></tr>
            <tr><td>Convert units or compute a dose</td><td><span className="badge t-review">no</span></td></tr>
            <tr><td>Decide PASS or REVIEW</td><td><span className="badge t-review">no</span></td></tr>
            <tr><td>Turn a web page into a rule</td><td><span className="badge t-review">no</span></td></tr>
            <tr><td>Write a number in an explanation</td><td><span className="badge t-review">no</span></td></tr>
          </tbody></table>
        </div>
        <div className="card pad stack" style={{ gap: 8 }}>
          <h2>Scope of this pack</h2>
          <p className="small">Seven oral antibiotic products for children aged 28 days to 12 years: amoxicillin, amoxicillin+clavulanic acid,
            cefalexin, azithromycin, clarithromycin, phenoxymethylpenicillin and sulfamethoxazole+trimethoprim. Doses and durations come
            from the WHO AWaRe antibiotic book (2022), Table 50.1 and the infection chapters; allergy and interaction rules come from
            FDA prescribing information. Interactions outside the 13 encoded pairs are listed as not covered.</p>
          <p className="small muted">A PASS means no discrepancy was detected within this pack. It is not a statement that a treatment is safe or appropriate.
            RxLint does not diagnose, choose antibiotics or change a dose. Research prototype, not approved for clinical use.</p>
        </div>
      </div>
    </div>
  );
}
