# External review implementation audit

The revised reader improves dose, weight, concentration and expiry extraction on the original
test fold, with seven fewer confirmation requests and zero incorrect high-risk accepts.
Batch confirmation and fixed FHIR R4 import are implemented; the tables below retain every
measured tradeoff and the separate public-photo pilot.

Baseline: commit 7887bb5; 218 tests pass before changes. The committed Token Factory Nano
benchmark uses 330 cases, including the fixed 120-case test fold. Original test confirmation
rate: 50.83%; exact verdict after simulated pharmacist confirmation: 95.83%.

The implementation follows the external review's remaining-work list. Acceptance requires measured
results, preserved fail-closed behavior, reproducible evaluation and candid dataset provenance.

## Decisions

- Evaluate current PP-OCRv6 rather than the review's older PP-OCRv4 recommendation.
- A focused vision re-read remains dependent on the original vision reader. It can correct an
  extraction only with independent OCR agreement, never waive corroboration or erase genuine
  ambiguity based on majority voting.
- Reliability thresholds are selected on validation data only. Test false-accept counts are
  reported outcomes, never optimization constraints.
- Structured FHIR input is an explicitly supplied prescription, not authenticated medical data.
  Unsupported schedules and ambiguous quantities must fail closed. Imported data gets its own
  evidence provenance and never imports a clinical verdict.
- Public medicine photographs are a perception-only external evaluation. They cannot be
  advertised as paired clinical cases or as prospective validation.

## Work tracking

| Review item | Status |
| --- | --- |
| Stronger OCR | Implemented: pinned RapidOCR 3.9.2, PP-OCRv6 bundled ONNX models; legacy comparison available |
| Targeted disputed-field reader | Implemented: at most three crop calls per image; independent OCR agreement required |
| Validation-only friction/safety threshold | Implemented and retrained; threshold 0.9000000000000001, zero validation false-accept budget |
| Batch confirmation | Implemented and browser-tested with two missing fields confirmed in one request |
| FHIR prescription import | Implemented, tested through the kernel, HTTP API and browser; JSON-path provenance |
| Real photograph evaluation | 12 genuine public photos evaluated; 30–50 paired clinical cases remain unavailable |
| English/French extraction examples | Implemented and measured on the original train/validation/test folds |
| Deterministic field validation | Implemented, including expiry day ambiguity, pediatric ranges and incomplete ingredient lists |
| Optional dual reader | Implemented and regression-tested; runtime evaluation needs an Omni endpoint |
| Audit and measured before/after results | Complete; frozen artifacts and honest tradeoffs published |

## Fixed-fold results

No new synthetic cases were created. The original manifest still has 150 training, 60 validation
and 120 test cases. The selected head and threshold were frozen before test extraction; hashes
are in `benchmarks/results/review_selection.json`. Test reporting does not refit the head.

| Metric, original 120-case test fold | Before | After |
| --- | --- | --- |
| Confirmation requests | 61/120 (50.83%) | 54/120 (45.0%) |
| Wrong high-risk readings through the head | 2 | 0 |
| Ambiguous doses held after simulated confirmation | 8/10 | 9/10 |
| Dose exact reading | 70.0% | 82.5% |
| Weight exact reading | 72.5% | 85.0% |
| Label strength exact reading | 80.0% | 93.3% |
| Expiry exact reading | 75.0% | 84.2% |
| Exact verdict after simulated confirmation | 115/120 (95.83%) | 114/120 (95.0%) |
| Clean PASS after simulated confirmation | 40/40 | 38/40 |
| False-safe, before and after confirmation | 0/80 | 0/80 |

The final head has test AUC 0.9805, versus 0.951 in the original report. It sees 677 high-risk
readings, including 69 incorrect ones; the earlier reader produced 566, including 42 incorrect
ones. Extraction completeness changed, so reading-level denominators are not identical.
The four field-accuracy comparisons above use the same 120 case-field denominators. Accuracy
after confirmation dropped one case and clean-case acceptance dropped two; these regressions
are retained in the report. No test-driven threshold adjustment was made.

Validation selected the zero-error budget: 46.67% case confirmations, 96.67% exact verdict after
simulated review and 5/5 ambiguous doses held. The one-error budget saved one additional
confirmation but fell to 95% exact verdict after review. The Qwen 3.8 27B alternative produced
a false-safe validation verdict and was rejected. Only train/validation experiments informed
reader selection. See `benchmarks/artifacts/review-v4/README.md` for reproduction.

## Resolved audit findings

- OCR failure previously skipped corroboration; it now explicitly blocks high-risk readings.
- A duplicate machine observation could waive a reliability veto. Only matching explicit
  structured/user evidence can now satisfy it, with pharmacist confirmation taking precedence.
- Expiry parsing could discard a day or ignore a second date. It now requires a complete,
  unambiguous date; month-only expiry retains the last day of that month.
- Token Factory template kwargs did not reliably stop vision reasoning. The documented
  top-level `reasoning_effort=none` avoids empty transcripts from exhausted reasoning budgets.
- Pathological repeated transcript lines are bounded without altering normal repetitions.
- Trademark normalization could turn `Amoxil™` into `AmoxilTM`. Marks are removed before NFKC.
- Partial ingredient lines could hide a combination product. Unfinished separators are
  unresolved; competing transcript ingredients block medicine identity and concentration.
  A post-freeze audit corrected a false conflict when a combination separately names its own
  ingredients. No test verdicts had been inspected; model/threshold bytes stayed unchanged.
- Cassette keys now distinguish models, endpoint and generation settings. Historical offline
  replay remains supported; live comparisons cannot silently reuse a different model/settings.
- Partial folds cannot be used to publish test summaries or fit calibration.
- Malformed FHIR, conditional regimens, mismatched ingredient order and unsupported quantity
  semantics fail before a run starts. Unknown confirmation fields and invalid dates return 400.
- Partial batch confirmations now use deterministic follow-up questions, so confirmation
  never spends another inference call, even while additional fields remain unresolved.
- The medicine viewer now opens correctly when the prescription is structured JSON. A stale
  asynchronous file preview cannot overwrite a newly selected FHIR file.

## External photographs and remaining evidence

The 12-image Wikimedia convenience sample has per-file licenses, author attribution, source URLs
and SHA-256 hashes. Three additional unannotated candidates are excluded. Exact readings: drug
8/10, strength 4/9 and volume 5/6. Strength separates into 4/5 liquid and 0/4 solid values; all
subgroups are reported. No wrong evaluated fields were accepted by the parser/gates. One failed
negative-control transcription remains in the report rather than being dropped.

This is a **development pilot**: bugs were diagnosed from its outputs. It has one visual
annotator, no pharmacist adjudication, correlated photographers, no prescriptions paired with
bottles and no patient data. It cannot establish real-world verdict accuracy. The requested
30–50 paired clinical cases remain future evidence work. Public images were not used for
training, calibration or threshold selection. RxHandBD version 3 (CC BY 4.0) is a downloadable
source for genuine handwriting word crops, not complete dispensing pairs; download details are
in `benchmarks/real_world/README.md`.

## Verification and delivery

251 Python tests pass, including the new import, corroboration, confirmation and calibration
boundaries; the React/TypeScript production build passes. Browser checks covered A/D/G/F, mobile
layout, explanations, reports and a FHIR order with two missing fields confirmed together. No
JavaScript page errors occurred; one remote font request was denied by the network sandbox.
The ten rendered demo cases were checked; a false ingredient conflict in I was corrected and
I rechecked successfully. All ten default photographed demo cases also match their expected
verdicts with the final head and refreshed recording. The frozen model bytes are preserved
across Windows/Linux checkouts while retaining the repository's existing line-ending rules.

All changes are local. The hosted service, GitHub repository and Devpost submission have not
been published by this task. The existing demo video and old screenshots describe the prior
version; the benchmark figure and submission text are updated locally. A new recording should
show FHIR preview, grouped confirmation, the improved gate metrics and the public-photo limits.
