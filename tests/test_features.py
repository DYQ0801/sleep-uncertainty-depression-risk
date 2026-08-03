import numpy as np
import pytest

from sleepdep.features import (
    architecture_features,
    cycle_uncertainty_features,
    dynamics_features,
    uncertainty_features,
)


def test_architecture_uses_sleep_onset_and_offset():
    stages = [0, 0, 1, 2, 0, 4, 4, 0]
    result = architecture_features(stages)
    assert result["sol_minutes"] == 1.0
    assert result["tst_minutes"] == 2.0
    assert result["waso_minutes"] == 0.5
    assert result["rem_latency_minutes"] == 1.5
    assert result["sleep_efficiency"] == pytest.approx(4 / 8)


def test_dynamics_transition_rows_are_probabilities():
    stages = [0, 1, 2, 1, 2, 4, 0]
    result = dynamics_features(stages)
    assert result["p_n1_to_n2"] == 1.0
    assert result["p_n2_to_n1"] == 0.5
    assert result["p_n2_to_rem"] == 0.5
    assert result["stage_switches_per_hour"] == pytest.approx(6 / (7 / 120))


def test_uncertainty_separates_boundary_epochs():
    stages = np.array([0, 0, 1, 1])
    probabilities = np.array(
        [
            [0.99, 0.0025, 0.0025, 0.0025, 0.0025],
            [0.99, 0.0025, 0.0025, 0.0025, 0.0025],
            [0.30, 0.40, 0.10, 0.10, 0.10],
            [0.01, 0.96, 0.01, 0.01, 0.01],
        ]
    )
    result = uncertainty_features(probabilities, stages)
    assert result["entropy_boundary_mean"] > result["entropy_stable_mean"]
    assert 0 <= result["entropy_mean"] <= 1


def test_uncertainty_rejects_uncalibrated_shape_or_rows():
    with pytest.raises(ValueError):
        uncertainty_features(np.ones((3, 4)) / 4)
    with pytest.raises(ValueError):
        uncertainty_features(np.ones((3, 5)))


def test_cycle_uncertainty_aligns_rem_terminated_cycles():
    stages = np.array(
        [1] * 8 + [2] * 8 + [4] * 10 + [2] * 8 + [3] * 8 + [4] * 10
    )
    probabilities = np.full((len(stages), 5), 0.025)
    probabilities[np.arange(len(stages)), stages] = 0.9
    probabilities[20:26] = 0.2
    result = cycle_uncertainty_features(probabilities, stages)
    assert result["cycle_count"] == 2
    assert np.isfinite(result["cycle_entropy_drift"])
    assert np.isfinite(result["pre_rem_entropy_mean"])
