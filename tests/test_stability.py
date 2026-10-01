import numpy as np
import pytest

from sleepdep import (
    bootstrap_group_error_difference,
    risk_coverage_summary,
    risk_interval_summary,
    temperature_rescale,
)


def test_temperature_rescale_preserves_rows_and_argmax():
    probabilities = np.array(
        [
            [0.70, 0.10, 0.08, 0.07, 0.05],
            [0.05, 0.10, 0.15, 0.20, 0.50],
        ]
    )

    colder = temperature_rescale(probabilities, 0.8)
    warmer = temperature_rescale(probabilities, 1.2)

    assert np.allclose(colder.sum(axis=1), 1.0)
    assert np.allclose(warmer.sum(axis=1), 1.0)
    assert np.array_equal(colder.argmax(axis=1), probabilities.argmax(axis=1))
    assert np.array_equal(warmer.argmax(axis=1), probabilities.argmax(axis=1))
    assert np.all(colder.max(axis=1) > probabilities.max(axis=1))
    assert np.all(warmer.max(axis=1) < probabilities.max(axis=1))


def test_risk_interval_detects_threshold_crossing():
    views = np.array(
        [
            [0.42, 0.45, 0.48],
            [0.47, 0.51, 0.54],
            [0.60, 0.55, 0.52],
        ]
    )

    result = risk_interval_summary(views, nominal_index=1)

    assert result["lower"] == pytest.approx([0.42, 0.47, 0.52])
    assert result["upper"] == pytest.approx([0.48, 0.54, 0.60])
    assert result["crosses_threshold"].tolist() == [False, True, False]
    assert result["decision_code"].tolist() == [0, -1, 1]
    assert result["stability_index"][1] > result["stability_index"][0]


def test_risk_coverage_accepts_least_uncertain_first():
    y_true = np.array([0, 0, 1, 1])
    risk_score = np.array([0.1, 0.8, 0.9, 0.2])
    uncertainty = np.array([0.1, 0.4, 0.2, 0.3])

    result = risk_coverage_summary(
        y_true,
        risk_score,
        uncertainty,
        coverages=(0.5, 1.0),
    )

    assert result["selected"]["0.50"]["error_rate"] == 0.0
    assert result["selected"]["1.00"]["error_rate"] == 0.5


def test_bootstrap_group_error_difference_uses_both_groups():
    y_true = np.array([0, 0, 1, 1, 0, 1])
    risk_score = np.array([0.1, 0.9, 0.8, 0.2, 0.2, 0.7])
    group = np.array([False, True, False, True, False, False])

    result = bootstrap_group_error_difference(
        y_true,
        risk_score,
        group,
        iterations=200,
        seed=7,
    )

    assert result["estimate"] == pytest.approx(1.0)
    assert result["iterations"] > 0
