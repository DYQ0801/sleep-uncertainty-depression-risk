#!/usr/bin/env python3
"""Leave-one-dataset-out validation on the public Bovy et al. MDD sleep data."""

from __future__ import annotations

import json
import re
import sys
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
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sleepdep import masked_rk_dynamics_features


DATA_ROOT = ROOT / "data/external/bovy2022"
OUTPUT_ROOT = ROOT / "results/bovy2022"

CONFOUNDERS = ["age", "gender"]
MACRO = [
    "Total_sleep_time_min",
    "Sleep_Onset_min",
    "REM_onset_min",
    "S1_percent",
    "S2_percent",
    "SWS_percent",
    "REM_percent",
    "Wake_after_sleep_onset_percent",
]
MICRO = [
    "spin_dens",
    "spin_dur",
    "spin_amp",
    "spin_freq",
    "so_dens",
    "so_dur",
    "so_amp",
    "so_freq",
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
C_DUPLICATES_FROM_A = {
    "B0001465",
    "C0001233",
    "C0001238",
    "C0001251",
    "D0001406",
    "C0000913",
    "D0001049",
}

# NumPy linked against macOS Accelerate can emit false matmul warnings while
# returning finite values. Every model output is checked explicitly below.
warnings.filterwarnings(
    "ignore",
    message=r".*encountered in matmul",
    category=RuntimeWarning,
)


def _average_channels(path: Path, prefix: str) -> pd.DataFrame:
    frame = pd.read_csv(path)
    if prefix == "spin":
        mapping = {
            "density_per_epoch": "spin_dens",
            "mean_duration_seconds": "spin_dur",
            "mean_amplitude_trough2peak_potential": "spin_amp",
            "mean_frequency_by_mean_pk_trgh_cnt_per_dur": "spin_freq",
        }
    else:
        mapping = {
            "density_per_epoch": "so_dens",
            "mean_duration_seconds": "so_dur",
            "mean_amplitude_peak2trough_potential": "so_amp",
            "mean_frequency_by_duration": "so_freq",
        }
    return (
        frame.groupby("datasetnum", as_index=False)[list(mapping)]
        .mean()
        .rename(columns=mapping)
    )


def _hypnogram_key(dataset: str, data_name: str) -> str:
    name = str(data_name).strip().lower()
    if dataset == "b":
        match = re.match(r"(lk_\d+|lp_\d+_[12])", name)
        return match.group(1) if match else ""
    return name


def _masked_dynamics(path: Path):
    raw = np.loadtxt(path, usecols=0, dtype=int)
    return masked_rk_dynamics_features(raw)


def _attach_hypnogram_features(frame: pd.DataFrame, base: Path, dataset: str):
    files = {
        path.stem.lower(): path
        for path in (base / "hypnograms").glob("*.txt")
        if path.stem.lower() not in {"filenames", "readme"}
    }
    records = []
    for data_name in frame["data_name"]:
        path = files.get(_hypnogram_key(dataset, data_name))
        records.append(_masked_dynamics(path) if path else {})
    dynamics = pd.DataFrame(records, index=frame.index)
    frame = frame.join(dynamics)
    frame["has_hypnogram"] = frame[DYNAMICS].notna().all(axis=1)
    return frame


def load_dataset(name: str) -> pd.DataFrame:
    base = DATA_ROOT / f"dataset_{name}"
    subjects = pd.read_excel(base / "subject_info.xlsx")
    hypnogram = pd.read_csv(base / "hypvals.csv")
    spindle = _average_channels(base / "spindles.csv", "spin")
    slow_wave = _average_channels(base / "slow_waves.csv", "so")
    frame = subjects.merge(hypnogram, on="datasetnum", how="inner")
    frame = frame.merge(spindle, on="datasetnum", how="inner")
    frame = frame.merge(slow_wave, on="datasetnum", how="inner")
    frame["dataset_id"] = name.upper()
    if name in {"a", "c"}:
        frame["gender"] = frame["gender"].map({0: "m", 1: "f"})
    else:
        frame["gender"] = frame["gender"].str.lower()

    if name == "a":
        keep = frame["group"].isin(["Controls", "Patients"])
        frame["is_mdd"] = (frame["group"] == "Patients").astype(int)
        frame["hamd_current"] = frame["hamd_0"]
    elif name == "b":
        keep = frame["group"].isin(["control", "patient_unmed"])
        frame["is_mdd"] = (frame["group"] == "patient_unmed").astype(int)
        frame["hamd_current"] = frame["hamd_0"]
    else:
        keep = frame["group"].isin(["control", "patient_7"])
        frame = frame.loc[~frame["data_name"].isin(C_DUPLICATES_FROM_A)].copy()
        keep = frame["group"].isin(["control", "patient_7"])
        frame["is_mdd"] = (frame["group"] == "patient_7").astype(int)
        frame["hamd_current"] = frame["hamd_week1"]
    frame = frame.loc[keep].copy()
    frame["SWS_percent"] = frame["S3_percent"] + frame["S4_percent"]
    if frame["gender"].isna().any():
        raise ValueError(f"Unmapped gender value in dataset {name.upper()}")
    if frame["datasetnum"].duplicated().any():
        raise ValueError(f"Duplicate selected visit in dataset {name.upper()}")
    return _attach_hypnogram_features(frame, base, name)


def _preprocessor(frame: pd.DataFrame, columns):
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
                        ("onehot", OneHotEncoder(handle_unknown="ignore")),
                    ]
                ),
                categorical,
            ),
        ]
    )


def bootstrap_metric(y, prediction, metric, seed=20260802, iterations=2000):
    rng = np.random.default_rng(seed)
    values = []
    y = np.asarray(y)
    prediction = np.asarray(prediction)
    for _ in range(iterations):
        indices = rng.integers(0, len(y), len(y))
        if np.unique(y[indices]).size < 2 and metric in {
            roc_auc_score,
            average_precision_score,
        }:
            continue
        values.append(metric(y[indices], prediction[indices]))
    return [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]


def diagnosis_experiment(frame: pd.DataFrame, feature_sets=None):
    if feature_sets is None:
        feature_sets = {
            "confounders": CONFOUNDERS,
            "macro": CONFOUNDERS + MACRO,
            "macro_micro": CONFOUNDERS + MACRO + MICRO,
        }
    rows = []
    predictions = []
    for held_out in sorted(frame["dataset_id"].unique()):
        train = frame[frame["dataset_id"] != held_out]
        test = frame[frame["dataset_id"] == held_out]
        inner = GroupKFold(n_splits=2)
        for feature_name, columns in feature_sets.items():
            model = Pipeline(
                [
                    ("transform", _preprocessor(train, columns)),
                    (
                        "model",
                        LogisticRegression(
                            class_weight="balanced",
                            solver="liblinear",
                            max_iter=2000,
                            random_state=20260802,
                        ),
                    ),
                ]
            )
            search = GridSearchCV(
                model,
                {"model__C": np.logspace(-3, 1, 9)},
                scoring="roc_auc",
                cv=inner,
                n_jobs=1,
                error_score="raise",
            )
            search.fit(
                train[columns],
                train["is_mdd"],
                groups=train["dataset_id"],
            )
            probability = search.predict_proba(test[columns])[:, 1]
            if not np.isfinite(probability).all():
                raise FloatingPointError("Non-finite diagnosis probability")
            prediction = (probability >= 0.5).astype(int)
            y = test["is_mdd"].to_numpy()
            rows.append(
                {
                    "held_out_dataset": held_out,
                    "features": feature_name,
                    "n": len(test),
                    "mdd": int(y.sum()),
                    "best_c": search.best_params_["model__C"],
                    "auroc": roc_auc_score(y, probability),
                    "auroc_ci": bootstrap_metric(y, probability, roc_auc_score),
                    "auprc": average_precision_score(y, probability),
                    "balanced_accuracy": balanced_accuracy_score(y, prediction),
                    "brier": brier_score_loss(y, probability),
                }
            )
            predictions.extend(
                {
                    "dataset_id": held_out,
                    "data_name": subject,
                    "features": feature_name,
                    "label": int(label),
                    "probability": float(prob),
                }
                for subject, label, prob in zip(test["data_name"], y, probability)
            )
    return rows, predictions


def severity_experiment(frame: pd.DataFrame):
    patients = frame[(frame["is_mdd"] == 1) & frame["hamd_current"].notna()].copy()
    rows = []
    predictions = []
    for held_out in sorted(patients["dataset_id"].unique()):
        train = patients[patients["dataset_id"] != held_out]
        test = patients[patients["dataset_id"] == held_out]
        inner = GroupKFold(n_splits=2)
        for feature_name, columns in {
            "macro": CONFOUNDERS + MACRO,
            "macro_micro": CONFOUNDERS + MACRO + MICRO,
        }.items():
            model = Pipeline(
                [
                    ("transform", _preprocessor(train, columns)),
                    ("model", Ridge(solver="lsqr")),
                ]
            )
            search = GridSearchCV(
                model,
                {"model__alpha": np.logspace(-3, 3, 13)},
                scoring="neg_mean_absolute_error",
                cv=inner,
                n_jobs=1,
                error_score="raise",
            )
            search.fit(
                train[columns],
                train["hamd_current"],
                groups=train["dataset_id"],
            )
            pred = search.predict(test[columns])
            if not np.isfinite(pred).all():
                raise FloatingPointError("Non-finite severity prediction")
            y = test["hamd_current"].to_numpy()
            rows.append(
                {
                    "held_out_dataset": held_out,
                    "features": feature_name,
                    "n": len(test),
                    "best_alpha": search.best_params_["model__alpha"],
                    "mae": mean_absolute_error(y, pred),
                    "rmse": mean_squared_error(y, pred) ** 0.5,
                    "r2": r2_score(y, pred),
                    "spearman": spearmanr(y, pred).statistic,
                }
            )
            predictions.extend(
                {
                    "dataset_id": held_out,
                    "data_name": subject,
                    "features": feature_name,
                    "hamd": float(label),
                    "prediction": float(value),
                }
                for subject, label, value in zip(test["data_name"], y, pred)
            )
    return rows, predictions


def diagnosis_summary(predictions, delta_pairs):
    frame = pd.DataFrame(predictions)
    summaries = {}
    for feature_name, group in frame.groupby("features"):
        dataset_aurocs = [
            roc_auc_score(part["label"], part["probability"])
            for _, part in group.groupby("dataset_id")
        ]
        summaries[feature_name] = {
            "pooled_auroc": roc_auc_score(group["label"], group["probability"]),
            "pooled_auroc_ci": bootstrap_metric(
                group["label"], group["probability"], roc_auc_score
            ),
            "macro_average_auroc": float(np.mean(dataset_aurocs)),
            "worst_dataset_auroc": float(np.min(dataset_aurocs)),
        }

    wide = frame.pivot(
        index=["dataset_id", "data_name"],
        columns="features",
        values=["label", "probability"],
    )
    rng = np.random.default_rng(20260802)
    deltas = {name: [] for name in delta_pairs}
    for _ in range(2000):
        sampled = []
        for dataset in wide.index.get_level_values("dataset_id").unique():
            part = wide.loc[dataset]
            indices = rng.integers(0, len(part), len(part))
            sampled.append(part.iloc[indices])
        sample = pd.concat(sampled, ignore_index=True)
        reference_feature = next(iter(delta_pairs.values()))[0]
        y = sample[("label", reference_feature)].to_numpy()
        for name, (added, baseline) in delta_pairs.items():
            deltas[name].append(
                roc_auc_score(y, sample[("probability", added)])
                - roc_auc_score(y, sample[("probability", baseline)])
            )
    delta_summary = {
        name: {
            "estimate": float(np.mean(values)),
            "ci": [
                float(np.quantile(values, 0.025)),
                float(np.quantile(values, 0.975)),
            ],
        }
        for name, values in deltas.items()
    }
    return summaries, delta_summary


def main():
    frame = pd.concat([load_dataset(name) for name in "abc"], ignore_index=True)
    expected_counts = {"A": 80, "B": 80, "C": 59}
    actual_counts = frame["dataset_id"].value_counts().to_dict()
    if actual_counts != expected_counts:
        raise ValueError(f"Unexpected cohort counts: {actual_counts}")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT_ROOT / "analysis_cohort.csv", index=False)

    diagnosis, diagnosis_predictions = diagnosis_experiment(frame)
    dynamics_frame = frame[frame["has_hypnogram"]].copy()
    dynamics_sets = {
        "confounders_cc": CONFOUNDERS,
        "macro_cc": CONFOUNDERS + MACRO,
        "macro_dynamics": CONFOUNDERS + MACRO + DYNAMICS,
        "macro_dynamics_micro": CONFOUNDERS + MACRO + DYNAMICS + MICRO,
    }
    dynamics_diagnosis, dynamics_predictions = diagnosis_experiment(
        dynamics_frame, dynamics_sets
    )
    severity, severity_predictions = severity_experiment(frame)
    diagnosis_aggregate, diagnosis_deltas = diagnosis_summary(
        diagnosis_predictions,
        {
            "macro_minus_confounders": ("macro", "confounders"),
            "macro_micro_minus_macro": ("macro_micro", "macro"),
        },
    )
    dynamics_aggregate, dynamics_deltas = diagnosis_summary(
        dynamics_predictions,
        {
            "macro_dynamics_minus_macro": ("macro_dynamics", "macro_cc"),
            "macro_dynamics_micro_minus_macro_dynamics": (
                "macro_dynamics_micro",
                "macro_dynamics",
            ),
        },
    )
    pd.DataFrame(diagnosis_predictions).to_csv(
        OUTPUT_ROOT / "diagnosis_predictions.csv", index=False
    )
    pd.DataFrame(severity_predictions).to_csv(
        OUTPUT_ROOT / "severity_predictions.csv", index=False
    )
    pd.DataFrame(dynamics_predictions).to_csv(
        OUTPUT_ROOT / "dynamics_diagnosis_predictions.csv", index=False
    )
    report = {
        "source": "Bovy et al., NeuroImage: Clinical 2022, OSF bdez9",
        "cohort": {
            "records": len(frame),
            "by_dataset_and_label": frame.groupby(["dataset_id", "is_mdd"])
            .size()
            .to_dict(),
            "known_cross_dataset_duplicates_removed_from_c": sorted(
                C_DUPLICATES_FROM_A
            ),
        },
        "diagnosis": diagnosis,
        "diagnosis_aggregate": diagnosis_aggregate,
        "diagnosis_paired_deltas": diagnosis_deltas,
        "dynamics_complete_case_records": len(dynamics_frame),
        "dynamics_diagnosis": dynamics_diagnosis,
        "dynamics_aggregate": dynamics_aggregate,
        "dynamics_paired_deltas": dynamics_deltas,
        "severity": severity,
        "limitations": [
            "No stage posterior probabilities are public, so entropy is not tested.",
            "Dataset A patients were medicated; B patients were unmedicated; C patients were medicated for 7 days.",
            "Hardware and channel references differ across datasets.",
        ],
    }
    # JSON does not support tuple dictionary keys.
    report["cohort"]["by_dataset_and_label"] = {
        f"{dataset}/label_{label}": int(count)
        for (dataset, label), count in frame.groupby(["dataset_id", "is_mdd"])
        .size()
        .items()
    }
    (OUTPUT_ROOT / "external_validation.json").write_text(
        json.dumps(report, indent=2, allow_nan=True), encoding="utf-8"
    )
    print(json.dumps(report, indent=2, allow_nan=True))


if __name__ == "__main__":
    main()
