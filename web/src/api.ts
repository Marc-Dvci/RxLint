export type State = "PASS" | "REVIEW" | "CANNOT_VERIFY" | "OUT_OF_SCOPE";

export interface Calc {
  name: string;
  formula: string;
  inputs: Record<string, string>;
  value: string;
  unit: string;
  steps: string[];
  evidence_id?: string;
}

export interface SourceView {
  ref: string;
  title?: string | null;
  edition?: string | null;
  url?: string | null;
  license?: string | null;
  locator?: unknown;
  quotes: string[];
}

export interface Finding {
  finding_id: string;
  rule_id: string;
  rule_version: string;
  title: string;
  type: string;
  status: "pass" | "fail" | "cannot_evaluate" | "not_applicable" | "out_of_scope";
  severity: string | null;
  message: string;
  facts: Record<string, unknown>;
  evidence: string[];
  calculations: Calc[];
  missing: string[];
  action: string;
  source: { primary?: SourceView; related?: SourceView[]; explain?: string | null };
  policies: string[];
}

export interface Evidence {
  id: string;
  kind: string;
  name: string;
  value: unknown;
  unit?: string | null;
  raw?: string | null;
  status: string;
  source?: { asset_id?: string | null; bbox?: number[] | null; grounding?: string | null } | null;
  method?: string | null;
  confidence?: number | null;
  formula?: string | null;
  parents: string[];
  notes: string[];
}

export interface Verification {
  state: State;
  summary: Record<string, number>;
  findings: Finding[];
  coverage: {
    interaction_pairs: number;
    current_medicines_covered: string[];
    current_medicines_not_covered: string[];
    current_medicines_unrecognised: string[];
  };
  clarification: Clarification | null;
  snapshot_sha256: string;
  rulepack: { id: string; version: string; title: string; sha256: string; rules: number };
  engine: string;
  result_sha256: string;
  evidence: Record<string, Evidence>;
}

export interface Clarification {
  action: string;
  fields: string[];
  message?: string;
  reason?: string;
  source: string;
  model?: string;
  model_rejected?: unknown;
}

export interface Observation {
  field: string;
  text: string;
  asset_id: string | null;
  bbox?: number[] | null;
  grounding?: string | null;
  corroboration?: string;
  ocr_text?: string | null;
  confidence?: number;
  legible?: boolean;
  alternatives?: string[];
  requires_confirmation?: boolean;
  method?: string;
}

export interface ModelCall {
  role: string;
  model: string;
  provider: string;
  purpose: string;
  latency_ms: number;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  ok: boolean;
  replayed: boolean;
  recorded_at: string | null;
  error: string | null;
}

export interface QualityCheck {
  id: string;
  ok: boolean;
  value: unknown;
  message: string;
}

export interface Asset {
  id: string;
  kind: string;
  filename?: string | null;
  mime: string;
  sha256: string;
  size: number;
}

export interface CaseResult {
  case_id: string;
  assets: Asset[];
  quality: Record<string, { checks: QualityCheck[]; ok: boolean; width: number; height: number }>;
  extractions: { asset_id: string; kind?: string; kind_corrected?: boolean; model?: string; provider?: string; replayed?: boolean; latency_ms?: number; error?: string | null; untrusted_instructions_seen?: boolean; legibility?: string }[];
  observations: Observation[];
  verification: Verification;
  clarification: Clarification | null;
  model_calls: ModelCall[];
  timings_ms: Record<string, number>;
  untrusted_text_flagged: boolean;
}

export interface Notice {
  source: string;
  authority: string;
  url: string;
  title: string;
  published_at?: string | null;
  match_type: string;
  matched_fields: string[];
  listed_lots: string[];
  snippet: string;
  recall_number?: string;
  reason?: string;
  classification?: string;
}

export interface LiveResult {
  status: "LIVE_CLEAR" | "LIVE_REVIEW" | "LIVE_UNAVAILABLE" | "LIVE_NOT_CONFIGURED";
  reason?: string;
  statement?: string | null;
  country?: string | null;
  as_of?: string | null;
  retrieved_at: string;
  notices: Notice[];
  searches: { source: string; query?: string; ok: boolean; results?: number; error?: string; domains?: string[]; rejected_off_allowlist?: number }[];
  errors?: string[];
  query_policy: string;
  target: { product: string | null; lot: string | null };
}

export interface Explanation {
  language: string;
  direction: "ltr" | "rtl";
  audience: string;
  state: State;
  state_label: string;
  action: string;
  text: string;
  source: "model" | "deterministic";
  model?: string;
  provider?: string;
  replayed?: boolean;
  integrity?: { ok: boolean; checks?: string[]; problems?: string[] };
  model_rejected?: { text: string; problems: string[] };
  model_error?: string;
}

export interface CaseEnvelope {
  input: {
    case_id: string;
    assets: Asset[];
    patient: Record<string, string>;
    confirmations: Record<string, string>;
    country: string | null;
    dispense_date: string | null;
    meta?: { demo?: DemoCase };
  };
  status: "running" | "done";
  result?: CaseResult;
  live?: LiveResult;
  events: string[];
}

export interface DemoCase {
  id: string;
  title: string;
  summary: string;
  expect: State;
  patient: Record<string, string>;
  country: string;
  dispense_date: string;
  tags: string[];
}

export interface Health {
  status: string;
  rulepack: { id: string; version: string; sha256: string; rules: number; title: string; effective_date: string };
  models: Record<string, { model: string; provider: string; configured: boolean }>;
  perception: { mode: "omni" | "two_stage"; readers: string[] };
  model_mode: string;
  tavily: { configured: boolean };
  languages: Record<string, { name: string; dir: string }>;
  countries: Record<string, string>;
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* body was not JSON */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then((r) => j<Health>(r)),
  demoCases: () => fetch("/api/demo-cases").then((r) => j<DemoCase[]>(r)),
  createDemo: (id: string) => {
    const fd = new FormData();
    fd.append("demo_id", id);
    return fetch("/api/cases", { method: "POST", body: fd }).then((r) => j<{ case_id: string }>(r));
  },
  createCase: (fd: FormData) => fetch("/api/cases", { method: "POST", body: fd }).then((r) => j<{ case_id: string }>(r)),
  getCase: (id: string) => fetch(`/api/cases/${id}`).then((r) => j<CaseEnvelope>(r)),
  confirm: (id: string, confirmations: Record<string, string>) =>
    fetch(`/api/cases/${id}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmations }) }).then((r) => j<CaseResult>(r)),
  explain: (id: string, language: string, audience: string) =>
    fetch(`/api/cases/${id}/explain`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ language, audience }) }).then((r) => j<Explanation>(r)),
  live: (id: string) => fetch(`/api/cases/${id}/live`, { method: "POST" }).then((r) => j<LiveResult>(r)),
  rulepack: () => fetch("/api/rulepack").then((r) => j<RulePackView>(r)),
  driftLast: () => fetch("/api/rulepack/drift").then((r) => j<Record<string, unknown>>(r)),
  drift: () => fetch("/api/rulepack/drift", { method: "POST" }).then((r) => j<Record<string, unknown>>(r)),
  bench: () => fetch("/api/bench").then((r) => j<Record<string, unknown>>(r)),
  assetUrl: (caseId: string, assetId: string) => `/api/cases/${caseId}/assets/${assetId}`,
  demoAssetUrl: (id: string, name: string, width?: number) => `/api/demo-cases/${id}/${name}${width ? `?w=${width}` : ""}`,
};

export interface RuleView {
  id: string;
  version: string;
  title: string;
  type: string;
  severity: string;
  requires: string[];
  params: Record<string, unknown>;
  applies_to: Record<string, unknown>;
  source: { ref: string; locator: unknown; quote: string | string[] | null };
  related_sources: { ref: string; locator: unknown; quote: string | string[] | null }[];
  explain: string | null;
  quote_verified: boolean | null;
}

export interface RulePackView {
  id: string;
  version: string;
  title: string;
  sha256: string;
  summary: string;
  effective_date: string;
  scope: Record<string, unknown>;
  policies: Record<string, { title: string; value?: number; text: string }>;
  sources: Record<string, Record<string, unknown>>;
  quotes_checked: number;
  quotes_verified: number;
  rules: RuleView[];
}
