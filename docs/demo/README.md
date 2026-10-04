# RxLint demo recording

The [177-second submission video and captions](https://github.com/Marc-Dvci/RxLint/releases/tag/submission-demo)
show the interface, confirmation flow and frozen benchmark results. All patients and
demo labels are fictional; model responses and the case I Tavily result are recorded and
identified as such by the app.

The first two sentences introduce RxLint, its pharmacist and clinic-nurse users, and the
value of checking the bottle against the prescription with inspectable evidence. The
concentration example follows at 00:15; the working verification begins at 00:27.
Narration is normalized to -14 LUFS for playback; video frames and cue timing are preserved.

To reproduce it, install the project's development dependencies, `edge-tts==7.2.8`, ffmpeg and
Playwright Chromium, build the web app, then run a local server on port 8011 in replay mode:

```bash
PYTHONPATH=src RXLINT_MODEL_MODE=replay RXLINT_LOAD_DOTENV=0 RXLINT_DATA=data/demo-recording \
  uvicorn rxlint.api.app:app --port 8011
python docs/demo/narrate.py
python docs/demo/export_captions.py
python docs/demo/record.py --stills
```

`narrate.py` measures sentence boundaries from the synthesized speech. `record.py` drives the
working app on a virtual clock, renders 1920×1080 H.264/AAC at 30 fps, and fails if the tour
cannot find an expected control. `timing.json` records the measured timings for the published
version. Speech-service output can vary; the attached MP4 and SRT are the final artifacts.
Their hashes, duration, frame count and tour checks are recorded in [artifacts.json](artifacts.json).
