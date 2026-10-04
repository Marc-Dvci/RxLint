"""Synthesise the narration in script.py and measure every sentence.

One Edge TTS synthesis per section, with sentence boundaries captured from the same stream as
the audio, so the cue times are measurements of the clip the viewer hears. Sections are padded
with a short pause and concatenated sample-exactly into narration.wav; timing.json carries the
absolute start of every section and sentence for tour.js.

    python narrate.py
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess

import edge_tts

from script import SECTIONS

HERE = pathlib.Path(__file__).resolve().parent
SPEECH = HERE / "speech"
VOICE = "en-US-AndrewMultilingualNeural"
RATE = "+15%"
LEAD_MS = 800       # silence before the first word, so the first frame is not mid-sentence
GAP_MS = 700        # pause after each section
TAIL_MS = 1800      # hold on the last frame


async def synth(text: str, mp3: pathlib.Path) -> list[dict]:
    comm = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="SentenceBoundary")
    bounds: list[dict] = []
    with mp3.open("wb") as fh:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "SentenceBoundary":
                bounds.append({"start_ms": chunk["offset"] / 10_000, "end_ms": (chunk["offset"] + chunk["duration"]) / 10_000,
                               "text": chunk["text"]})
    return bounds


def duration_ms(path: pathlib.Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return int(round(float(out) * 1000))


def main() -> None:
    SPEECH.mkdir(exist_ok=True)
    for stale in SPEECH.glob("*"):
        stale.unlink()
    clips: list[pathlib.Path] = []
    timing: list[dict] = []
    at = LEAD_MS
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-t", f"{LEAD_MS / 1000}", str(SPEECH / "lead.wav")], check=True)
    clips.append(SPEECH / "lead.wav")
    for i, sec in enumerate(SECTIONS, start=1):
        text = " ".join(s["say"] for s in sec["sentences"])
        mp3 = SPEECH / f"{i}.mp3"
        bounds = asyncio.run(synth(text, mp3))
        if len(bounds) != len(sec["sentences"]):
            got = "\n".join(f"    {b['start_ms'] / 1000:5.1f}s  {b['text'][:70]}" for b in bounds)
            raise SystemExit(f"section {sec['id']}: {len(sec['sentences'])} sentences written, {len(bounds)} boundaries measured:\n{got}")
        wav = SPEECH / f"{i}.wav"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af", f"apad=pad_dur={GAP_MS / 1000}",
                        "-ar", "48000", "-ac", "2", str(wav)], check=True)
        ms = duration_ms(wav)
        sentences = [{"start_ms": at + b["start_ms"], "end_ms": at + b["end_ms"], "say": s["say"], "cap": s["cap"]}
                     for b, s in zip(bounds, sec["sentences"])]
        timing.append({"id": sec["id"], "file": wav.name, "start_ms": at, "duration_ms": ms, "sentences": sentences})
        print(f"{i} {sec['id']:12} {at / 1000:6.1f}s  +{ms / 1000:5.1f}s")
        for s in sentences:
            print(f"      {s['start_ms'] / 1000:6.1f}s  {s['say'][:80]}")
        at += ms
        clips.append(wav)
    listing = SPEECH / "concat.txt"
    listing.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy",
                    str(HERE / "narration.wav")], check=True)
    total = at + TAIL_MS
    (HERE / "timing.json").write_text(json.dumps({"voice": VOICE, "rate": RATE, "lead_ms": LEAD_MS, "tail_ms": TAIL_MS,
                                                  "total_ms": total, "sections": timing}, indent=1), encoding="utf-8")
    print(f"\nnarration.wav {at / 1000:.1f}s, film {total / 1000:.1f}s ({total / 60000:.2f} min)")


if __name__ == "__main__":
    main()
