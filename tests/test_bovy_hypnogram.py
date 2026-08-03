import pytest

from sleepdep import masked_rk_dynamics_features


def test_invalid_epochs_break_bouts_and_transitions():
    result = masked_rk_dynamics_features([2, 2, -1, 2, 2, 5, 5, 8, 0, 0])

    assert result["n2_bout_mean_minutes"] == 1.0
    assert result["rem_bout_mean_minutes"] == 1.0
    assert result["p_n2_to_rem"] == pytest.approx(1 / 3)
    assert result["p_rem_to_w"] == 0.0
    assert result["stage_switches_per_hour"] == pytest.approx(15.0)
