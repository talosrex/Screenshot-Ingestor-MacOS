#!/usr/bin/env python3
"""Inventory screenshot image files and identify time-window grouping candidates."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import struct
import subprocess
from pathlib import Path
from typing import Any

try:
    from PIL import Image, UnidentifiedImageError
except ImportError:  # pragma: no cover - exercised only when Pillow is absent
    Image = None  # type: ignore[assignment]
    UnidentifiedImageError = Exception  # type: ignore[assignment]


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


SCREENSHOT_PATTERNS = [
    re.compile(
        r"(?:Screen Shot|Screenshot)\s+"
        r"(?P<date>\d{4}-\d{2}-\d{2})\s+at\s+"
        r"(?P<hour>\d{1,2})[.\-:](?P<minute>\d{2})[.\-:](?P<second>\d{2})"
        r"(?:\s*(?P<ampm>AM|PM))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"Screenshot[_\-\s]?"
        r"(?P<year>\d{4})(?P<month>\d{2})(?P<day>\d{2})"
        r"[_\-\s]?"
        r"(?P<hour>\d{2})(?P<minute>\d{2})(?P<second>\d{2})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<year>\d{4})[-_](?P<month>\d{2})[-_](?P<day>\d{2})"
        r"[ T_-]"
        r"(?P<hour>\d{2})[-_.:](?P<minute>\d{2})[-_.:](?P<second>\d{2})"
    ),
]


def iso_from_timestamp(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="seconds")


def parse_filename_datetime(name: str) -> str | None:
    for pattern in SCREENSHOT_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        groups = match.groupdict()
        if "date" in groups and groups.get("date"):
            year, month, day = [int(part) for part in groups["date"].split("-")]
        else:
            year = int(groups["year"])
            month = int(groups["month"])
            day = int(groups["day"])
        hour = int(groups["hour"])
        minute = int(groups["minute"])
        second = int(groups["second"])
        ampm = groups.get("ampm")
        if ampm:
            upper = ampm.upper()
            if upper == "PM" and hour != 12:
                hour += 12
            elif upper == "AM" and hour == 12:
                hour = 0
        try:
            value = dt.datetime(year, month, day, hour, minute, second).astimezone()
        except ValueError:
            return None
        return value.isoformat(timespec="seconds")
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def png_size(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    return None


def gif_size(data: bytes) -> tuple[int, int] | None:
    if len(data) >= 10 and data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    return None


def webp_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return None
    chunk = data[12:16]
    if chunk == b"VP8X" and len(data) >= 30:
        width = 1 + int.from_bytes(data[24:27], "little")
        height = 1 + int.from_bytes(data[27:30], "little")
        return width, height
    if chunk == b"VP8 " and len(data) >= 30:
        start = data.find(b"\x9d\x01\x2a")
        if start != -1 and len(data) >= start + 7:
            width, height = struct.unpack("<HH", data[start + 3 : start + 7])
            return width & 0x3FFF, height & 0x3FFF
    return None


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        while marker == 0xFF and index < len(data):
            marker = data[index]
            index += 1
        if marker in {0xD8, 0xD9, 0x01} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            return None
        length = struct.unpack(">H", data[index : index + 2])[0]
        if length < 2 or index + length > len(data):
            return None
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            height = struct.unpack(">H", data[index + 3 : index + 5])[0]
            width = struct.unpack(">H", data[index + 5 : index + 7])[0]
            return width, height
        index += length
    return None


def image_size(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()[:512 * 1024]
    except OSError:
        return None
    for parser in (png_size, jpeg_size, gif_size, webp_size):
        size = parser(data)
        if size:
            return size
    return mdls_dimensions(path)


def mdls_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        output = subprocess.check_output(
            ["mdls", "-raw", "-name", "kMDItemPixelWidth", "-name", "kMDItemPixelHeight", str(path)],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    values = [line.strip() for line in output.splitlines() if line.strip() and line.strip() != "(null)"]
    if len(values) >= 2 and all(value.isdigit() for value in values[:2]):
        return int(values[0]), int(values[1])
    return None


def mdls_value(path: Path, key: str) -> str | None:
    try:
        output = subprocess.check_output(
            ["mdls", "-raw", "-name", key, str(path)],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not output or output == "(null)":
        return None
    return output


def pillow_available() -> bool:
    return Image is not None


def dhash(path: Path, hash_size: int = 8) -> str | None:
    """Compute a difference hash (dHash) for perceptual near-duplicate matching.

    Returns None when Pillow is unavailable or the image cannot be decoded, so
    callers can treat this purely as an optional enrichment on top of the
    existing timestamp-based grouping.
    """
    if not pillow_available():
        return None
    try:
        with Image.open(path) as image:
            grayscale = image.convert("L").resize(
                (hash_size + 1, hash_size), Image.Resampling.LANCZOS
            )
            pixels = list(grayscale.getdata())
    except (OSError, UnidentifiedImageError, ValueError):
        return None

    bits = 0
    row_width = hash_size + 1
    for row in range(hash_size):
        offset = row * row_width
        for col in range(hash_size):
            bits <<= 1
            if pixels[offset + col] > pixels[offset + col + 1]:
                bits |= 1
    return format(bits, f"0{hash_size * hash_size // 4}x")


def hamming_distance(hash_a: str, hash_b: str) -> int:
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")


def collect_files(paths: list[Path], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        expanded = path.expanduser()
        if expanded.is_dir():
            iterator = expanded.rglob("*") if recursive else expanded.iterdir()
            files.extend(item for item in iterator if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS)
        elif expanded.is_file() and expanded.suffix.lower() in IMAGE_EXTENSIONS:
            files.append(expanded)
    return sorted(set(files), key=lambda item: str(item).lower())


def capture_time(record: dict[str, Any]) -> str:
    return (
        record.get("filename_datetime")
        or record.get("spotlight_creation_date")
        or record.get("filesystem_created_at")
        or record["filesystem_modified_at"]
    )


def parse_iso(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _phash_map(records: list[dict[str, Any]]) -> dict[str, str]:
    return {record["path"]: record["phash"] for record in records if record.get("phash")}


def _phash_similarity(paths: list[str], phash_by_path: dict[str, str], max_distance: int) -> dict[str, Any]:
    hashes = [phash_by_path[path] for path in paths if path in phash_by_path]
    if len(hashes) < 2:
        return {"available": False, "min_distance": None, "max_distance": None, "visually_similar": None}
    distances = [
        hamming_distance(hashes[i], hashes[j]) for i in range(len(hashes)) for j in range(i + 1, len(hashes))
    ]
    return {
        "available": True,
        "min_distance": min(distances),
        "max_distance": max(distances),
        "visually_similar": min(distances) <= max_distance,
    }


def _phash_only_groups(
    records: list[dict[str, Any]],
    grouped_paths: set[str],
    max_distance: int,
    max_compare: int,
    start_index: int,
) -> tuple[list[dict[str, Any]], str | None]:
    """Cluster visually near-duplicate files that fell outside every timestamp window.

    Weaker evidence than timestamp-based groups: perceptual similarity alone
    does not prove a real sequence (e.g. two unrelated visits to the same
    settings screen), so these are flagged with a distinct merge_decision.
    """
    candidates = [record for record in records if record.get("phash") and record["path"] not in grouped_paths]
    if len(candidates) > max_compare:
        return [], f"phash_only pass skipped: {len(candidates)} ungrouped candidates exceeds --max-phash-compare ({max_compare})"
    if len(candidates) < 2:
        return [], None

    parent = {record["path"]: record["path"] for record in candidates}

    def find(path: str) -> str:
        while parent[path] != path:
            parent[path] = parent[parent[path]]
            path = parent[path]
        return path

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            if hamming_distance(candidates[i]["phash"], candidates[j]["phash"]) <= max_distance:
                union(candidates[i]["path"], candidates[j]["path"])

    clusters: dict[str, list[dict[str, Any]]] = {}
    for record in candidates:
        clusters.setdefault(find(record["path"]), []).append(record)

    phash_by_path = _phash_map(candidates)
    output = []
    index = start_index
    for members in clusters.values():
        if len(members) < 2:
            continue
        paths = [record["path"] for record in members]
        output.append(
            {
                "group_id": f"candidate-{index:03d}",
                "group_basis": "phash_only",
                "files": paths,
                "phash_similarity": _phash_similarity(paths, phash_by_path, max_distance),
                "merge_decision": "candidate_only_visual_text_review_required_weak_evidence",
            }
        )
        index += 1
    return output, None


def candidate_groups(
    records: list[dict[str, Any]],
    window_seconds: int,
    phash_max_distance: int | None = None,
    max_phash_compare: int = 500,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    timed = []
    for record in records:
        parsed = parse_iso(capture_time(record))
        if parsed is not None:
            timed.append((parsed, record))
    timed.sort(key=lambda item: item[0])

    groups: list[list[tuple[dt.datetime, dict[str, Any]]]] = []
    current: list[tuple[dt.datetime, dict[str, Any]]] = []
    for item in timed:
        if not current:
            current = [item]
            continue
        if (item[0] - current[-1][0]).total_seconds() <= window_seconds:
            current.append(item)
        else:
            if len(current) > 1:
                groups.append(current)
            current = [item]
    if len(current) > 1:
        groups.append(current)

    phash_by_path = _phash_map(records)
    phash_enabled = bool(phash_max_distance) and phash_max_distance > 0 and bool(phash_by_path)

    output = []
    grouped_paths: set[str] = set()
    for index, group in enumerate(groups, start=1):
        start = group[0][0]
        end = group[-1][0]
        paths = [str(record["path"]) for _, record in group]
        grouped_paths.update(paths)
        entry = {
            "group_id": f"candidate-{index:03d}",
            "group_basis": "timestamp",
            "start": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds"),
            "duration_seconds": int((end - start).total_seconds()),
            "files": paths,
            "merge_decision": "candidate_only_visual_text_review_required",
        }
        if phash_enabled:
            entry["phash_similarity"] = _phash_similarity(paths, phash_by_path, phash_max_distance)
        output.append(entry)

    phash_summary: dict[str, Any] = {
        "enabled": phash_enabled,
        "library": "pillow_dhash" if phash_enabled else None,
        "max_distance": phash_max_distance if phash_enabled else None,
        "skipped_reason": None,
    }

    if phash_enabled:
        phash_only, skipped_reason = _phash_only_groups(
            records, grouped_paths, phash_max_distance, max_phash_compare, start_index=len(output) + 1
        )
        output.extend(phash_only)
        phash_summary["skipped_reason"] = skipped_reason
    elif phash_max_distance and phash_max_distance > 0 and not phash_by_path:
        phash_summary["skipped_reason"] = "no phash data available (Pillow not installed or images undecodable)"

    return output, phash_summary


def inventory_file(path: Path) -> dict[str, Any]:
    stat = path.stat()
    size = image_size(path)
    width = size[0] if size else None
    height = size[1] if size else None
    filename_datetime = parse_filename_datetime(path.name)
    spotlight_creation = mdls_value(path, "kMDItemContentCreationDate") or mdls_value(path, "kMDItemFSCreationDate")
    where_from = mdls_value(path, "kMDItemWhereFroms")
    file_phash = dhash(path)
    return {
        "path": str(path),
        "name": path.name,
        "extension": path.suffix.lower(),
        "bytes": stat.st_size,
        "sha256": sha256(path),
        "width": width,
        "height": height,
        "phash": file_phash,
        "phash_basis": "dhash_8x8" if file_phash else None,
        "filename_datetime": filename_datetime,
        "spotlight_creation_date": spotlight_creation,
        "filesystem_created_at": iso_from_timestamp(stat.st_birthtime if hasattr(stat, "st_birthtime") else stat.st_ctime),
        "filesystem_modified_at": iso_from_timestamp(stat.st_mtime),
        "where_from": where_from,
        "capture_time_basis": "filename_datetime"
        if filename_datetime
        else "spotlight_creation_date"
        if spotlight_creation
        else "filesystem_created_at",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory screenshots and identify 20-second candidate groups.")
    parser.add_argument("paths", nargs="+", help="Screenshot files or folders to inventory.")
    parser.add_argument("--recursive", action="store_true", help="Recurse into directories.")
    parser.add_argument("--window-seconds", type=int, default=20, help="Grouping window in seconds.")
    parser.add_argument(
        "--phash-max-distance",
        type=int,
        default=10,
        help="Max dHash Hamming distance (of 64 bits) to treat two images as visually similar. "
        "0 disables perceptual-hash grouping entirely. Requires Pillow.",
    )
    parser.add_argument(
        "--max-phash-compare",
        type=int,
        default=500,
        help="Skip the phash-only grouping pass if more than this many ungrouped files have a phash "
        "(bounds O(n^2) comparison cost for very large folders).",
    )
    parser.add_argument("--output", help="Write JSON inventory to this path.")
    args = parser.parse_args()

    paths = [Path(value) for value in args.paths]
    files = collect_files(paths, args.recursive)
    records = [inventory_file(path) for path in files]
    groups, phash_summary = candidate_groups(
        records, args.window_seconds, args.phash_max_distance, args.max_phash_compare
    )
    result = {
        "run": {
            "inputs": [str(path.expanduser()) for path in paths],
            "recursive": args.recursive,
            "window_seconds": args.window_seconds,
            "cwd": os.getcwd(),
            "file_count": len(records),
            "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "phash": phash_summary,
        },
        "files": records,
        "candidate_groups": groups,
    }

    serialized = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).expanduser().write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
