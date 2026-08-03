#!/usr/bin/env python3
"""Create a validated, deduplicated APPLES research subset from apples.zip."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple
from zipfile import BadZipFile, ZipFile


CLINICAL_FILES = {
    "apples/datasets/apples-dataset-0.1.0.csv": "clinical/apples-dataset-0.1.0.csv",
    "apples/datasets/apples-harmonized-dataset-0.1.0.csv": (
        "clinical/apples-harmonized-dataset-0.1.0.csv"
    ),
    "apples/apples/subject_labels_diagnosis.csv": (
        "clinical/subject_labels_diagnosis.csv"
    ),
    "apples/apples/subject_labels_morethan4h.csv": (
        "clinical/subject_labels_morethan4h.csv"
    ),
}
RAW_PREFIXES = (
    "apples/processed_1ch/",
    "apples/apples/processed_1ch/",
)
YASA_PREFIX = "apples/features_yasa/"
REQUIRED_NPZ_MEMBERS = {
    "x.npy",
    "y.npy",
    "y_full.npy",
    "keep_idx.npy",
    "fs.npy",
}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def valid_npz(content: bytes) -> Tuple[bool, Optional[str]]:
    try:
        with ZipFile(BytesIO(content)) as archive:
            missing = REQUIRED_NPZ_MEMBERS - set(archive.namelist())
            if missing:
                return False, f"missing members: {sorted(missing)}"
            corrupt_member = archive.testzip()
            if corrupt_member:
                return False, f"corrupt member: {corrupt_member}"
    except BadZipFile:
        return False, "invalid inner ZIP structure"
    return True, None


def file_id(path: str) -> str:
    match = re.search(r"(apples-\d+)\.npz$", path)
    if not match:
        raise ValueError(f"Cannot parse APPLES file ID: {path}")
    return match.group(1)


def select_npz_entries(archive: ZipFile):
    raw_candidates = defaultdict(list)
    yasa_candidates = {}
    corrupt = []
    for info in archive.infolist():
        name = info.filename
        if not name.endswith(".npz"):
            continue
        is_raw = name.startswith(RAW_PREFIXES)
        is_yasa = name.startswith(YASA_PREFIX)
        if not is_raw and not is_yasa:
            continue
        content = archive.read(info)
        valid, error = valid_npz(content)
        record = {
            "source_path": name,
            "bytes": len(content),
            "crc32": f"{info.CRC:08x}",
            "sha256": sha256_bytes(content),
        }
        if not valid:
            record["error"] = error
            corrupt.append(record)
            continue
        subject = file_id(name)
        record["fileid"] = subject
        if is_raw:
            # Prefer the newer top-level collection when both copies are valid.
            priority = 1 if name.startswith("apples/processed_1ch/") else 0
            raw_candidates[subject].append((priority, name, content, record))
        else:
            yasa_candidates[subject] = (name, content, record)

    raw_selected = {
        subject: sorted(candidates, key=lambda item: item[0], reverse=True)[0]
        for subject, candidates in raw_candidates.items()
    }
    return raw_selected, yasa_candidates, corrupt


def write_selected(output: Path, directory: str, selected):
    manifest = []
    destination = output / directory
    destination.mkdir(parents=True, exist_ok=True)
    expected_names = set()
    for subject, item in sorted(selected.items()):
        _, content, record = item[-3:]
        name = f"{subject}.npz"
        expected_names.add(name)
        path = destination / name
        path.write_bytes(content)
        manifest.append({**record, "curated_path": str(path.relative_to(output))})

    # Remove stale files from a previous curation run.
    for path in destination.glob("*.npz"):
        if path.name not in expected_names:
            path.unlink()
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, default=Path("data/apples.zip"))
    parser.add_argument(
        "--output", type=Path, default=Path("data/apples_curated")
    )
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    clinical_dir = args.output / "clinical"
    clinical_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.archive) as archive:
        raw_selected, yasa_selected, corrupt = select_npz_entries(archive)
        for source, target in CLINICAL_FILES.items():
            destination = args.output / target
            with archive.open(source) as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst)
        raw_manifest = write_selected(
            args.output, "raw_1ch", raw_selected
        )
        yasa_manifest = write_selected(
            args.output, "yasa", yasa_selected
        )

    source_sha256 = hashlib.sha256()
    with args.archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            source_sha256.update(chunk)
    report = {
        "source_archive": str(args.archive),
        "source_archive_sha256": source_sha256.hexdigest(),
        "policy": {
            "raw_duplicate_resolution": (
                "prefer apples/processed_1ch, fall back to "
                "apples/apples/processed_1ch"
            ),
            "excluded": [
                "invalid inner NPZ files",
                "duplicate raw NPZ versions",
                "historical checkpoints, logs, and model outputs",
                "redundant archived clinical tables",
                "standalone annotation text duplicates",
            ],
        },
        "counts": {
            "raw_1ch": len(raw_manifest),
            "yasa": len(yasa_manifest),
            "corrupt_entries": len(corrupt),
        },
        "clinical_files": sorted(CLINICAL_FILES.values()),
        "raw_1ch": raw_manifest,
        "yasa": yasa_manifest,
        "corrupt_entries": corrupt,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report["counts"], indent=2))


if __name__ == "__main__":
    main()
