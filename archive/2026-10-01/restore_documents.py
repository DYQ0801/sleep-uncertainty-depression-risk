#!/usr/bin/env python3
"""Verify the cleanup or copy the original documents to a new directory."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("manifest.json")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def original_copies(manifest):
    copies = {}
    for operation in manifest["moves"]:
        for item in operation["files"]:
            copies[item["path"]] = (item["destination"], item["sha256"])
    for item in manifest["deduplicated"]:
        copies[item["path"]] = (item["retained_path"], item["sha256"])
    # Use untouched pre-edit copies for README, .gitignore and the reference index.
    for item in manifest["before_edit_copies"]:
        copies[item["path"]] = (item["destination"], item["sha256"])
    return copies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--destination", type=Path)
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    copies = original_copies(manifest)
    errors = []
    for original, (current, expected) in copies.items():
        path = ROOT / current
        if not path.is_file() or sha256(path) != expected:
            errors.append(f"Original unavailable or changed: {original} -> {current}")
    if args.check:
        for item in manifest["protected_files"]:
            path = ROOT / item["path"]
            if not path.is_file() or sha256(path) != item["sha256"]:
                errors.append(f"Protected file changed since cleanup: {item['path']}")
    if errors:
        raise SystemExit("\n".join(errors))
    if args.check:
        print(json.dumps({
            "original_document_files_verified": len(copies),
            "protected_files_verified": len(manifest["protected_files"]),
        }, indent=2))
        return

    destination = args.destination.resolve()
    if destination.exists():
        raise SystemExit(f"Destination must not exist: {destination}")
    destination.mkdir(parents=True)
    for original, (current, expected) in copies.items():
        target = destination / original
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / current, target)
        if sha256(target) != expected:
            raise SystemExit(f"Copy verification failed: {target}")
    print(f"Restored {len(copies)} original document files to {destination}")


if __name__ == "__main__":
    main()
