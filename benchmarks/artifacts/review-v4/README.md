# Frozen RxLintBench evaluation

The 330-case RxLintBench manifest contains 150 training, 60 validation and 120 test cases.
`extractions/` contains both photographed
render readings, OCR text and boxes, crop resolutions and model identities for every case.
`model_cassette.jsonl` records the exact model responses. `image_hashes.json` identifies all
660 source images. These are synthetic images; public real photographs are evaluated separately.

The LightGBM head and threshold in `models/reliability/` were frozen before test extraction;
their hashes and validation selection are in `benchmarks/results/review_selection.json`.
The final evaluator measures the saved head and does not refit on test labels.

To reproduce, install the `bench` extras, generate RxLintBench v1 with the supplied renderer
and fonts, check all image hashes, copy the saved extractions into
`bench_out/v1/extractions/tf-review-v4-nano/`, then run:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m rxlint.bench.evaluate --bench bench_out/v1 --run tf-review-v4-nano
```

Use `benchmarks/results/bench_tf-review-v4-nano.json` for the full report and
`docs/implementation_audit.md` for the evaluation design, results and implementation checks.

The transcription prompt and transport setting were selected using training/validation
experiments. The rejected Qwen reader produced a false-safe validation case. A one-error
validation threshold budget reduced one additional confirmation but reduced reviewed verdict
accuracy, so the zero-error budget was chosen. The public-photo set was a development pilot,
not an untouched holdout. Model and manifest hashes are recorded in the selection report.
