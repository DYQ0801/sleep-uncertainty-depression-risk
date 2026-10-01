#!/usr/bin/env python3
"""Propagate sleep-stage calibration sensitivity to subject risk intervals."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import fisher_exact
from sklearn.model_selection import StratifiedKFold


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sleepdep import (  # noqa: E402
    bootstrap_group_error_difference,
    classification_metrics,
    risk_coverage_summary,
    risk_interval_summary,
    temperature_rescale,
    uncertainty_features,
)
from run_apples_clinical_experiments import (  # noqa: E402
    CONFOUNDERS,
    DYNAMICS,
    MACRO,
    OSA,
    tune_model,
)


CALIBRATED_UNCERTAINTY = [
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
FEATURES = CONFOUNDERS + OSA + MACRO + DYNAMICS + CALIBRATED_UNCERTAINTY


def temperature_grid(spans, step):
    """Build one symmetric multiplier grid covering every requested span."""

    spans = np.asarray(spans, dtype=float)
    if spans.ndim != 1 or spans.size == 0:
        raise ValueError("at least one temperature span is required")
    if np.any(~np.isfinite(spans)) or np.any((spans <= 0) | (spans >= 1)):
        raise ValueError("temperature spans must lie in (0, 1)")
    if not np.isfinite(step) or step <= 0:
        raise ValueError("temperature step must be positive")

    maximum = float(np.max(spans))
    count = int(np.ceil(maximum / step))
    positive = np.linspace(0.0, maximum, count + 1)
    values = np.unique(
        np.concatenate(
            [
                1.0 - positive,
                np.array([1.0]),
                1.0 + positive,
                1.0 - spans,
                1.0 + spans,
            ]
        )
    )
    return np.round(values, 10)


def load_feature_views(
    cohort_path,
    sequence_path,
    posterior_dir,
    multipliers,
):
    """Recompute E4 uncertainty features for each temperature multiplier."""

    rows = {float(multiplier): [] for multiplier in multipliers}
    fold_temperatures = {}
    paths = sorted(posterior_dir.glob("*.npz"))
    if not paths:
        raise FileNotFoundError(f"No subject posterior files in {posterior_dir}")

    for path in paths:
        with np.load(path, allow_pickle=False) as archive:
            probabilities = archive["probabilities"].astype(float)
            predicted = archive["predicted_stages"].astype(int)
            fold = int(archive["fold"])
            temperature = float(archive["temperature"])
        previous = fold_temperatures.setdefault(fold, temperature)
        if not np.isclose(previous, temperature):
            raise ValueError(f"Inconsistent temperature in fold {fold}")
        for multiplier in multipliers:
            view = temperature_rescale(probabilities, float(multiplier))
            row = {"fileid": path.stem}
            row.update(uncertainty_features(view, predicted))
            rows[float(multiplier)].append(row)

    cohort = pd.read_csv(cohort_path, low_memory=False)
    sequence = pd.read_csv(sequence_path)
    base = cohort.merge(
        sequence,
        on="fileid",
        how="inner",
        validate="one_to_one",
    )
    base = base[base["over_4h"]].reset_index(drop=True)
    views = {}
    for multiplier, feature_rows in rows.items():
        feature_frame = pd.DataFrame(feature_rows)
        frame = base.merge(
            feature_frame,
            on="fileid",
            how="inner",
            validate="one_to_one",
        )
        if len(frame) != len(base):
            raise ValueError(
                f"Incomplete posterior view at multiplier {multiplier}"
            )
        views[multiplier] = frame
    return views, {
        str(fold): temperature
        for fold, temperature in sorted(fold_temperatures.items())
    }


def protocol_splits(frame, protocol, seed):
    y = frame["diagnosis_hamd"].to_numpy(dtype=int)
    if protocol == "nested_cv":
        splitter = StratifiedKFold(
            n_splits=5,
            shuffle=True,
            random_state=seed,
        )
        for fold, (train, test) in enumerate(
            splitter.split(frame[FEATURES], y),
            start=1,
        ):
            yield str(fold), train, test, seed + fold
        return

    sites = frame["site"].astype(str).to_numpy()
    for index, site in enumerate(sorted(np.unique(sites))):
        train = np.flatnonzero(sites != site)
        test = np.flatnonzero(sites == site)
        yield site, train, test, seed + index + 100


def predict_protocol(views, multipliers, protocol, seed):
    nominal = views[1.0]
    y = nominal["diagnosis_hamd"].to_numpy(dtype=int)
    predictions = np.full((len(nominal), len(multipliers)), np.nan)
    split_labels = np.full(len(nominal), "", dtype=object)
    for label, train, test, fold_seed in protocol_splits(
        nominal,
        protocol,
        seed,
    ):
        model = tune_model(
            nominal,
            train,
            FEATURES,
            y,
            y,
            "classification",
            fold_seed,
        )
        for column, multiplier in enumerate(multipliers):
            predictions[test, column] = model.predict_proba(
                views[float(multiplier)].iloc[test][FEATURES]
            )[:, 1]
        split_labels[test] = label

    if not np.isfinite(predictions).all() or np.any(split_labels == ""):
        raise FloatingPointError(f"Incomplete {protocol} predictions")
    return y, predictions, split_labels


def group_metrics(y, risk_score, group):
    if not np.any(group):
        return {
            "n": 0,
            "positive": 0,
            "coverage": 0.0,
            "error_rate": np.nan,
            "balanced_accuracy": np.nan,
            "brier": np.nan,
            "auroc": np.nan,
            "auprc": np.nan,
        }
    result = classification_metrics(y[group], risk_score[group])
    result["coverage"] = float(np.mean(group))
    return result


def matched_margin_group(summary):
    """Select the same number of subjects using nominal score margin only."""

    count = int(np.sum(~summary["crosses_threshold"]))
    order = np.argsort(-summary["margin"], kind="stable")
    selected = np.zeros(summary["margin"].size, dtype=bool)
    selected[order[:count]] = True
    return selected


def summarize_span(
    y,
    predictions,
    multipliers,
    span,
    bootstrap_iterations,
    seed,
):
    selected_columns = np.flatnonzero(
        np.abs(multipliers - 1.0) <= span + 1e-12
    )
    selected_multipliers = multipliers[selected_columns]
    nominal_index = int(np.flatnonzero(selected_multipliers == 1.0)[0])
    interval = risk_interval_summary(
        predictions[:, selected_columns],
        nominal_index,
    )
    stable = ~interval["crosses_threshold"]
    crossing = interval["crosses_threshold"]
    margin_selected = matched_margin_group(interval)

    errors = ((interval["nominal"] >= 0.5).astype(int) != y).astype(int)
    table = [
        [int(errors[crossing].sum()), int((1 - errors[crossing]).sum())],
        [int(errors[stable].sum()), int((1 - errors[stable]).sum())],
    ]
    if crossing.any() and stable.any():
        odds_ratio, fisher_p = fisher_exact(table)
        error_comparison = {
            **bootstrap_group_error_difference(
                y,
                interval["nominal"],
                crossing,
                iterations=bootstrap_iterations,
                seed=seed,
            ),
            "odds_ratio": float(odds_ratio),
            "fisher_exact_p": float(fisher_p),
        }
    else:
        error_comparison = {
            "estimate": np.nan,
            "ci": [np.nan, np.nan],
            "iterations": 0,
            "odds_ratio": np.nan,
            "fisher_exact_p": np.nan,
        }
    return {
        "temperature_multipliers": selected_multipliers.tolist(),
        "threshold_crossing_rate": float(np.mean(crossing)),
        "threshold_crossing_count": int(np.sum(crossing)),
        "crossing_group": group_metrics(y, interval["nominal"], crossing),
        "stable_group": group_metrics(y, interval["nominal"], stable),
        "matched_margin_group": group_metrics(
            y,
            interval["nominal"],
            margin_selected,
        ),
        "crossing_vs_stable_error": error_comparison,
        "risk_coverage": {
            "nominal_margin": risk_coverage_summary(
                y,
                interval["nominal"],
                -interval["margin"],
            ),
            "calibration_stability_index": risk_coverage_summary(
                y,
                interval["nominal"],
                interval["stability_index"],
            ),
        },
        "interval_width": {
            "mean": float(np.mean(interval["width"])),
            "median": float(np.median(interval["width"])),
            "p90": float(np.quantile(interval["width"], 0.9)),
            "maximum": float(np.max(interval["width"])),
        },
        "_interval": interval,
    }


def span_key(span):
    return f"span_{span:.3f}".replace(".", "_")


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
        "--posterior-dir",
        type=Path,
        default=Path("results/apples/posterior_extratrees/subjects"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/apples/risk_stability"),
    )
    parser.add_argument(
        "--temperature-spans",
        type=float,
        nargs="+",
        default=[0.05, 0.10, 0.15],
    )
    parser.add_argument("--temperature-step", type=float, default=0.025)
    parser.add_argument("--bootstrap-iterations", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20260802)
    args = parser.parse_args()

    multipliers = temperature_grid(
        args.temperature_spans,
        args.temperature_step,
    )
    views, fold_temperatures = load_feature_views(
        args.cohort,
        args.sequence_features,
        args.posterior_dir,
        multipliers,
    )
    nominal = views[1.0]
    report = {
        "subjects": len(nominal),
        "outcome": "HAMD total score >= 8",
        "decision_threshold": 0.5,
        "temperature_spans": args.temperature_spans,
        "temperature_step": args.temperature_step,
        "source_temperature_by_staging_fold": fold_temperatures,
        "interpretation": (
            "Temperature spans are engineering sensitivity tolerances, "
            "not statistical confidence intervals."
        ),
        "protocols": {},
    }
    prediction_table = nominal[
        ["fileid", "nsrrid", "site", "hamd", "diagnosis_hamd"]
    ].copy()

    for protocol in ("nested_cv", "leave_one_site_out"):
        y, predictions, split_labels = predict_protocol(
            views,
            multipliers,
            protocol,
            args.seed,
        )
        nominal_column = int(np.flatnonzero(multipliers == 1.0)[0])
        protocol_report = {
            "nominal": classification_metrics(
                y,
                predictions[:, nominal_column],
            ),
            "spans": {},
        }
        prediction_table[f"{protocol}_split"] = split_labels
        prediction_table[f"{protocol}_risk_nominal"] = predictions[
            :, nominal_column
        ]
        for span in args.temperature_spans:
            key = span_key(span)
            summary = summarize_span(
                y,
                predictions,
                multipliers,
                span,
                args.bootstrap_iterations,
                args.seed + int(round(span * 1000)),
            )
            interval = summary.pop("_interval")
            protocol_report["spans"][key] = summary
            for name in (
                "lower",
                "upper",
                "width",
                "stability_index",
                "crosses_threshold",
                "decision_code",
            ):
                prediction_table[
                    f"{protocol}_{key}_{name}"
                ] = interval[name]
        report["protocols"][protocol] = protocol_report

    args.output.mkdir(parents=True, exist_ok=True)
    prediction_table.to_csv(args.output / "predictions.csv", index=False)
    (args.output / "metrics.json").write_text(
        json.dumps(report, indent=2, allow_nan=True),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, allow_nan=True))


if __name__ == "__main__":
    main()
