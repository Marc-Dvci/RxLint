# External medicine photograph pilot

These are genuine photographs downloaded from Wikimedia Commons, with no synthetic camera
transformations or generated images. Every image directory contains the original downloaded
bytes, a SHA-256 checksum, the author's attribution, the exact source page and per-file license.
Image licenses apply independently of the code's Apache-2.0 license. Redistribute attribution
and comply with the recorded CC BY/CC BY-SA terms. No patient prescription labels are used.

Ground truth records only text that is visibly readable. `gold_rx` is empty, and
`expected_state` is null: **these are not paired clinical dispensing cases**. Do not fill in a
fictional prescription or patient and report that result as real-world clinical performance.
Bare pill photos serve as negative controls for invented strength/expiry/lot values.

Annotations were made by visual inspection, before running the reader, by a single coding
agent; there is no independent pharmacist adjudication. The evaluated sample includes adult packaging,
French text, multiple bottles, oblique angles and curved labels. Several photos
share a photographer and backdrop; the dataset is small and is not statistically independent.

Run the same production perception and reliability gates:

```powershell
$env:PYTHONPATH='src'
.\.venv\Scripts\python.exe -m rxlint.bench.real_world --run review-v4 --mode replay
```

To add a genuine paired case, provide `rx.jpg`, `label.jpg`, provenance and manually adjudicated
`ground_truth.json` in a new directory. Explicitly annotate unreadable/ambiguous fields and
do not derive unseen facts from filenames, drug databases or the reader's output. Keep this
dataset outside training, calibration and threshold selection.

There are 12 evaluated images (10 readable medicine packages and 2 bare-pill negative controls).
Three additional downloaded candidates have no `ground_truth.json` and are excluded from evaluation.
Failures remain in the evaluation denominator. The published pilot is a development evaluation:
transport, trademark and ingredient-conflict bugs were found while inspecting its outputs. It is
not an untouched external holdout. Individual source pages, authors, licenses and checksums are
recorded in `provenance.json`; use `tools/collect_public_photos.py` to obtain additional candidates.

For freely reusable **genuine prescription handwriting**, download **RxHandBD-Raw.zip** or
**RxHandBD-ML.zip**, version 3, from [RxHandBD on Mendeley Data](https://data.mendeley.com/datasets/dsb5r6vskg/3)
(DOI 10.17632/dsb5r6vskg.3, Md Masudul Islam, CC BY 4.0). These contain prescription **word crops**,
not complete orders paired with dispensed bottles. Keep its published test split out of training
and retain author attribution. It is suitable for a separate handwriting-recognition experiment;
it cannot supply the missing dose regimen, patient context or a clinical verdict.

The review's target of 30–50 genuine paired dispensing cases still needs appropriately licensed,
de-identified prescription/bottle pairs and independent pharmacist annotation. Public bottle
photos and handwritten word crops do not fulfill that clinical-data requirement.
