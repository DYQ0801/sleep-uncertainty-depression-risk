#!/usr/bin/env python3
"""Nested-CV APPLES phenotype baselines for BDI-I prediction."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, KFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


CONFOUNDERS = [
    "age",
    "gender",
    "ethnicity",
    "bmihp",
    "site",
    "depressionmedhxhp",
    "nsrr_age",
    "nsrr_sex",
    "nsrr_race",
]
SLEEP_FEATURES = [
    "nsrr_ahi_chicago1999",
    "nsrr_phrnumar_f1",
    "nsrr_ttldursp_f1",
    "nsrr_pctdursp_s1",
    "nsrr_pctdursp_s2",
    "nsrr_pctdursp_s3",
    "nsrr_pctdursp_sr",
    "nsrr_ttldurws_f1",
    "nsrr_ttleffsp_f1",
    "nsrr_ttllatsp_f1",
    "nsrr_ttlprdbd_f1",
    "nsrr_ttlprdsp_s1s4",
]


def make_pipeline(frame: pd.DataFrame, columns):
    numeric = [c for c in columns if pd.api.types.is_numeric_dtype(frame[c])]
    categorical = [c for c in columns if c not in numeric]
    transform = ColumnTransformer(
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
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
        ]
    )
    return Pipeline([("transform", transform), ("model", Ridge(solver="lsqr"))])


def evaluate(frame: pd.DataFrame, columns, seed: int):
    x = frame[columns]
    y = frame["bditotalscore"].astype(float).to_numpy()
    outer = KFold(n_splits=5, shuffle=True, random_state=seed)
    predictions = np.full(y.shape, np.nan)
    fold_rows = []
    for fold, (train, test) in enumerate(outer.split(x), start=1):
        inner = KFold(n_splits=4, shuffle=True, random_state=seed + fold)
        search = GridSearchCV(
            make_pipeline(frame, columns),
            {"model__alpha": np.logspace(-3, 3, 13)},
            scoring="neg_mean_absolute_error",
            cv=inner,
            n_jobs=-1,
        )
        search.fit(x.iloc[train], y[train])
        pred = search.predict(x.iloc[test])
        predictions[test] = pred
        fold_rows.append(
            {
                "fold": fold,
                "n_train": len(train),
                "n_test": len(test),
                "alpha": search.best_params_["model__alpha"],
                "mae": mean_absolute_error(y[test], pred),
                "rmse": mean_squared_error(y[test], pred) ** 0.5,
                "r2": r2_score(y[test], pred),
                "spearman": spearmanr(y[test], pred).statistic,
            }
        )
    return {
        "columns": columns,
        "folds": fold_rows,
        "oof": {
            "mae": mean_absolute_error(y, predictions),
            "rmse": mean_squared_error(y, predictions) ** 0.5,
            "r2": r2_score(y, predictions),
            "spearman": spearmanr(y, predictions).statistic,
        },
    }, predictions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("results/apples_baseline"))
    parser.add_argument("--seed", type=int, default=20260802)
    args = parser.parse_args()

    frame = pd.read_csv(args.dataset, low_memory=False)
    required = {"appleid", "bditotalscore"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {sorted(missing)}")

    frame = frame.loc[frame["bditotalscore"].notna()].copy()
    # Subject-level evaluation: never allow repeated visits into separate folds.
    frame = frame.sort_values("appleid").drop_duplicates("appleid", keep="first")
    available_confounders = [c for c in CONFOUNDERS if c in frame.columns]
    available_sleep = [c for c in SLEEP_FEATURES if c in frame.columns]
    if not available_confounders or not available_sleep:
        raise ValueError(
            "Expected APPLES confounder and harmonized sleep columns were not found"
        )

    feature_sets = {
        "confounders": available_confounders,
        "sleep_only": available_sleep,
        "confounders_plus_sleep": available_confounders + available_sleep,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "outcome": "bditotalscore (BDI-I continuous)",
        "subjects": len(frame),
        "protocol": "5-fold outer CV with 4-fold inner alpha selection",
        "models": {},
    }
    prediction_frame = frame[["appleid", "bditotalscore"]].copy()
    for name, columns in feature_sets.items():
        result, predictions = evaluate(frame, columns, args.seed)
        report["models"][name] = result
        prediction_frame[f"pred_{name}"] = predictions

    prediction_frame.to_csv(args.output_dir / "oof_predictions.csv", index=False)
    (args.output_dir / "metrics.json").write_text(
        json.dumps(report, indent=2, allow_nan=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, allow_nan=True))


if __name__ == "__main__":
    main()
