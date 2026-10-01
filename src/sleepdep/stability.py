"""Calibration-sensitivity propagation for subject-level risk scores."""

from __future__ import annotations

from typing import Dict

import numpy as np
from sklearn.metrics import (
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    roc_auc_score,
)


def temperature_rescale(
    probabilities: np.ndarray,
    multiplier: float,
    eps: float = 1e-12,
) -> np.ndarray:
    """Move calibrated probabilities from temperature T to multiplier * T.

    If ``probabilities = softmax(logits / T)``, this transformation exactly
    recovers ``softmax(logits / (multiplier * T))`` up to clipping error.
    """

    probabilities = np.asarray(probabilities, dtype=float)
    if probabilities.ndim != 2 or probabilities.shape[1] < 2:
        raise ValueError("probabilities must have shape (samples, classes)")
    if not np.isfinite(probabilities).all() or np.any(probabilities < 0):
        raise ValueError("probabilities must be finite and non-negative")
    if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-5):
        raise ValueError("each probability row must sum to one")
    if not np.isfinite(multiplier) or multiplier <= 0:
        raise ValueError("multiplier must be finite and positive")

    log_probabilities = np.log(np.clip(probabilities, eps, 1.0))
    scaled = log_probabilities / multiplier
    scaled -= scaled.max(axis=1, keepdims=True)
    result = np.exp(scaled)
    return result / result.sum(axis=1, keepdims=True)


def risk_interval_summary(
    risk_views: np.ndarray,
    nominal_index: int,
    threshold: float = 0.5,
    eps: float = 1e-12,
) -> Dict[str, np.ndarray]:
    """Summarize risk-score sensitivity across calibration views."""

    risk_views = np.asarray(risk_views, dtype=float)
    if risk_views.ndim != 2 or risk_views.shape[1] < 2:
        raise ValueError("risk_views must have shape (subjects, views)")
    if not np.isfinite(risk_views).all():
        raise ValueError("risk_views must be finite")
    if not 0 <= nominal_index < risk_views.shape[1]:
        raise ValueError("nominal_index is outside risk_views")

    nominal = risk_views[:, nominal_index]
    lower = risk_views.min(axis=1)
    upper = risk_views.max(axis=1)
    width = upper - lower
    margin = np.abs(nominal - threshold)
    crosses_threshold = (lower <= threshold) & (upper >= threshold)
    stability_index = width / np.maximum(margin, eps)
    decision_code = np.full(nominal.size, -1, dtype=np.int8)
    decision_code[upper < threshold] = 0
    decision_code[lower > threshold] = 1
    return {
        "nominal": nominal,
        "lower": lower,
        "upper": upper,
        "width": width,
        "margin": margin,
        "stability_index": stability_index,
        "crosses_threshold": crosses_threshold,
        "decision_code": decision_code,
    }


def classification_metrics(
    y_true: np.ndarray,
    risk_score: np.ndarray,
    threshold: float = 0.5,
) -> Dict[str, float]:
    """Return classification metrics for a non-empty selected subset."""

    y_true = np.asarray(y_true, dtype=int)
    risk_score = np.asarray(risk_score, dtype=float)
    if y_true.ndim != 1 or risk_score.shape != y_true.shape:
        raise ValueError("y_true and risk_score must be equal-length vectors")
    if y_true.size == 0:
        raise ValueError("selected subset must not be empty")
    if not np.isfinite(risk_score).all():
        raise ValueError("risk_score must be finite")

    predicted = (risk_score >= threshold).astype(int)
    result = {
        "n": int(y_true.size),
        "positive": int(y_true.sum()),
        "error_rate": float(np.mean(predicted != y_true)),
        "balanced_accuracy": float(
            balanced_accuracy_score(y_true, predicted)
        ),
        "brier": float(brier_score_loss(y_true, risk_score)),
    }
    if np.unique(y_true).size == 2:
        result["auroc"] = float(roc_auc_score(y_true, risk_score))
        result["auprc"] = float(
            average_precision_score(y_true, risk_score)
        )
    else:
        result["auroc"] = np.nan
        result["auprc"] = np.nan
    return result


def risk_coverage_summary(
    y_true: np.ndarray,
    risk_score: np.ndarray,
    uncertainty: np.ndarray,
    coverages: tuple[float, ...] = (0.5, 0.7, 0.9, 0.95),
    threshold: float = 0.5,
) -> Dict[str, object]:
    """Evaluate prediction error after accepting least-uncertain subjects."""

    y_true = np.asarray(y_true, dtype=int)
    risk_score = np.asarray(risk_score, dtype=float)
    uncertainty = np.asarray(uncertainty, dtype=float)
    if risk_score.shape != y_true.shape or uncertainty.shape != y_true.shape:
        raise ValueError("inputs must be equal-length vectors")
    if y_true.size == 0 or not np.isfinite(uncertainty).all():
        raise ValueError("uncertainty must be finite and non-empty")

    order = np.argsort(uncertainty, kind="stable")
    errors = ((risk_score >= threshold).astype(int) != y_true).astype(float)
    cumulative_risk = np.cumsum(errors[order]) / np.arange(
        1, y_true.size + 1
    )
    selected = {}
    for coverage in coverages:
        if not 0 < coverage <= 1:
            raise ValueError("coverages must lie in (0, 1]")
        count = max(1, int(round(coverage * y_true.size)))
        indices = order[:count]
        selected[f"{coverage:.2f}"] = {
            "coverage": float(count / y_true.size),
            **classification_metrics(
                y_true[indices],
                risk_score[indices],
                threshold,
            ),
        }
    return {
        "aurc": float(np.mean(cumulative_risk)),
        "selected": selected,
    }


def bootstrap_group_error_difference(
    y_true: np.ndarray,
    risk_score: np.ndarray,
    group: np.ndarray,
    iterations: int = 5000,
    seed: int = 20260802,
    threshold: float = 0.5,
) -> Dict[str, object]:
    """Bootstrap error(group=True) minus error(group=False)."""

    y_true = np.asarray(y_true, dtype=int)
    risk_score = np.asarray(risk_score, dtype=float)
    group = np.asarray(group, dtype=bool)
    if y_true.shape != risk_score.shape or group.shape != y_true.shape:
        raise ValueError("inputs must be equal-length vectors")
    if not group.any() or group.all():
        raise ValueError("both groups must contain at least one subject")

    errors = ((risk_score >= threshold).astype(int) != y_true).astype(float)
    estimate = float(errors[group].mean() - errors[~group].mean())
    rng = np.random.default_rng(seed)
    values = []
    for _ in range(iterations):
        indices = rng.integers(0, y_true.size, y_true.size)
        sampled_group = group[indices]
        if not sampled_group.any() or sampled_group.all():
            continue
        sampled_error = errors[indices]
        values.append(
            sampled_error[sampled_group].mean()
            - sampled_error[~sampled_group].mean()
        )
    return {
        "estimate": estimate,
        "ci": [
            float(np.quantile(values, 0.025)),
            float(np.quantile(values, 0.975)),
        ],
        "iterations": len(values),
    }
