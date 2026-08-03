#!/usr/bin/env python3
"""Generate subject-disjoint calibrated APPLES stage posteriors and features."""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.linear_model import Ridge, SGDClassifier
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    f1_score,
    log_loss,
)
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sleepdep import extract_night_features


STAGE_NAMES = ("w", "n1", "n2", "n3", "rem")

warnings.filterwarnings(
    "ignore", message=r".*encountered in matmul", category=RuntimeWarning
)


def softmax(logits, temperature=1.0):
    scaled = logits / temperature
    return np.exp(scaled - logsumexp(scaled, axis=1, keepdims=True))


def normalized_entropy(probabilities):
    clipped = np.clip(probabilities, 1e-12, 1.0)
    return -np.sum(clipped * np.log(clipped), axis=1) / np.log(5)


def expected_calibration_error(y, probabilities, bins=15):
    confidence = probabilities.max(axis=1)
    correct = probabilities.argmax(axis=1) == y
    result = 0.0
    edges = np.linspace(0, 1, bins + 1)
    for lower, upper in zip(edges[:-1], edges[1:]):
        mask = (confidence > lower) & (confidence <= upper)
        if np.any(mask):
            result += np.mean(mask) * abs(
                np.mean(confidence[mask]) - np.mean(correct[mask])
            )
    return float(result)


def fit_temperature(logits, y):
    def objective(log_temperature):
        temperature = np.exp(log_temperature)
        return log_loss(y, softmax(logits, temperature), labels=np.arange(5))

    result = minimize_scalar(
        objective,
        bounds=(np.log(0.2), np.log(5.0)),
        method="bounded",
        options={"xatol": 1e-4},
    )
    return float(np.exp(result.x))


def transition_distance(stages, cap=20):
    stages = np.asarray(stages)
    boundary = np.r_[True, stages[1:] != stages[:-1]]
    distance = np.full(stages.size, cap, dtype=float)
    last = -cap
    for index in range(stages.size):
        if boundary[index]:
            last = index
        distance[index] = min(index - last, cap)
    last = stages.size + cap
    for index in range(stages.size - 1, -1, -1):
        if boundary[index]:
            last = index
        distance[index] = min(distance[index], last - index, cap)
    return distance


def condition_frame(stages, site, ahi):
    return pd.DataFrame(
        {
            "stage": stages.astype(str),
            "site": str(site),
            "transition_distance": transition_distance(stages),
            "ahi": float(ahi),
        }
    )


def fit_conditional_baseline(rows, entropy):
    transform = ColumnTransformer(
        [
            (
                "numeric",
                StandardScaler(),
                ["transition_distance", "ahi"],
            ),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore"),
                ["stage", "site"],
            ),
        ]
    )
    model = Pipeline(
        [("transform", transform), ("model", Ridge(alpha=10.0, solver="lsqr"))]
    )
    model.fit(rows, entropy)
    return model


def cycle_signal_features(values, stages, prefix):
    values = np.asarray(values, dtype=float)
    stages = np.asarray(stages, dtype=int)
    starts = np.r_[0, np.flatnonzero(stages[1:] != stages[:-1]) + 1]
    ends = np.r_[starts[1:], len(stages)]
    rem_bouts = [
        (start, end)
        for start, end in zip(starts, ends)
        if stages[start] == 4 and end - start >= 10
    ]
    sleep = np.flatnonzero(stages != 0)
    result = {f"{prefix}_cycle_count": 0.0}
    for phase in range(1, 5):
        result[f"{prefix}_phase_{phase}"] = np.nan
    result[f"{prefix}_pre_rem_mean"] = np.nan
    result[f"{prefix}_cycle_drift"] = np.nan
    if not rem_bouts or not sleep.size:
        return result

    cycle_start = int(sleep[0])
    phase_values = [[] for _ in range(4)]
    cycle_means = []
    pre_rem = []
    for rem_start, rem_end in rem_bouts:
        if rem_end <= cycle_start:
            continue
        indices = np.arange(cycle_start, rem_end)
        phase_bins = np.minimum(np.arange(indices.size) * 4 // indices.size, 3)
        for phase in range(4):
            phase_values[phase].extend(values[indices[phase_bins == phase]])
        cycle_means.append(float(np.mean(values[indices])))
        pre_start = max(cycle_start, rem_start - 20)
        pre_rem.extend(values[pre_start:rem_start])
        cycle_start = rem_end
    count = len(cycle_means)
    result[f"{prefix}_cycle_count"] = float(count)
    for phase, phase_data in enumerate(phase_values, start=1):
        if phase_data:
            result[f"{prefix}_phase_{phase}"] = float(np.mean(phase_data))
    if pre_rem:
        result[f"{prefix}_pre_rem_mean"] = float(np.mean(pre_rem))
    if count >= 2:
        result[f"{prefix}_cycle_drift"] = float(
            np.polyfit(np.arange(count), cycle_means, 1)[0]
        )
    return result


def residual_features(residual, stages):
    residual = np.asarray(residual)
    stages = np.asarray(stages)
    boundary = np.r_[False, stages[1:] != stages[:-1]]
    result = {
        "residual_entropy_mean": float(np.mean(residual)),
        "residual_entropy_std": float(np.std(residual)),
        "residual_entropy_p90": float(np.quantile(residual, 0.9)),
        "residual_boundary_mean": (
            float(np.mean(residual[boundary])) if np.any(boundary) else np.nan
        ),
        "residual_stable_mean": float(np.mean(residual[~boundary])),
    }
    result["residual_boundary_excess"] = (
        result["residual_boundary_mean"] - result["residual_stable_mean"]
    )
    for index, name in enumerate(STAGE_NAMES):
        mask = stages == index
        result[f"residual_{name}_mean"] = (
            float(np.mean(residual[mask])) if np.any(mask) else np.nan
        )
    result.update(cycle_signal_features(residual, stages, "residual_cycle"))
    return result


def load_subjects(root, cohort):
    subjects = {}
    for row in cohort.itertuples(index=False):
        path = root / "yasa" / f"{row.fileid}.npz"
        with np.load(path, allow_pickle=False) as archive:
            subjects[row.fileid] = {
                "x": archive["x"].astype(np.float32),
                "y": archive["y"].astype(np.int32),
                "site": row.site,
                "ahi": row.nsrr_ahi_chicago1999,
                "diagnosis_bdi": row.diagnosis_bdi,
            }
    return subjects


def concatenate(subjects, ids, means=None):
    x = np.concatenate([subjects[subject]["x"] for subject in ids])
    y = np.concatenate([subjects[subject]["y"] for subject in ids])
    if means is None:
        means = np.nanmean(x, axis=0)
    missing = np.where(np.isnan(x))
    if missing[0].size:
        x[missing] = means[missing[1]]
    return x, y, means


def model_logits(classifier, x):
    if hasattr(classifier, "decision_function"):
        return classifier.decision_function(x)
    probabilities = np.clip(classifier.predict_proba(x), 1e-8, 1.0)
    return np.log(probabilities)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path("data/apples_curated")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("results/apples/posterior")
    )
    parser.add_argument(
        "--classifier",
        choices=["sgd", "extra_trees"],
        default="sgd",
    )
    parser.add_argument("--seed", type=int, default=20260802)
    args = parser.parse_args()

    cohort = pd.read_csv(args.root / "analysis_cohort.csv", low_memory=False)
    cohort = cohort[cohort["has_yasa"] & cohort["over_4h"]].reset_index(drop=True)
    if len(cohort) != 798:
        raise ValueError(f"Expected 798 APPLES subjects, found {len(cohort)}")
    subjects = load_subjects(args.root, cohort)
    ids = cohort["fileid"].to_numpy()
    strata = (
        cohort["site"].astype(str)
        + "_"
        + cohort["diagnosis_bdi"].astype(str)
    ).to_numpy()
    outer = StratifiedKFold(n_splits=5, shuffle=True, random_state=args.seed)
    args.output.mkdir(parents=True, exist_ok=True)
    posterior_dir = args.output / "subjects"
    posterior_dir.mkdir(parents=True, exist_ok=True)
    feature_rows = []
    fold_rows = []

    for fold, (train_index, test_index) in enumerate(
        outer.split(ids, strata), start=1
    ):
        train_ids = ids[train_index]
        test_ids = ids[test_index]
        train_sites = cohort.iloc[train_index]["site"].astype(str).to_numpy()
        model_ids, calibration_ids = train_test_split(
            train_ids,
            test_size=0.2,
            random_state=args.seed + fold,
            stratify=train_sites,
        )
        x_train, y_train, means = concatenate(subjects, model_ids)
        scaler = StandardScaler()
        x_train = scaler.fit_transform(x_train)
        counts = np.bincount(y_train, minlength=5)
        class_weights = len(y_train) / (5 * counts)
        if args.classifier == "sgd":
            classifier = SGDClassifier(
                loss="log_loss",
                penalty="l2",
                alpha=1e-4,
                max_iter=100,
                tol=1e-3,
                early_stopping=True,
                validation_fraction=0.1,
                n_iter_no_change=5,
                average=True,
                random_state=args.seed + fold,
            )
            classifier.fit(
                x_train, y_train, sample_weight=class_weights[y_train]
            )
        else:
            classifier = ExtraTreesClassifier(
                n_estimators=160,
                min_samples_leaf=3,
                max_features="sqrt",
                class_weight="balanced",
                n_jobs=-1,
                random_state=args.seed + fold,
            )
            classifier.fit(x_train, y_train)
        del x_train, y_train

        calibration_logits = []
        calibration_y = []
        calibration_conditions = []
        for subject in calibration_ids:
            item = subjects[subject]
            x = item["x"].copy()
            missing = np.where(np.isnan(x))
            if missing[0].size:
                x[missing] = means[missing[1]]
            logits = model_logits(classifier, scaler.transform(x))
            calibration_logits.append(logits)
            calibration_y.append(item["y"])
        calibration_logits = np.concatenate(calibration_logits)
        calibration_y = np.concatenate(calibration_y)
        temperature = fit_temperature(calibration_logits, calibration_y)

        offset = 0
        calibration_entropy = []
        for subject in calibration_ids:
            item = subjects[subject]
            count = len(item["y"])
            probabilities = softmax(
                calibration_logits[offset : offset + count], temperature
            )
            predicted = probabilities.argmax(axis=1)
            entropy = normalized_entropy(probabilities)
            sample = np.linspace(
                0, count - 1, min(count, 300), dtype=int
            )
            calibration_conditions.append(
                condition_frame(
                    predicted[sample], item["site"], item["ahi"]
                )
            )
            calibration_entropy.append(entropy[sample])
            offset += count
        condition_model = fit_conditional_baseline(
            pd.concat(calibration_conditions, ignore_index=True),
            np.concatenate(calibration_entropy),
        )

        fold_y = []
        fold_uncalibrated = []
        fold_calibrated = []
        for subject in test_ids:
            item = subjects[subject]
            x = item["x"].copy()
            missing = np.where(np.isnan(x))
            if missing[0].size:
                x[missing] = means[missing[1]]
            logits = model_logits(classifier, scaler.transform(x))
            uncalibrated = softmax(logits)
            calibrated = softmax(logits, temperature)
            if not np.isfinite(calibrated).all():
                raise FloatingPointError("Non-finite calibrated posterior")
            predicted = calibrated.argmax(axis=1)
            entropy = normalized_entropy(calibrated)
            expected = condition_model.predict(
                condition_frame(predicted, item["site"], item["ahi"])
            )
            residual = entropy - expected
            features = {"fileid": subject, "posterior_fold": fold}
            features.update(extract_night_features(predicted, calibrated))
            features.update(residual_features(residual, predicted))
            feature_rows.append(features)
            np.savez_compressed(
                posterior_dir / f"{subject}.npz",
                probabilities=calibrated.astype(np.float32),
                stages=item["y"],
                predicted_stages=predicted.astype(np.int8),
                entropy_residual=residual.astype(np.float32),
                fold=np.int8(fold),
                temperature=np.float32(temperature),
            )
            fold_y.append(item["y"])
            fold_uncalibrated.append(uncalibrated)
            fold_calibrated.append(calibrated)

        fold_y = np.concatenate(fold_y)
        fold_uncalibrated = np.concatenate(fold_uncalibrated)
        fold_calibrated = np.concatenate(fold_calibrated)
        prediction = fold_calibrated.argmax(axis=1)
        fold_rows.append(
            {
                "fold": fold,
                "model_subjects": len(model_ids),
                "calibration_subjects": len(calibration_ids),
                "test_subjects": len(test_ids),
                "test_epochs": len(fold_y),
                "temperature": temperature,
                "accuracy": float(accuracy_score(fold_y, prediction)),
                "balanced_accuracy": float(
                    balanced_accuracy_score(fold_y, prediction)
                ),
                "macro_f1": float(
                    f1_score(fold_y, prediction, average="macro")
                ),
                "uncalibrated_nll": float(
                    log_loss(
                        fold_y, fold_uncalibrated, labels=np.arange(5)
                    )
                ),
                "calibrated_nll": float(
                    log_loss(fold_y, fold_calibrated, labels=np.arange(5))
                ),
                "uncalibrated_ece": expected_calibration_error(
                    fold_y, fold_uncalibrated
                ),
                "calibrated_ece": expected_calibration_error(
                    fold_y, fold_calibrated
                ),
            }
        )

    features = pd.DataFrame(feature_rows).sort_values("fileid")
    if len(features) != len(cohort) or not features["fileid"].is_unique:
        raise ValueError("OOF posterior features are incomplete or duplicated")
    features.to_csv(args.output / "posterior_features.csv", index=False)
    summary = {
        "subjects": len(features),
        "protocol": (
            "5-fold subject-level OOF; each training fold reserves 20% "
            "of subjects for temperature calibration and conditional baseline"
        ),
        "classifier": args.classifier,
        "folds": fold_rows,
        "mean": {
            key: float(np.mean([row[key] for row in fold_rows]))
            for key in [
                "accuracy",
                "balanced_accuracy",
                "macro_f1",
                "uncalibrated_nll",
                "calibrated_nll",
                "uncalibrated_ece",
                "calibrated_ece",
            ]
        },
    }
    (args.output / "staging_metrics.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary["mean"], indent=2))


if __name__ == "__main__":
    main()
