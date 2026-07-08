#!/usr/bin/env python3
"""Batch-run Apple's on-device Vision OCR (VNRecognizeTextRequest) over screenshots.

Compiles scripts/vision_ocr.swift into scripts/bin/vision_ocr on first use (or
when the source has changed), then invokes it in batches and writes a single
structured JSON file mapping each image to its recognized text, per-line
confidence, and bounding boxes. macOS only; requires Xcode Command Line Tools.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".heic",
    ".heif",
    ".webp",
    ".tif",
    ".tiff",
    ".gif",
}

SCRIPT_DIR = Path(__file__).resolve().parent
SWIFT_SOURCE = SCRIPT_DIR / "vision_ocr.swift"
BINARY_PATH = SCRIPT_DIR / "bin" / "vision_ocr"
SDK_ROOT = Path("/Library/Developer/CommandLineTools/SDKs")


def candidate_sdks() -> list[Path]:
    if not SDK_ROOT.is_dir():
        return []
    versioned = []
    for entry in SDK_ROOT.iterdir():
        match = re.match(r"MacOSX(\d+(?:\.\d+)?)\.sdk$", entry.name)
        if match:
            versioned.append((float(match.group(1)), entry))
    versioned.sort(key=lambda pair: pair[0], reverse=True)
    return [path for _, path in versioned]


def build_binary() -> None:
    BINARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    base_cmd = ["swiftc", "-O", str(SWIFT_SOURCE), "-o", str(BINARY_PATH)]

    result = subprocess.run(base_cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return

    last_error = result.stderr
    for sdk in candidate_sdks():
        cmd = ["swiftc", "-sdk", str(sdk), "-O", str(SWIFT_SOURCE), "-o", str(BINARY_PATH)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return
        last_error = result.stderr

    raise RuntimeError(
        "Failed to compile vision_ocr.swift. This requires macOS with Xcode "
        "Command Line Tools installed (`xcode-select --install`).\n\n"
        f"Last compiler error:\n{last_error}"
    )


def ensure_binary(rebuild: bool = False) -> None:
    if rebuild or not BINARY_PATH.exists() or BINARY_PATH.stat().st_mtime < SWIFT_SOURCE.stat().st_mtime:
        print("Building vision_ocr helper (one-time)...", file=sys.stderr)
        build_binary()


def collect_images(input_path: Path, recursive: bool) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    pattern = "**/*" if recursive else "*"
    files = [
        p for p in sorted(input_path.glob(pattern))
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    ]
    return files


def run_batch(paths: list[Path], languages: list[str]) -> list[dict]:
    cmd = [str(BINARY_PATH), *[str(p) for p in paths], "--languages", ",".join(languages)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"vision_ocr failed on a batch: {result.stderr}")
    return json.loads(result.stdout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", help="Screenshot file or folder")
    parser.add_argument("--recursive", action="store_true", help="Recurse into subfolders")
    parser.add_argument("-o", "--output", default="screenshot-vision-ocr.json", help="Output JSON path")
    parser.add_argument("--languages", default="en-US", help="Comma-separated recognition languages")
    parser.add_argument("--batch-size", type=int, default=150, help="Images per subprocess call")
    parser.add_argument("--rebuild", action="store_true", help="Force rebuild of the OCR helper binary")
    args = parser.parse_args()

    ensure_binary(rebuild=args.rebuild)

    input_path = Path(args.input_path)
    images = collect_images(input_path, args.recursive)
    if not images:
        print(f"No images found under {input_path}", file=sys.stderr)
        sys.exit(1)

    languages = [lang.strip() for lang in args.languages.split(",") if lang.strip()]

    results: list[dict] = []
    for i in range(0, len(images), args.batch_size):
        batch = images[i : i + args.batch_size]
        print(f"OCR {i + 1}-{i + len(batch)} of {len(images)}...", file=sys.stderr)
        results.extend(run_batch(batch, languages))

    errors = sum(1 for r in results if r.get("error"))
    confidences = [r["averageConfidence"] for r in results if r.get("lineCount", 0) > 0]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    output: dict[str, Any] = {
        "engine": "Apple Vision (VNRecognizeTextRequest)",
        "recognition_level": "accurate",
        "language_correction": True,
        "languages": languages,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "image_count": len(results),
        "error_count": errors,
        "average_confidence": avg_confidence,
        "results": results,
    }

    Path(args.output).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(
        f"Wrote {args.output}: {len(results)} images, {errors} errors, "
        f"avg confidence {avg_confidence:.2f}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
