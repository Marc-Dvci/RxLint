import type { State } from "./api";

export const FIELD_LABEL: Record<string, string> = {
  "rx.product": "Prescribed medicine",
  "rx.drug": "Prescribed medicine",
  "rx.strength": "Prescribed strength",
  "rx.dose": "Dose",
  "rx.frequency": "Frequency",
  "rx.duration": "Duration",
  "rx.duration_days": "Duration",
  "rx.indication": "Indication",
  "rx.route": "Route",
  "rx.dosage_form": "Prescribed form",
  "rx.patient_weight": "Weight on prescription",
  "rx.patient_age": "Age on prescription",
  "rx.allergies": "Allergies on prescription",
  "dispensed.product": "Medicine on the shelf",
  "dispensed.drug": "Medicine on the shelf",
  "dispensed.strength": "Label strength",
  "dispensed.dosage_form": "Label form",
  "dispensed.volume": "Pack volume",
  "dispensed.volume_ml": "Pack volume",
  "dispensed.lot": "Lot",
  "dispensed.expiry": "Expiry",
  "dispensed.manufacturer": "Manufacturer",
  "dispensed.gtin": "Product code",
  "patient.weight": "Weight",
  "patient.weight_kg": "Weight",
  "patient.age": "Age",
  "patient.age_months": "Age",
  "patient.allergies": "Allergies",
  "patient.medications": "Current medicines",
  "patient.current_medications": "Current medicines",
  "context.dispense_date": "Dispense date",
  "context.country": "Country",
};

export const STATE_META: Record<State, { label: string; short: string; tone: string; line: string }> = {
  PASS: { label: "No discrepancy found", short: "PASS", tone: "pass", line: "Every mandatory fact was present and every applicable rule in the pack passed." },
  REVIEW: { label: "Requires professional review", short: "REVIEW", tone: "review", line: "At least one deterministic rule failed." },
  CANNOT_VERIFY: { label: "Cannot verify", short: "CANNOT VERIFY", tone: "cannot", line: "Required evidence is missing, unreadable or contradictory. RxLint does not guess." },
  OUT_OF_SCOPE: { label: "Outside the installed pack", short: "OUT OF SCOPE", tone: "oos", line: "The case is outside the medicines, route or ages this pack covers." },
};

export const ACTION_LABEL: Record<string, string> = {
  REQUEST_NEW_PHOTO: "Retake the photo",
  REQUEST_FIELD_CONFIRMATION: "Confirm a reading",
  REQUEST_WEIGHT: "Enter the weight",
  REQUEST_AGE: "Enter the age",
  REQUEST_INDICATION: "Enter the indication",
  REQUEST_ALLERGY_CONFIRMATION: "Confirm the allergy history",
  REQUEST_MEDICATION_LIST: "List current medicines",
  professional_review_required: "Pharmacist review",
  none: "",
};

export const SEVERITY_ORDER = ["critical", "high", "moderate", "cannot_verify", "out_of_scope", "advisory"];

export function fieldLabel(key: string): string {
  return FIELD_LABEL[key] ?? key;
}

export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "string") return v;
  if (Array.isArray(v)) {
    if (v.length === 0) return "none";
    return v.map((x) => (typeof x === "object" && x && "raw" in x ? String((x as { raw: string }).raw) : String(x))).join(", ");
  }
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if ("components_mg" in o) {
      const c = (o.components_mg as string[]).map((x) => `${x} mg`).join(" / ");
      return o.per_ml ? `${c} per ${o.per_ml} mL` : `${c} per ${o.per_unit ?? "unit"}`;
    }
    if ("volume_ml" in o || "mass_mg" in o) {
      if (o.volume_ml) return `${o.volume_ml} mL`;
      if (o.mass_mg) return `${o.mass_mg} mg`;
      return `${o.units} ${o.unit_name}`;
    }
    if ("per_day" in o) return String(o.label ?? `${o.per_day}x/day`);
    return JSON.stringify(o);
  }
  return String(v);
}

export function productName(key: string | null | undefined): string {
  if (!key) return "";
  return key
    .split("+")
    .map((p) => p.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()))
    .join(" + ");
}

const INDICATION: Record<string, string> = {
  acute_otitis_media: "Acute otitis media", pharyngitis: "Pharyngitis", acute_sinusitis: "Acute sinusitis",
  cap_mild: "Community-acquired pneumonia (mild)", uti_lower: "Lower urinary tract infection", ssti_mild: "Mild skin infection",
};

/** Human rendering of a normalised fact value, with its unit. */
export function factValue(key: string, v: unknown): string {
  if (v === null || v === undefined) return "";
  if (key.endsWith(".product")) return productName(String(v));
  if (key === "rx.indication") return INDICATION[String(v)] ?? String(v);
  if (key === "patient.weight_kg") return `${v} kg`;
  if (key === "patient.age_months") {
    const m = Number(v);
    return m >= 24 && Number.isInteger(m / 12) ? `${m / 12} years` : `${v} months`;
  }
  if (key === "rx.duration_days") return `${v} days`;
  if (key === "dispensed.volume_ml") return `${v} mL`;
  if (key.endsWith("dosage_form")) return String(v).replace(/_/g, " ");
  return fmtValue(v);
}

export function modelName(m: string | null | undefined): string {
  if (!m) return "";
  if (/\.gguf$/i.test(m)) return "nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning (IQ4_XS GGUF)";
  return m;
}
