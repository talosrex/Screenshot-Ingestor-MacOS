#!/usr/bin/env python3
"""Optional Tesseract OCR fallback for screenshots where vision-based reading is uncertain.

This is a cross-check, not a replacement for the primary vision-based extraction
described in SKILL.md: Claude should keep reading screenshots directly, and only
invoke this script when its own reading of a specific image is low-confidence,
garbled, or contested.

Requires (not bundled, feature-detected at runtime):
    brew install tesseract
    pip install pytesseract pillow

If any dependency is missing, this script still exits 0 and reports
`{"ocr_available": false, ...}` so callers can proceed vision-only.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Callable

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    _PILLOW_AVAILABLE = True
except ImportError:
    _PILLOW_AVAILABLE = False

try:
    import pytesseract
    from pytesseract import Output

    _PYTESSERACT_AVAILABLE = True
except ImportError:
    _PYTESSERACT_AVAILABLE = False


PSM_BY_TYPE: dict[str, list[int]] = {
    "social": [4, 6, 11],
    "chat": [4, 6],
    "article": [3, 6],
    "code": [6],
    "generic": [3, 4, 6, 11],
    "auto": [3, 6, 11],
}

DEFAULT_VARIANTS = ["raw", "upscale2x", "grayscale_contrast", "binarize"]


def dependency_status() -> dict[str, Any]:
    missing = []
    if not _PILLOW_AVAILABLE:
        missing.append("pillow")
    if not _PYTESSERACT_AVAILABLE:
        missing.append("pytesseract")
    if shutil.which("tesseract") is None:
        missing.append("tesseract-binary")
    return {"available": not missing, "missing": missing}


def variant_upscale(image: "Image.Image", factor: float) -> "Image.Image":
    width, height = image.size
    return image.resize((int(width * factor), int(height * factor)), Image.Resampling.LANCZOS)


def variant_sharpen(image: "Image.Image") -> "Image.Image":
    return image.filter(ImageFilter.SHARPEN)


def variant_grayscale(image: "Image.Image") -> "Image.Image":
    return image.convert("L")


def variant_contrast(image: "Image.Image", factor: float = 1.5) -> "Image.Image":
    return ImageEnhance.Contrast(image.convert("L")).enhance(factor)


def variant_binarize(image: "Image.Image") -> "Image.Image":
    grayscale = image.convert("L")
    threshold = ImageOps.autocontrast(grayscale)
    return threshold.point(lambda pixel: 255 if pixel > 140 else 0, mode="L")


PREPROCESS_VARIANTS: dict[str, list[Callable[["Image.Image"], "Image.Image"]]] = {
    "raw": [],
    "upscale2x": [lambda image: variant_upscale(image, 2.0)],
    "upscale3x": [lambda image: variant_upscale(image, 3.0)],
    "upscale2x_sharpen": [lambda image: variant_upscale(image, 2.0), variant_sharpen],
    "grayscale_contrast": [variant_contrast],
    "binarize": [variant_binarize],
}


def crop_trim(image: "Image.Image", top_pct: float, bottom_pct: float) -> "Image.Image":
    """Trim a flat top/bottom margin as a rough, app-agnostic chrome heuristic.

    Not app-aware and not pixel-precise — fixed per-app crop regions are too
    fragile across device models, resolutions, and app redesigns. This only
    approximates "skip likely status bar / nav chrome" for the OCR fallback
    path; it never touches the source file or the primary vision reading.
    """
    width, height = image.size
    top = int(height * top_pct / 100)
    bottom = height - int(height * bottom_pct / 100)
    if bottom <= top:
        return image
    return image.crop((0, top, width, bottom))


def apply_variant(image: "Image.Image", variant: str) -> "Image.Image":
    result = image
    for transform in PREPROCESS_VARIANTS[variant]:
        result = transform(result)
    return result


def run_tesseract(image: "Image.Image", psm: int) -> dict[str, Any]:
    data = pytesseract.image_to_data(image, config=f"--psm {psm}", output_type=Output.DICT)
    words = []
    confidences = []
    for text, conf in zip(data["text"], data["conf"]):
        text = text.strip()
        conf = float(conf)
        if text:
            words.append(text)
        if conf >= 0:
            confidences.append(conf)
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return {
        "text": " ".join(words),
        "mean_confidence": round(mean_confidence, 1),
        "word_count": len(words),
    }


def best_result(results: list[dict[str, Any]]) -> dict[str, Any]:
    return max(results, key=lambda result: (result["mean_confidence"], len(result["text"])))


def ocr_image(
    path: Path,
    screenshot_type: str,
    crop_heuristic: str,
    top_pct: float,
    bottom_pct: float,
    variants: list[str],
    psms: list[int],
) -> dict[str, Any]:
    with Image.open(path) as source:
        base = source.convert("RGB")
        crop_applied = False
        if crop_heuristic == "trim-top-bottom":
            base = crop_trim(base, top_pct, bottom_pct)
            crop_applied = True

        all_variants = []
        for variant in variants:
            preprocessed = apply_variant(base, variant)
            for psm in psms:
                outcome = run_tesseract(preprocessed, psm)
                all_variants.append({"variant": variant, "psm": psm, **outcome})

    notes = []
    if crop_applied:
        notes.append(
            f"cropped image discards ~{top_pct:g}% top / ~{bottom_pct:g}% bottom; "
            "verify against the raw screenshot for chrome-adjacent text"
        )

    return {
        "path": str(path),
        "ocr_available": True,
        "screenshot_type_used": screenshot_type,
        "crop_heuristic": crop_heuristic,
        "crop_applied": crop_applied,
        "best": {key: value for key, value in best_result(all_variants).items()},
        "all_variants": all_variants,
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Tesseract OCR fallback with preprocessing variants and PSM sweep.")
    parser.add_argument("paths", nargs="+", help="Screenshot image paths.")
    parser.add_argument(
        "--screenshot-type",
        default="auto",
        choices=sorted(PSM_BY_TYPE),
        help="Hint used to pick which PSM modes to sweep.",
    )
    parser.add_argument(
        "--crop-heuristic",
        default="none",
        choices=["none", "trim-top-bottom"],
        help="Optional flat top/bottom margin trim before OCR. Approximate, not app-aware.",
    )
    parser.add_argument("--top-trim-pct", type=float, default=8.0, help="Top margin percent trimmed when cropping.")
    parser.add_argument(
        "--bottom-trim-pct", type=float, default=10.0, help="Bottom margin percent trimmed when cropping."
    )
    parser.add_argument(
        "--variants",
        default=",".join(DEFAULT_VARIANTS),
        help=f"Comma-separated preprocessing variants to try. Available: {', '.join(sorted(PREPROCESS_VARIANTS))}",
    )
    parser.add_argument(
        "--psm",
        default=None,
        help="Comma-separated Tesseract PSM modes to try. Defaults to the set for --screenshot-type.",
    )
    parser.add_argument("--output", help="Write JSON result to this path.")
    args = parser.parse_args()

    status = dependency_status()
    if not status["available"]:
        result: dict[str, Any] = {
            "ocr_available": False,
            "missing": status["missing"],
            "reason": "Install missing dependencies to enable the Tesseract fallback: "
            "brew install tesseract; pip install pytesseract pillow",
        }
    else:
        variants = [name.strip() for name in args.variants.split(",") if name.strip()]
        unknown = [name for name in variants if name not in PREPROCESS_VARIANTS]
        if unknown:
            parser.error(f"unknown --variants entries: {', '.join(unknown)}")
        psms = (
            [int(value.strip()) for value in args.psm.split(",") if value.strip()]
            if args.psm
            else PSM_BY_TYPE[args.screenshot_type]
        )

        results = []
        for value in args.paths:
            path = Path(value).expanduser()
            results.append(
                ocr_image(
                    path,
                    args.screenshot_type,
                    args.crop_heuristic,
                    args.top_trim_pct,
                    args.bottom_trim_pct,
                    variants,
                    psms,
                )
            )
        result = {"ocr_available": True, "results": results}

    serialized = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).expanduser().write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
