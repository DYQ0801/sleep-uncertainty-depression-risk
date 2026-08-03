#!/usr/bin/env python3
"""Evaluate calibrated entropy, conditional residual, and cycle ablations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, roc_auc_score

from run_apples_clinical_experiments import (
    CONFOUNDERS,
    DYNAMICS,
    MACRO,
    OSA,
    leave_one_site_predictions,
    nested_predictions,
)


BASE = CONFOUNDERS + OSA + MACRO + DYNAMICS
CALIBRATED_ENTROPY = [
    "entropy_mean",
    "entropy_std",
    "entropy_p90",
    "posterior_margin_mean",
    "entropy_boundary_excess",
    "entropy_w_mean",
    "entropy_n1_mean",
    "entropy_n2_mean",
    "entropy_n3_mean",
    "entropy_rem_mean",
]
RESIDUAL = [
    "residual_entropy_mean",
    "residual_entropy_std",
    "residual_entropy_p90",
    "residual_boundary_excess",
    "residual_w_mean",
    "residual_n1_mean",
    "residual_n2_mean",
    "residual_n3_mean",
    "residual_rem_mean",
]
PHASE = [
    "residual_cycle_cycle_count",
    "residual_cycle_phase_1",
    "residual_cycle_phase_2",
    "residual_cycle_phase_3",
    "residual_cycle_phase_4",
    "residual_cycle_pre_rem_mean",
    "residual_cycle_cycle_drift",
]
FEATURE_SETS = {
    "E3_dynamics": BASE,
    "E4_calibrated_entropy": BASE + CALIBRATED_ENTROPY,
    "E5_conditional_residual": BASE + CALIBRATED_ENTROPY + RESIDUAL,
    "E6_cycle_phase": BASE + CALIBRATED_ENTROPY + RESIDUAL + PHASE,
}


def paired_deltas(frame, predictions, outcome, task, iterations=5000):
    rng = np.random.default_rng(20260802)
    y = frame[outcome].to_numpy()
    comparisons = {
        "E4_minus_E3": ("E4_calibrated_entropy", "E3_dynamics"),
        "E5_minus_E4": (
            "E5_conditional_residual",
            "E4_calibrated_entropy",
        ),
        "E6_minus_E5": ("E6_cycle_phase", "E5_conditional_residual"),
        "E6_minus_E3": ("E6_cycle_phase", "E3_dynamics"),
    }
    values = {name: [] for name in comparisons}
    for _ in range(iterations):
        indices = rng.integers(0, len(frame), len(frame))
        if task == "classification" and np.unique(y[indices]).size < 2:
            continue
        for name, (added, baseline) in comparisons.items():
            if task == "regression":
                delta = mean_absolute_error(
                    y[indices], predictions[baseline][indices]
                ) - mean_absolute_error(
                    y[indices], predictions[added][indices]
                )
            else:
                delta = roc_auc_score(
                    y[indices], predictions[added][indices]
                ) - roc_auc_score(
                    y[indices], predictions[baseline][indices]
                )
            values[name].append(delta)
    return {
        name: {
            "estimate": float(np.mean(result)),
            "ci": [
                float(np.quantile(result, 0.025)),
                float(np.quantile(result, 0.975)),
            ],
        }
        for name, result in values.items()
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cohort",
        type=Path,
        default=Path("data/apples_curated/analysis_cohort.csv"),
    )
    parser.add_argument(
        "--posterior-features",
        type=Path,
        default=Path("results/apples/posterior/posterior_features.csv"),
    )
    parser.add_argument(
        "--sequence-features",
        type=Path,
        default=Path("results/apples/sequence_features.csv"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/apples/posterior_ablation")
    )
    parser.add_argument("--seed", type=int, default=20260802)
    args = parser.parse_args()

    cohort = pd.read_csv(args.cohort, low_memory=False)
    sequence = pd.read_csv(args.sequence_features)
    posterior = pd.read_csv(args.posterior_features)
    frame = cohort.merge(
        sequence, on="fileid", how="inner", validate="one_to_one"
    ).merge(
        posterior,
        on="fileid",
        how="inner",
        validate="one_to_one",
        suffixes=("", "_posterior"),
    )
    frame = frame[frame["over_4h"]].reset_index(drop=True)
    if len(frame) != 798:
        raise ValueError(f"Expected 798 posterior subjects, found {len(frame)}")

    tasks = {
        "bdi_regression": ("bdi", "diagnosis_bdi", "regression"),
        "hamd_regression": ("hamd", "diagnosis_hamd", "regression"),
        "bdi_classification": (
            "diagnosis_bdi",
            "diagnosis_bdi",
            "classification",
        ),
        "hamd_classification": (
            "diagnosis_hamd",
            "diagnosis_hamd",
            "classification",
        ),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        "subjects": len(frame),
        "feature_sets": FEATURE_SETS,
        "tasks": {},
    }
    prediction_table = frame[
        [
            "fileid",
            "nsrrid",
            "site",
            "bdi",
            "hamd",
            "diagnosis_bdi",
            "diagnosis_hamd",
        ]
    ].copy()
    for task_name, (outcome, diagnosis, task) in tasks.items():
        nested_by_feature = {}
        loso_by_feature = {}
        task_report = {"nested_cv": {}, "leave_one_site_out": {}}
        for feature_name, columns in FEATURE_SETS.items():
            nested, folds, overall = nested_predictions(
                frame,
                columns,
                outcome,
                diagnosis,
                task,
                args.seed,
            )
            loso, sites, loso_overall = leave_one_site_predictions(
                frame,
                columns,
                outcome,
                diagnosis,
                task,
                args.seed,
            )
            nested_by_feature[feature_name] = nested
            loso_by_feature[feature_name] = loso
            task_report["nested_cv"][feature_name] = {
                "overall": overall,
                "folds": folds,
            }
            task_report["leave_one_site_out"][feature_name] = {
                "overall": loso_overall,
                "sites": sites,
            }
            prediction_table[
                f"{task_name}_{feature_name}_nested"
            ] = nested
            prediction_table[
                f"{task_name}_{feature_name}_loso"
            ] = loso
        task_report["nested_paired_deltas"] = paired_deltas(
            frame, nested_by_feature, outcome, task
        )
        task_report["loso_paired_deltas"] = paired_deltas(
            frame, loso_by_feature, outcome, task
        )
        report["tasks"][task_name] = task_report

    prediction_table.to_csv(args.output / "predictions.csv", index=False)
    (args.output / "metrics.json").write_text(
        json.dumps(report, indent=2, allow_nan=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                task: {
                    feature: values["overall"]
                    for feature, values in result["nested_cv"].items()
                }
                for task, result in report["tasks"].items()
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
