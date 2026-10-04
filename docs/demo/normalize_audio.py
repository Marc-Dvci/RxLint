"""Set demo narration to -14 LUFS, preserving video frames and cue timing."""
from pathlib import Path
import json
import subprocess
import sys


def duration(path: Path) -> float:
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(result.stdout)['format']['duration'])


def normalize_audio(path: Path) -> dict:
    path = path.resolve(strict=True)
    staged = path.with_name(path.stem + '.normalized' + path.suffix)
    original_duration = duration(path)
    result = subprocess.run(
        ['ffmpeg', '-y', '-hide_banner', '-i', str(path), '-map', '0:v:0', '-map', '0:a:0',
         '-c:v', 'copy', '-af', 'loudnorm=I=-14:LRA=11:TP=-1.5:print_format=json',
         '-ar', '48000', '-c:a', 'aac', '-b:a', '192k', '-t', f'{original_duration:.6f}',
         '-movflags', '+faststart', str(staged)],
        capture_output=True, text=True, check=True,
    )
    stats = json.loads(result.stderr[result.stderr.rfind('{'):result.stderr.rfind('}') + 1])
    if abs(duration(staged) - original_duration) > .05:
        raise RuntimeError('Audio normalization changed the movie duration; original retained.')
    staged.replace(path)
    return stats


if __name__ == '__main__':
    print(json.dumps(normalize_audio(Path(sys.argv[1])), indent=2))
