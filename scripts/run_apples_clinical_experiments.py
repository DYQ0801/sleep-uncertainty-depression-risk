#!/usr/bin/env python3
"""Nested and leave-one-site-out APPLES clinical/sequence experiments."""

from __future__ import annotations

import argparse
import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    mean_absolute_error,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


warnings.filterwarnings(
    "ignore", message=r".*encountered in matmul", category=RuntimeWarning
)

CONFOUNDERS = [
    "age_at_enrollment",
    "nsrr_sex",
    "nsrr_race",
    "nsrr_bmi",
    "site",
]
OSA = ["nsrr_ahi_chicago1999", "nsrr_phrnumar_f1"]
MACRO = [
    "nsrr_ttldursp_f1",
    "nsrr_ttleffsp_f1",
    "nsrr_ttllatsp_f1",
    "nsrr_ttlprdsp_s1sr",
    "nsrr_ttldurws_f1",
    "nsrr_pctdursp_s1",
    "nsrr_pctdursp_s2",
    "nsrr_pctdursp_s3",
    "nsrr_pctdursp_sr",
    "nsrr_ttlprdbd_f1",
]
DYNAMICS = [
    "stage_switches_per_hour",
    "short_sleep_bout_fraction",
    "n1_bout_mean_minutes",
    "n2_bout_mean_minutes",
    "n3_bout_mean_minutes",
    "rem_bout_mean_minutes",
    "p_n2_to_w",
    "p_n2_to_n3",
    "p_n2_to_rem",
    "p_n3_to_n2",
    "p_rem_to_w",
]
FEATURE_SETS = {
    "E0_confounders": CONFOUNDERS,
    "E1_osa_arousal": CONFOUNDERS + OSA,
    "E2_macrostructure": CONFOUNDERS + OSA + MACRO,
    "E3_dynamics": CONFOUNDERS + OSA + MACRO + DYNAMICS,
}


def preprocessor(frame: pd.DataFrame, columns):
    numeric = [c for c in columns if pd.api.types.is_numeric_dtype(frame[c])]
    categorical = [c for c in columns if c not in numeric]
    return ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric,
            ),
            (
                "categorical",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        (
                            "onehot",
                            OneHotEncoder(handle_unknown="ignore"),
                        ),
                    ]
                ),
                categorical,
            ),
        ]
    )


def model_pipeline(frame, columns, task):
    if task == "regression":
        model = Ridge(solver="lsqr")
    else:
        model = LogisticRegression(
            solver="liblinear",
            class_weight="balanced",
            max_iter=2000,
            random_state=20260802,
        )
    return Pipeline(
        [("transform", preprocessor(frame, columns)), ("model", model)]
    )


def tune_model(frame, train, columns, target, stratify, task, seed):
    inner = StratifiedKFold(n_splits=4, shuffle=True, random_state=seed)
    split_indices = list(
        inner.split(frame.iloc[train][columns], stratify[train])
    )
    if task == "regression":
        grid = {"model__alpha": np.logspace(-3, 3, 13)}
        scoring = "neg_mean_absolute_error"
    else:
        grid = {"model__C": np.logspace(-3, 1, 9)}
        scoring = "roc_auc"
    search = GridSearchCV(
        model_pipeline(frame.iloc[train], columns, task),
        grid,
        scoring=scoring,
        cv=split_indices,
        n_jobs=1,
        error_score="raise",
    )
    search.fit(frame.iloc[train][columns], target[train])
    return search


def regression_metrics(y, prediction):
    return {
        "mae": float(mean_absolute_error(y, prediction)),
        "rmse": float(mean_squared_error(y, prediction) ** 0.5),
        "r2": float(r2_score(y, prediction)),
        "spearman": float(spearmanr(y, prediction).statistic),
    }


def classification_metrics(y, probability):
    prediction = (probability >= 0.5).astype(int)
    return {
        "auroc": float(roc_auc_score(y, probability)),
        "auprc": float(average_precision_score(y, probability)),
        "balanced_accuracy": float(
            balanced_accuracy_score(y, prediction)
        ),
        "brier": float(brier_score_loss(y, probability)),
    }


def nested_predictions(frame, columns, outcome, diagnosis, task, seed):
    y = frame[outcome].to_numpy(dtype=float)
    strata = frame[diagnosis].to_numpy(dtype=int)
    outer = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    prediction = np.full(len(frame), np.nan)
    folds = []
    for fold, (train, test) in enumerate(
        outer.split(frame[columns], strata), start=1
    ):
        search = tune_model(
            frame,
            train,
            columns,
            y,
            strata,
            task,
            seed + fold,
        )
        if task == "regression":
            values = search.predict(frame.iloc[test][columns])
            metrics = regression_metrics(y[test], values)
        else:
            values = search.predict_proba(frame.iloc[test][columns])[:, 1]
            metrics = classification_metrics(y[test], values)
        if not np.isfinite(values).all():
            raise FloatingPointError("Non-finite APPLES prediction")
        prediction[test] = values
        folds.append(
            {
                "fold": fold,
                "n_train": len(train),
                "n_test": len(test),
                "best_params": search.best_params_,
                **metrics,
            }
        )
    overall = (
        regression_metrics(y, prediction)
        if task == "regression"
        else classification_metrics(y, prediction)
    )
    return prediction, folds, overall


def leave_one_site_predictions(
    frame, columns, outcome, diagnosis, task, seed
):
    y = frame[outcome].to_numpy(dtype=float)
    strata = frame[diagnosis].to_numpy(dtype=int)
    rows = []
    predictions = np.full(len(frame), np.nan)
    for index, site in enumerate(sorted(frame["site"].unique())):
        train = np.flatnonzero(frame["site"].to_numpy() != site)
        test = np.flatnonzero(frame["site"].to_numpy() == site)
        search = tune_model(
            frame,
            train,
            columns,
            y,
            strata,
            task,
            seed + index + 100,
        )
        if task == "regression":
            values = search.predict(frame.iloc[test][columns])
            metrics = regression_metrics(y[test], values)
        else:
            values = search.predict_proba(frame.iloc[test][columns])[:, 1]
            metrics = classification_metrics(y[test], values)
        predictions[test] = values
        rows.append(
            {
                "held_out_site": site,
                "n": len(test),
                "positive": int(strata[test].sum()),
                "best_params": search.best_params_,
                **metrics,
            }
        )
    overall = (
        regression_metrics(y, predictions)
        if task == "regression"
        else classification_metrics(y, predictions)
    )
    return predictions, rows, overall


def paired_bootstrap(frame, predictions, outcome, task, iterations=2000):
    rng = np.random.default_rng(20260802)
    y = frame[outcome].to_numpy()
    values = {
        "E3_minus_E2": [],
        "E2_minus_E0": [],
    }
    for _ in range(iterations):
        indices = rng.integers(0, len(frame), len(frame))
        if task == "regression":
            metric = lambda name: mean_absolute_error(
                y[indices], predictions[name][indices]
            )
            values["E3_minus_E2"].append(
                metric("E2_macrostructure") - metric("E3_dynamics")
            )
            values["E2_minus_E0"].append(
                metric("E0_confounders") - metric("E2_macrostructure")
            )
        else:
            if np.unique(y[indices]).size < 2:
                continue
            metric = lambda name: roc_auc_score(
                y[indices], predictions[name][indices]
            )
            values["E3_minus_E2"].append(
                metric("E3_dynamics") - metric("E2_macrostructure")
            )
            values["E2_minus_E0"].append(
                metric("E2_macrostructure") - metric("E0_confounders")
            )
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
        "--sequence-features",
        type=Path,
        default=Path("results/apples/sequence_features.csv"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/apples/clinical")
    )
    parser.add_argument("--seed", type=int, default=20260802)
    args = parser.parse_args()

    cohort = pd.read_csv(args.cohort, low_memory=False)
    sequence = pd.read_csv(args.sequence_features)
    frame = cohort.merge(
        sequence, on="fileid", how="inner", validate="one_to_one"
    )
    frame = frame[frame["over_4h"]].reset_index(drop=True)
    if len(frame) != 798:
        raise ValueError(f"Expected 798 >4h YASA subjects, found {len(frame)}")

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
        "selection": "valid YASA NPZ and TST >= 4 hours",
        "feature_sets": FEATURE_SETS,
        "tasks": {},
    }
    prediction_table = frame[
        ["fileid", "nsrrid", "site", "bdi", "hamd", "diagnosis_bdi", "diagnosis_hamd"]
    ].copy()
    for task_name, (outcome, diagnosis, task) in tasks.items():
        task_report = {"nested_cv": {}, "leave_one_site_out": {}}
        nested_by_feature = {}
        loso_by_feature = {}
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
        task_report["nested_paired_deltas"] = paired_bootstrap(
            frame, nested_by_feature, outcome, task
        )
        task_report["loso_paired_deltas"] = paired_bootstrap(
            frame, loso_by_feature, outcome, task
        )
        report["tasks"][task_name] = task_report

    prediction_table.to_csv(args.output / "predictions.csv", index=False)
    (args.output / "metrics.json").write_text(
        json.dumps(report, indent=2, allow_nan=True), encoding="utf-8"
    )
    print(json.dumps({
        name: {
            feature: values["overall"]
            for feature, values in result["nested_cv"].items()
        }
        for name, result in report["tasks"].items()
    }, indent=2))


if __name__ == "__main__":
    main()
