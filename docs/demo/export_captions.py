"""Export synchronized SRT captions from the measured narration timing."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def stamp(ms: float) -> str:
    hours, remainder = divmod(round(ms), 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


def main() -> None:
    timing = json.loads((HERE / "timing.json").read_text(encoding="utf-8"))
    beats = [s for section in timing["sections"] for s in section["sentences"]]
    cues = []
    for i, sentence in enumerate(beats):
        end = sentence["end_ms"] + 150
        if i + 1 < len(beats):
            end = min(end, beats[i + 1]["start_ms"] - 30)
        cues.append(f"{i + 1}\n{stamp(sentence['start_ms'])} --> {stamp(end)}\n{sentence['say']}\n")
    (HERE / "rxlint-demo.srt").write_text("\n".join(cues), encoding="utf-8")


if __name__ == "__main__":
    main()
