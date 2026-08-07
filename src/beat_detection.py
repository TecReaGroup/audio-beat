"""Detect beats and downbeats in local audio files with Beat This."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from beat_this.inference import File2Beats

AUDIO_EXTENSIONS = frozenset({".flac", ".m4a", ".mp3", ".ogg", ".wav", ".wma"})


def find_audio_files(input_path: Path) -> list[Path]:
    """Return supported audio files from a file or directory."""
    if input_path.is_file():
        if input_path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError(f"Unsupported audio format: {input_path.suffix}")
        return [input_path]
    if input_path.is_dir():
        return sorted(
            path
            for path in input_path.rglob("*")
            if path.is_file() and path.suffix.lower() in AUDIO_EXTENSIONS
        )
    raise FileNotFoundError(f"Input path does not exist: {input_path}")


def detect_file(detector: File2Beats, audio_path: Path, output_path: Path) -> None:
    """Detect beats for one file and write a JSON result."""
    beats, downbeats = detector(str(audio_path))
    result: dict[str, Any] = {
        "audio": str(audio_path),
        "beats": [float(value) for value in beats],
        "downbeats": [float(value) for value in downbeats],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _select_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def detect_directory(
    input_path: Path,
    output_dir: Path,
    checkpoint: str = "final0",
    device: str = "auto",
) -> int:
    """Detect all audio files below input_path and return the failure count."""
    files = find_audio_files(input_path)
    if not files:
        print(f"No supported audio files found in {input_path}")
        return 0
    detector = File2Beats(checkpoint_path=checkpoint, device=_select_device(device))
    failures = 0
    for audio_path in files:
        output_path = output_dir / f"{audio_path.stem}.json"
        try:
            detect_file(detector, audio_path, output_path)
            print(f"Wrote {output_path}")
        except Exception as exc:  # keep processing remaining files
            failures += 1
            print(f"Failed {audio_path}: {exc}")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    """Run the beat detection CLI."""
    parser = argparse.ArgumentParser(prog="beat-detect")
    parser.add_argument("input", nargs="?", type=Path, default=Path("data/audio"))
    parser.add_argument("-o", "--output", type=Path, default=Path("data/beats"))
    parser.add_argument("--model", default="final0", help="Beat This checkpoint name or path")
    parser.add_argument("--device", default="auto", help="auto, cpu, cuda, or cuda:N")
    args = parser.parse_args(argv)
    try:
        return 1 if detect_directory(args.input, args.output, args.model, args.device) else 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
