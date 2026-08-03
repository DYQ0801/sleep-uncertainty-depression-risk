#!/usr/bin/env python3
"""Download public epoch-level Bovy et al. hypnograms from OSF."""

from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/external/bovy2022"
FOLDERS = {
    "a": "https://api.osf.io/v2/nodes/bdez9/files/osfstorage/5f47b049d4c60300c52026b3/",
    "b": "https://api.osf.io/v2/nodes/bdez9/files/osfstorage/5f47b057d4c60300cd1fd2cb/",
    "c": "https://api.osf.io/v2/nodes/bdez9/files/osfstorage/5f47b064746a81034a1a23c7/",
}


def read_json(url: str):
    with urlopen(url) as response:
        return json.load(response)


def download_file(task):
    dataset, name, download_url = task
    output_dir = OUTPUT / f"dataset_{dataset.lower()}" / "hypnograms"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / name
    if path.exists():
        content = path.read_bytes()
    else:
        for attempt in range(4):
            try:
                with urlopen(download_url, timeout=60) as response:
                    content = response.read()
                break
            except TimeoutError:
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
        path.write_bytes(content)
    return {
        "dataset": dataset,
        "name": name,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
        "download_url": download_url,
    }


def main():
    tasks = []
    for dataset, first_page in FOLDERS.items():
        page_url = first_page
        while page_url:
            page = read_json(page_url)
            for item in page["data"]:
                name = item["attributes"]["name"]
                download_url = item["links"]["download"]
                tasks.append((dataset.upper(), name, download_url))
            page_url = page["links"].get("next")
    with ThreadPoolExecutor(max_workers=12) as pool:
        manifest = list(pool.map(download_file, tasks))
    manifest.sort(key=lambda row: (row["dataset"], row["name"]))
    (OUTPUT / "hypnograms_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    counts = {
        dataset: sum(row["dataset"] == dataset for row in manifest)
        for dataset in ["A", "B", "C"]
    }
    print(json.dumps({"files": len(manifest), "by_dataset": counts}, indent=2))


if __name__ == "__main__":
    main()
