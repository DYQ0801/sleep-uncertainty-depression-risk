#!/usr/bin/env python3
"""Extract whole-night architecture and dynamics from curated APPLES labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sleepdep import extract_night_features


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path("data/apples_curated")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/apples/sequence_features.csv"),
    )
    args = parser.parse_args()

    cohort = pd.read_csv(args.root / "analysis_cohort.csv", low_memory=False)
    records = []
    errors = []
    for path in sorted((args.root / "yasa").glob("*.npz")):
        try:
            with np.load(path, allow_pickle=False) as archive:
                stages = archive["y"].astype(int)
                if archive["x"].shape[0] != stages.size:
                    raise ValueError("feature and label epoch counts differ")
            record = {"fileid": path.stem, "epochs": len(stages)}
            record.update(extract_night_features(stages))
            records.append(record)
        except Exception as exc:
            errors.append({"fileid": path.stem, "error": str(exc)})

    features = pd.DataFrame(records)
    expected_ids = set(cohort.loc[cohort["has_yasa"], "fileid"])
    if set(features["fileid"]) != expected_ids:
        missing = sorted(expected_ids - set(features["fileid"]))
        raise ValueError(f"Missing valid YASA features for: {missing[:10]}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    features.to_csv(args.output, index=False)
    summary = {
        "subjects": len(features),
        "errors": errors,
        "feature_count": len(features.columns) - 2,
        "epoch_median": float(features["epochs"].median()),
        "recording_hours_median": float(features["recording_minutes"].median() / 60),
    }
    args.output.with_suffix(".summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
