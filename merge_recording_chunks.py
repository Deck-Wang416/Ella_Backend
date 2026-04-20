#!/usr/bin/env python3
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


CHUNK_RE = re.compile(r"^chunk_(\d+)\.([A-Za-z0-9]+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge one recording session's chunk files into a single audio file."
    )
    parser.add_argument(
        "session_dir",
        type=Path,
        help="Local directory containing chunk_000000.* files for one recording session.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output file path. Defaults to <session_dir>/<session_dir_name>_merged.<ext>.",
    )
    return parser.parse_args()


def find_chunks(session_dir: Path) -> list[Path]:
    chunks: list[tuple[int, Path]] = []
    for path in session_dir.iterdir():
        if not path.is_file():
            continue
        match = CHUNK_RE.match(path.name)
        if not match:
            continue
        chunks.append((int(match.group(1)), path))
    return [path for _, path in sorted(chunks, key=lambda item: item[0])]


def ensure_same_extension(chunks: list[Path]) -> str:
    exts = {chunk.suffix.lower() for chunk in chunks}
    if len(exts) != 1:
        raise ValueError(f"Expected all chunks to have the same extension, got: {sorted(exts)}")
    return exts.pop().lstrip(".")


def resolve_media_extension(extension: str) -> str:
    # Firebase uploads may fall back to .bin when the backend cannot map
    # a mime type like "audio/webm;codecs=opus" to a better suffix.
    if extension == "bin":
        return "webm"
    return extension


def default_output_path(session_dir: Path, extension: str) -> Path:
    return session_dir / f"{session_dir.name}_merged.{extension}"


def run_ffmpeg_from_concatenated_bytes(chunks: list[Path], output_path: Path, media_extension: str) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is not installed or not on PATH.")

    with tempfile.TemporaryDirectory(prefix="merge_chunks_raw_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        combined_input = tmp_path / f"combined.{media_extension}"
        with combined_input.open("wb") as target:
            for chunk in chunks:
                target.write(chunk.read_bytes())

        # MediaRecorder dataavailable chunks are slices of a single byte stream,
        # not standalone WebM files. Rebuild that byte stream first, then remux.
        remux_cmd = [
            ffmpeg,
            "-y",
            "-i",
            str(combined_input),
            "-c",
            "copy",
            str(output_path),
        ]
        remux_result = subprocess.run(remux_cmd, capture_output=True, text=True)
        if remux_result.returncode == 0:
            return

        transcode_cmd = [
            ffmpeg,
            "-y",
            "-fflags",
            "+genpts",
            "-i",
            str(combined_input),
            "-c:a",
            "libopus",
            str(output_path),
        ]
        transcode_result = subprocess.run(transcode_cmd, capture_output=True, text=True)
        if transcode_result.returncode == 0:
            return

        raise RuntimeError(
            "ffmpeg failed to merge concatenated chunk bytes.\n"
            f"remux stderr:\n{remux_result.stderr}\n\n"
            f"transcode stderr:\n{transcode_result.stderr}"
        )


def main() -> int:
    args = parse_args()
    session_dir = args.session_dir.expanduser().resolve()
    if not session_dir.exists() or not session_dir.is_dir():
        print(f"Session directory not found: {session_dir}", file=sys.stderr)
        return 1

    chunks = find_chunks(session_dir)
    if not chunks:
        print(f"No chunk_*.ext files found in: {session_dir}", file=sys.stderr)
        return 1

    raw_extension = ensure_same_extension(chunks)
    media_extension = resolve_media_extension(raw_extension)
    output_path = (
        args.output.expanduser().resolve()
        if args.output
        else default_output_path(session_dir, media_extension)
    )

    try:
        run_ffmpeg_from_concatenated_bytes(chunks, output_path, media_extension)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Merged {len(chunks)} chunks into: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
