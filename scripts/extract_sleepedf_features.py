#!/usr/bin/env python3
"""Extract whole-night features from the real Sleep-EDF files bundled upstream."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sleepdep.features import extract_night_features  # noqa: E402


def read_labels(path: Path) -> np.ndarray:
    with h5py.File(path, "r") as handle:
        labels = np.asarray(handle["label"]).reshape(-1).astype(int)
    # The official L-SeqSleepNet files encode W/N1/N2/N3/REM as 1..5.
    if labels.min() >= 1 and labels.max() <= 5:
        labels = labels - 1
    return labels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=ROOT / "external/l-seqsleepnet/sleepedf-20/mat_30min",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "results/sleepedf/night_features.csv",
    )
    args = parser.parse_args()

    rows = []
    failures = []
    for path in sorted(args.input_dir.glob("*.mat")):
        try:
            labels = read_labels(path)
            rows.append({"subject_night": path.stem, **extract_night_features(labels)})
        except Exception as exc:
            failures.append({"file": str(path), "error": str(exc)})

    if not rows:
        raise RuntimeError(f"No valid MAT files found in {args.input_dir}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(args.output, index=False)
    report = {
        "source": "L-SeqSleepNet bundled Sleep-EDF-20 prepared files",
        "records": len(frame),
        "failures": failures,
        "feature_count": len(frame.columns) - 1,
        "tst_minutes": frame["tst_minutes"].describe().to_dict(),
        "sleep_efficiency": frame["sleep_efficiency"].describe().to_dict(),
        "rem_latency_minutes": frame["rem_latency_minutes"].describe().to_dict(),
    }
    report_path = args.output.with_suffix(".summary.json")
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), **report}, indent=2))


if __name__ == "__main__":
    main()
