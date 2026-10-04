# RxLint evaluation and implementation audit

RxLint reaches **95.0% exact verdicts after simulated confirmation** on 120 held-out rendered
cases, holds **9/10 overwritten doses** for confirmation and accepts **zero incorrect high-risk
readings** across 677 evaluated readings. The workflow supports photographed prescriptions,
fixed FHIR R4 MedicationRequest import, evidence-linked findings and batch confirmation.

## Evaluation design

The fixed dataset contains 150 training, 60 validation and 120 test cases. Test cases hold out a
handwriting font, four photo perturbation families and one product. The test composition is
40 clean cases, 60 rule violations and 20 missing or overwritten facts. Every compared system
uses these cases and the same deterministic rule kernel.

The hosted reader uses DeepSeek V4.1 Flash for transcription and Nemotron 3 Nano for cited
structured fields. PP-OCRv6 independently corroborates high-risk readings. Focused crop reads
are bounded to three per image and cannot waive independent OCR agreement. A calibrated
LightGBM head adds confirmations using grammar, OCR agreement, plausibility and image evidence.
It is trained on the training fold and selected on validation with a zero false-accept budget.
The model and threshold (0.900) are frozen before test extraction; test results are reporting
outcomes, not selection criteria.

## Held-out results

| Metric | Result |
|---|---|
| Exact verdict after simulated confirmation | 114/120 (95.0%) |
| Clean cases returned PASS after simulated confirmation | 38/40 (95.0%) |
| Cases needing confirmation | 54/120 (45.0%) |
| Overwritten doses held after simulated confirmation | 9/10 |
| Error cases returned PASS, before and after confirmation | 0/80 at both stages |
| Incorrect high-risk readings accepted | 0 of 677 readings, including 69 incorrect readings |
| Reliability-head test AUC | 0.9805 |
| Exact prescription-dose reading | 82.5% |
| Exact patient-weight reading | 85.0% |
| Exact label-strength reading | 93.3% |
| Exact expiry reading | 84.2% |

| System | Exact verdict after confirmation | Error cases returned PASS after confirmation | Overwritten doses held |
|---|---|---|---|
| Reader output trusted as read | 85.8% | 4/80 | 3/10 |
| RxLint: OCR and reliability head | 95.0% | 0/80 | 9/10 |
| OCR + regex + same kernel | 92.5% | 1/80 | 6/10 |

False-safe means an error case returned as PASS. Confirmation is simulated from written ground
truth; 95.0% is not an autonomous clinical accuracy claim. The 120 rendered cases measure
prototype performance and do not establish clinical safety. Zero observed false-safe cases
does not establish a zero population risk. The gold-facts kernel result is an upper bound.

## Public-photo perception pilot

A separate development pilot contains 12 genuine public medicine photographs: ten packages
and two bare-pill controls, including one failed control read. Author attribution, licenses,
source URLs and SHA-256 hashes are retained for each photo.

| Field | Exact reading | Accepted by parser and gates | Incorrect accepted |
|---|---|---|---|
| Product identity | 8/10 | 8/10 | 0 |
| Strength | 4/9 | 3/9 | 0 |
| Volume | 5/6 | 4/6 | 0 |

Liquid concentration is exact on 4/5 packages and solid strength on 0/4. This pilot uses one
annotator and has no paired prescriptions or independent pharmacist adjudication. Paired
pharmacy cases and independent assessment are the next validation stage; solid-package reading
is a priority for broader coverage. [Dataset and provenance](../benchmarks/real_world/README.md).

## Implementation checks

**251 automated tests pass**, and all **ten demo cases** return their expected verdicts.
The suite covers rule boundaries, source quotes, units, grounded readings, explanation integrity,
live lot matching, FHIR import and confirmation. A browser check confirms that two missing fields
can be reviewed in one action without additional model calls. The Linux container also completes
all ten demos within the deployed 2 CPU / 2 GiB limits.

FHIR import accepts supported fixed MedicationRequest orders with JSON-path evidence. It rejects
unsupported conditional schedules and ambiguous quantities; import does not authenticate an order
or perform full FHIR conformance validation. Optional Omni and dual-reader paths have regression
coverage; their runtime performance is not included in the hosted benchmark.

## Reproduction and audit evidence

- [Frozen report](../benchmarks/results/bench_tf-review-v4-nano.json), including all five systems,
  every evaluated field and validation/test reading counts.
- [Per-case results](../benchmarks/results/cases_tf-review-v4-nano.json).
- [Frozen model selection](../benchmarks/results/review_selection.json).
- [Reproduction artifacts](../benchmarks/artifacts/review-v4/README.md), including manifests,
  image hashes, extractions and recorded responses. Reproduction does not require model fitting.
- [Public-photo results](../benchmarks/results/real_world/review-v4.json).

Development history and complete historical comparisons are preserved in
[the audit archive](audits/implementation_history.md) and the raw benchmark reports.
