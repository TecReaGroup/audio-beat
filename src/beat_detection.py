"""Detect beats and downbeats in local audio files with Beat This."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from beat_this.inference import File2Beats

AUDIO_EXTENSIONS = frozenset({".flac", ".m4a", ".mp3", ".ogg", ".wav", ".wma"})
TEMP_DIR = Path("temp")


@dataclass(frozen=True)
class InferenceDevice:
    name: str
    description: str
    float16: bool


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


def _detect_with_ffmpeg(detector: File2Beats, audio_path: Path) -> tuple[Any, Any]:
    """Decode an unsupported audio container with ffmpeg before detection."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            f'Could not decode "{audio_path}". Install ffmpeg and make it available on PATH.'
        )

    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", dir=TEMP_DIR, delete=False) as file:
        decoded_path = Path(file.name)

    try:
        process = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(audio_path),
                "-map",
                "0:a:0",
                "-vn",
                "-c:a",
                "pcm_s16le",
                str(decoded_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if process.returncode != 0:
            detail = process.stderr.strip() or f"ffmpeg exited with code {process.returncode}"
            raise RuntimeError(f'Could not decode "{audio_path}" with ffmpeg: {detail}')
        return detector(str(decoded_path))
    finally:
        decoded_path.unlink(missing_ok=True)


def detect_file(detector: File2Beats, audio_path: Path, output_path: Path) -> None:
    """Detect beats for one file and write a JSON result."""
    try:
        beats, downbeats = detector(str(audio_path))
    except RuntimeError as exc:
        if "Could not load audio" not in str(exc):
            raise
        beats, downbeats = _detect_with_ffmpeg(detector, audio_path)
    result: dict[str, Any] = {
        "audio": str(audio_path),
        "beats": [float(value) for value in beats],
        "downbeats": [float(value) for value in downbeats],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _cuda_device(device: str) -> InferenceDevice:
    if torch.version.cuda is None:
        raise ValueError(
            f"CUDA was requested, but PyTorch {torch.__version__} is a CPU-only build"
        )
    if not torch.cuda.is_available():
        raise ValueError(
            "CUDA was requested, but PyTorch cannot access an NVIDIA GPU; "
            "check the NVIDIA driver and CUDA wheel"
        )

    try:
        parsed = torch.device(device)
    except RuntimeError as exc:
        raise ValueError(f"Invalid CUDA device: {device}") from exc
    index = parsed.index if parsed.index is not None else torch.cuda.current_device()
    if index < 0 or index >= torch.cuda.device_count():
        raise ValueError(
            f"CUDA device index {index} is unavailable; found {torch.cuda.device_count()} GPU(s)"
        )

    properties = torch.cuda.get_device_properties(index)
    memory_gib = properties.total_memory / (1024**3)
    name = f"cuda:{index}"
    description = (
        f"{name} ({properties.name}, {memory_gib:.1f} GiB, CUDA {torch.version.cuda})"
    )
    return InferenceDevice(name=name, description=description, float16=True)


def _select_device(device: str) -> InferenceDevice:
    requested = device.strip().lower()
    if requested == "auto":
        if torch.cuda.is_available():
            return _cuda_device("cuda")
        reason = (
            f"PyTorch {torch.__version__} is CPU-only"
            if torch.version.cuda is None
            else "CUDA is unavailable"
        )
        return InferenceDevice("cpu", f"cpu ({reason})", False)
    if requested == "cpu":
        return InferenceDevice("cpu", "cpu (explicitly selected)", False)
    if requested == "cuda" or requested.startswith("cuda:"):
        return _cuda_device(requested)
    raise ValueError("Device must be auto, cpu, cuda, or cuda:N")


def detect_directory(
    input_path: Path,
    output_dir: Path,
    checkpoint: str = "final0",
    device: str = "auto",
    dbn: bool = False,
) -> int:
    """Detect all audio files below input_path and return the failure count."""
    files = find_audio_files(input_path)
    if not files:
        print(f"No supported audio files found in {input_path}")
        return 0
    selected_device = _select_device(device)
    precision = "float16" if selected_device.float16 else "float32"
    postprocessing = "DBN" if dbn else "minimal"
    print(
        f"Inference device: {selected_device.description}; precision: {precision}; "
        f"postprocessing: {postprocessing}"
    )
    try:
        detector = File2Beats(
            checkpoint_path=checkpoint,
            device=selected_device.name,
            float16=selected_device.float16,
            dbn=dbn,
        )
    except ImportError as exc:
        if dbn:
            raise ValueError(
                "DBN postprocessing could not load madmom; reinstall it with: "
                "uv sync --extra dbn --reinstall-package madmom"
            ) from exc
        raise
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
    parser.add_argument(
        "--dbn",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="use madmom DBN postprocessing instead of minimal peak picking",
    )
    args = parser.parse_args(argv)
    try:
        return (
            1
            if detect_directory(
                args.input,
                args.output,
                checkpoint=args.model,
                device=args.device,
                dbn=args.dbn,
            )
            else 0
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
