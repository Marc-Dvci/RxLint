# Nemotron 3.5 Super VL as the transcriber

`nvidia/Nemotron-3.5-Super-VL` reached the Token Factory catalog after the hosted reader was
frozen. This run swaps it in as the `vision` model on the frozen validation and test folds and
changes nothing else: the same transcription prompt (`transcribe-v2`), Nemotron 3 Nano for
structuring, PP-OCRv6 corroboration, and the reliability head and threshold frozen in
`benchmarks/results/review_selection.json`. The head was not refit on these readings.

`extractions/` holds all 180 cases (60 validation, 120 test) and `model_cassette.jsonl` the 768
recorded responses. Results are in `benchmarks/results/bench_tf-review-v4-supervl.json`,
`cases_tf-review-v4-supervl.json` and
`reader_comparison_tf-review-v4-nano_vs_tf-review-v4-supervl.json`.

| Test fold, 120 cases, full RxLint pipeline | DeepSeek V4.1 Flash + Nano | Nemotron 3.5 Super VL + Nano |
|---|---|---|
| Error cases returned PASS after confirmation | 0/80 | 0/80 |
| Overwritten doses held | 9/10 | 10/10 |
| Exact verdict after confirmation | 114/120 (95.0%) | 111/120 (92.5%) |
| Clean cases PASS after confirmation | 38/40 | 37/40 |
| Cases needing confirmation | 54/120 | 51/120 |
| Wrong high-risk readings accepted by the head | 0 of 677 | 1 of 668 |
| Dose / weight / label strength / expiry exact | 82.5 / 85.0 / 93.3 / 84.2% | 83.3 / 86.7 / 94.2 / 85.0% |
| Readings trusted as read: false-safe after confirmation | 4/80 | 5/80 |

On validation, Super VL returned 0/40 false-safe verdicts, 59/60 exact verdicts after
confirmation and no wrong high-risk reading accepted, with 32/60 cases needing confirmation
(DeepSeek: 0/40, 58/60, none accepted, 28/60). Most of the extra validation confirmations are
expiry years: on blurred and low-resolution bottles Super VL reads the label's dotted zero in
"2027" as "2827", and OCR corroboration holds every one of those readings for confirmation.

The one accepted wrong reading is case rb0296: an occlusion covers part of the label strength,
Super VL reads "400 mg/57 mL" and the partial OCR line "400mg/57" agrees with it. The case still
ends REVIEW, because the misread strength fails the product checks. DeepSeek V4.1 Flash remains the
hosted transcriber because its frozen run accepted no wrong high-risk reading; setting
`RXLINT_VISION_MODEL=nvidia/Nemotron-3.5-Super-VL` runs the all-Nemotron configuration.

To reproduce, copy `extractions/` to `bench_out/v1/extractions/tf-review-v4-supervl/` and the
cassette to `bench_out/v1/extractions/tf-review-v4-supervl.cassette.jsonl`, then run:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m rxlint.bench.evaluate --bench bench_out/v1 --run tf-review-v4-supervl --no-summary
```
