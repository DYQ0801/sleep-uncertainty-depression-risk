#!/usr/bin/env python3
"""Build a subject-level APPLES analysis cohort across BL and DX visits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path("data/apples_curated")
    )
    args = parser.parse_args()

    clinical = args.root / "clinical"
    labels = pd.read_csv(clinical / "subject_labels_diagnosis.csv").rename(
        columns={"subid": "fileid"}
    )
    long_nights = pd.read_csv(clinical / "subject_labels_morethan4h.csv")[
        ["subid", "TST"]
    ].rename(columns={"subid": "fileid", "TST": "tst_label_minutes"})
    source = pd.read_csv(
        clinical / "apples-dataset-0.1.0.csv", low_memory=False
    )
    harmonized = pd.read_csv(
        clinical / "apples-harmonized-dataset-0.1.0.csv",
        low_memory=False,
    )

    baseline_source = source[source["visitn"] == 1][
        [
            "appleid",
            "age",
            "gender",
            "ethnicity",
            "depressionmedhxhp",
            "bditotalscore",
            "hamdtotalscore",
        ]
    ].copy()
    baseline_harmonized = harmonized[harmonized["visitn"] == 1][
        [
            "nsrrid",
            "age_at_enrollment",
            "nsrr_age",
            "nsrr_sex",
            "nsrr_race",
            "nsrr_bmi",
        ]
    ].copy()
    diagnostic = harmonized[harmonized["fileid"].notna()].copy()
    diagnostic = diagnostic.drop(
        columns=[
            "age_at_enrollment",
            "nsrr_age",
            "nsrr_sex",
            "nsrr_race",
            "nsrr_bmi",
        ]
    )

    cohort = labels.merge(
        diagnostic,
        on="fileid",
        how="left",
        validate="one_to_one",
    )
    cohort = cohort.merge(
        baseline_source,
        left_on="nsrrid",
        right_on="appleid",
        how="left",
        validate="one_to_one",
    )
    cohort = cohort.merge(
        baseline_harmonized,
        on="nsrrid",
        how="left",
        validate="one_to_one",
    )
    cohort = cohort.merge(
        long_nights, on="fileid", how="left", validate="one_to_one"
    )
    cohort["over_4h"] = cohort["tst_label_minutes"].notna()
    raw_ids = {path.stem for path in (args.root / "raw_1ch").glob("*.npz")}
    yasa_ids = {path.stem for path in (args.root / "yasa").glob("*.npz")}
    cohort["has_raw_1ch"] = cohort["fileid"].isin(raw_ids)
    cohort["has_yasa"] = cohort["fileid"].isin(yasa_ids)

    if len(cohort) != 1073 or not cohort["fileid"].is_unique:
        raise ValueError("Unexpected APPLES cohort size or duplicate file IDs")
    if cohort["nsrrid"].isna().any():
        raise ValueError("Some APPLES labels do not match diagnostic PSG rows")
    if not cohort["bdi"].equals(cohort["bditotalscore"]):
        raise ValueError("BDI values disagree between label and phenotype files")
    if not cohort["hamd"].equals(cohort["hamdtotalscore"]):
        raise ValueError("HAMD values disagree between label and phenotype files")

    cohort.to_csv(args.root / "analysis_cohort.csv", index=False)
    summary = {
        "subjects": len(cohort),
        "over_4h": int(cohort["over_4h"].sum()),
        "raw_1ch": int(cohort["has_raw_1ch"].sum()),
        "raw_1ch_over_4h": int(
            (cohort["has_raw_1ch"] & cohort["over_4h"]).sum()
        ),
        "yasa": int(cohort["has_yasa"].sum()),
        "yasa_over_4h": int(
            (cohort["has_yasa"] & cohort["over_4h"]).sum()
        ),
        "bdi_positive": int(cohort["diagnosis_bdi"].sum()),
        "hamd_positive": int(cohort["diagnosis_hamd"].sum()),
        "sites": {
            str(key): int(value)
            for key, value in cohort["site"].value_counts().items()
        },
        "missing": {
            column: int(cohort[column].isna().sum())
            for column in [
                "age_at_enrollment",
                "nsrr_sex",
                "nsrr_race",
                "nsrr_bmi",
                "nsrr_ahi_chicago1999",
                "nsrr_phrnumar_f1",
                "nsrr_ttldursp_f1",
                "nsrr_ttleffsp_f1",
            ]
        },
    }
    (args.root / "cohort_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
