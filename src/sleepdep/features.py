"""Feature extraction for whole-night sleep-stage sequences."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional

import numpy as np


STAGES = ("W", "N1", "N2", "N3", "REM")


@dataclass(frozen=True)
class FeatureConfig:
    epoch_seconds: float = 30.0
    eps: float = 1e-12


def _as_stages(stages: Iterable[int]) -> np.ndarray:
    values = np.asarray(stages, dtype=int).reshape(-1)
    if values.size == 0:
        raise ValueError("stages must not be empty")
    if np.any((values < 0) | (values >= len(STAGES))):
        raise ValueError("stages must contain only integers 0..4")
    return values


def _bouts(stages: np.ndarray):
    starts = np.r_[0, np.flatnonzero(stages[1:] != stages[:-1]) + 1]
    ends = np.r_[starts[1:], stages.size]
    return stages[starts], ends - starts, starts, ends


def architecture_features(
    stages: Iterable[int], config: FeatureConfig = FeatureConfig()
) -> Dict[str, float]:
    stages = _as_stages(stages)
    epoch_minutes = config.epoch_seconds / 60.0
    sleep_idx = np.flatnonzero(stages != 0)
    result: Dict[str, float] = {
        "recording_minutes": stages.size * epoch_minutes,
        "tst_minutes": sleep_idx.size * epoch_minutes,
        "sleep_efficiency": float(sleep_idx.size / stages.size),
    }
    for index, name in enumerate(STAGES):
        count = int(np.sum(stages == index))
        result[f"{name.lower()}_minutes"] = count * epoch_minutes
        result[f"{name.lower()}_fraction_recording"] = count / stages.size

    if sleep_idx.size == 0:
        result.update(
            sol_minutes=np.nan,
            waso_minutes=np.nan,
            rem_latency_minutes=np.nan,
            sleep_period_minutes=np.nan,
        )
        return result

    onset, offset = int(sleep_idx[0]), int(sleep_idx[-1])
    rem_idx = np.flatnonzero((stages == 4) & (np.arange(stages.size) >= onset))
    result["sol_minutes"] = onset * epoch_minutes
    result["sleep_period_minutes"] = (offset - onset + 1) * epoch_minutes
    result["waso_minutes"] = np.sum(stages[onset : offset + 1] == 0) * epoch_minutes
    result["rem_latency_minutes"] = (
        (int(rem_idx[0]) - onset) * epoch_minutes if rem_idx.size else np.nan
    )
    for index, name in enumerate(STAGES[1:], start=1):
        count = int(np.sum(stages == index))
        result[f"{name.lower()}_fraction_tst"] = count / sleep_idx.size
    return result


def dynamics_features(
    stages: Iterable[int], config: FeatureConfig = FeatureConfig()
) -> Dict[str, float]:
    stages = _as_stages(stages)
    labels, lengths, _, _ = _bouts(stages)
    epoch_minutes = config.epoch_seconds / 60.0
    transitions = np.zeros((len(STAGES), len(STAGES)), dtype=float)
    for source, target in zip(stages[:-1], stages[1:]):
        transitions[source, target] += 1
    row_sums = transitions.sum(axis=1, keepdims=True)
    probabilities = np.divide(
        transitions, row_sums, out=np.zeros_like(transitions), where=row_sums > 0
    )

    hours = max(stages.size * config.epoch_seconds / 3600.0, config.eps)
    result: Dict[str, float] = {
        "stage_switches_per_hour": float(np.sum(stages[1:] != stages[:-1]) / hours),
        "wake_bouts": float(np.sum(labels == 0)),
        "short_sleep_bout_fraction": float(
            np.mean(lengths[labels != 0] <= 2) if np.any(labels != 0) else np.nan
        ),
    }
    for source, source_name in enumerate(STAGES):
        for target, target_name in enumerate(STAGES):
            result[f"p_{source_name.lower()}_to_{target_name.lower()}"] = probabilities[
                source, target
            ]
        stage_lengths = lengths[labels == source] * epoch_minutes
        result[f"{source_name.lower()}_bout_count"] = float(stage_lengths.size)
        result[f"{source_name.lower()}_bout_mean_minutes"] = (
            float(np.mean(stage_lengths)) if stage_lengths.size else np.nan
        )
        result[f"{source_name.lower()}_bout_median_minutes"] = (
            float(np.median(stage_lengths)) if stage_lengths.size else np.nan
        )
    return result


def masked_rk_dynamics_features(
    stages: Iterable[int], config: FeatureConfig = FeatureConfig()
) -> Dict[str, float]:
    """Extract dynamics from R&K stages while preserving unscored gaps.

    Expected codes are -1 (unscored), 0 (W), 1-4 (N1-N4), 5 (REM), and
    8 (movement). N3/N4 are merged; unscored and movement epochs break bouts
    and are excluded from transition denominators.
    """

    raw = np.asarray(stages, dtype=int).reshape(-1)
    if raw.size == 0 or np.any(~np.isin(raw, [-1, 0, 1, 2, 3, 4, 5, 8])):
        raise ValueError("R&K stages must use only -1, 0..5, and 8")
    valid = np.isin(raw, [0, 1, 2, 3, 4, 5])
    if not np.any(valid):
        raise ValueError("R&K stages must contain at least one scored epoch")
    mapped = raw.copy()
    mapped[raw == 4] = 3
    mapped[raw == 5] = 4
    adjacent = valid[:-1] & valid[1:]
    source = mapped[:-1][adjacent]
    target = mapped[1:][adjacent]
    transitions = np.zeros((len(STAGES), len(STAGES)), dtype=float)
    np.add.at(transitions, (source, target), 1)
    row_sums = transitions.sum(axis=1, keepdims=True)
    probabilities = np.divide(
        transitions, row_sums, out=np.zeros_like(transitions), where=row_sums > 0
    )

    break_before = np.r_[True, (~adjacent) | (mapped[:-1] != mapped[1:])]
    bout_starts = np.flatnonzero(valid & break_before)
    bout_labels = []
    bout_lengths = []
    for start in bout_starts:
        end = start + 1
        while end < raw.size and valid[end] and mapped[end] == mapped[start]:
            end += 1
        bout_labels.append(mapped[start])
        bout_lengths.append(end - start)
    bout_labels = np.asarray(bout_labels)
    bout_lengths = np.asarray(bout_lengths)
    sleep_bouts = bout_lengths[bout_labels != 0]
    valid_hours = valid.sum() * config.epoch_seconds / 3600
    result: Dict[str, float] = {
        "stage_switches_per_hour": float(
            np.sum(source != target) / max(valid_hours, config.eps)
        ),
        "short_sleep_bout_fraction": float(
            np.mean(sleep_bouts <= 2) if sleep_bouts.size else np.nan
        ),
    }
    epoch_minutes = config.epoch_seconds / 60
    for index, name in enumerate(STAGES):
        lengths = bout_lengths[bout_labels == index] * epoch_minutes
        result[f"{name.lower()}_bout_mean_minutes"] = (
            float(np.mean(lengths)) if lengths.size else np.nan
        )
        for target_index, target_name in enumerate(STAGES):
            result[f"p_{name.lower()}_to_{target_name.lower()}"] = probabilities[
                index, target_index
            ]
    return result


def uncertainty_features(
    probabilities: np.ndarray,
    stages: Optional[Iterable[int]] = None,
    config: FeatureConfig = FeatureConfig(),
) -> Dict[str, float]:
    """Summarize calibrated stage-posterior uncertainty.

    These are model epistemic/decision features, not EEG signal entropy.
    Calibration must be fitted without using the evaluated subject.
    """

    probabilities = np.asarray(probabilities, dtype=float)
    if probabilities.ndim != 2 or probabilities.shape[1] != len(STAGES):
        raise ValueError("probabilities must have shape (epochs, 5)")
    if not np.all(np.isfinite(probabilities)) or np.any(probabilities < 0):
        raise ValueError("probabilities must be finite and non-negative")
    row_sums = probabilities.sum(axis=1)
    if not np.allclose(row_sums, 1.0, atol=1e-5):
        raise ValueError("each probability row must sum to one")

    clipped = np.clip(probabilities, config.eps, 1.0)
    entropy = -np.sum(clipped * np.log(clipped), axis=1) / np.log(len(STAGES))
    ordered = np.sort(probabilities, axis=1)
    margin = ordered[:, -1] - ordered[:, -2]
    result = {
        "entropy_mean": float(np.mean(entropy)),
        "entropy_std": float(np.std(entropy)),
        "entropy_cv": float(np.std(entropy) / max(np.mean(entropy), config.eps)),
        "entropy_p90": float(np.quantile(entropy, 0.9)),
        "posterior_margin_mean": float(np.mean(margin)),
    }
    if stages is None:
        return result

    stages = _as_stages(stages)
    if stages.size != probabilities.shape[0]:
        raise ValueError("stages and probabilities must have equal epoch counts")
    boundary = np.r_[False, stages[1:] != stages[:-1]]
    result["entropy_boundary_mean"] = (
        float(np.mean(entropy[boundary])) if np.any(boundary) else np.nan
    )
    result["entropy_stable_mean"] = (
        float(np.mean(entropy[~boundary])) if np.any(~boundary) else np.nan
    )
    result["entropy_boundary_excess"] = (
        result["entropy_boundary_mean"] - result["entropy_stable_mean"]
    )
    for index, name in enumerate(STAGES):
        mask = stages == index
        result[f"entropy_{name.lower()}_mean"] = (
            float(np.mean(entropy[mask])) if np.any(mask) else np.nan
        )
    return result


def cycle_uncertainty_features(
    probabilities: np.ndarray,
    stages: Iterable[int],
    min_rem_epochs: int = 10,
    pre_rem_epochs: int = 20,
    config: FeatureConfig = FeatureConfig(),
) -> Dict[str, float]:
    """Aggregate posterior entropy after aligning nights by NREM-REM cycles."""

    stages = _as_stages(stages)
    probabilities = np.asarray(probabilities, dtype=float)
    # Reuse all probability validation and entropy normalization rules.
    uncertainty_features(probabilities, stages, config)
    clipped = np.clip(probabilities, config.eps, 1.0)
    entropy = -np.sum(clipped * np.log(clipped), axis=1) / np.log(len(STAGES))

    labels, lengths, starts, ends = _bouts(stages)
    rem_bouts = [
        (int(start), int(end))
        for label, length, start, end in zip(labels, lengths, starts, ends)
        if label == 4 and length >= min_rem_epochs
    ]
    sleep_idx = np.flatnonzero(stages != 0)
    if not rem_bouts or not sleep_idx.size:
        return {
            "cycle_count": 0.0,
            **{f"cycle_entropy_phase_{phase}": np.nan for phase in range(1, 5)},
            "pre_rem_entropy_mean": np.nan,
            "cycle_entropy_drift": np.nan,
        }

    cycle_start = int(sleep_idx[0])
    phase_values = [[] for _ in range(4)]
    cycle_means = []
    pre_rem_values = []
    valid_cycles = 0
    for rem_start, rem_end in rem_bouts:
        if rem_end <= cycle_start:
            continue
        indices = np.arange(cycle_start, rem_end)
        bins = np.minimum((np.arange(indices.size) * 4) // indices.size, 3)
        for phase in range(4):
            phase_values[phase].extend(entropy[indices[bins == phase]].tolist())
        cycle_means.append(float(np.mean(entropy[indices])))
        pre_start = max(cycle_start, rem_start - pre_rem_epochs)
        if rem_start > pre_start:
            pre_rem_values.extend(entropy[pre_start:rem_start].tolist())
        cycle_start = rem_end
        valid_cycles += 1

    drift = (
        float(np.polyfit(np.arange(valid_cycles), cycle_means, 1)[0])
        if valid_cycles >= 2
        else np.nan
    )
    result = {
        "cycle_count": float(valid_cycles),
        "pre_rem_entropy_mean": (
            float(np.mean(pre_rem_values)) if pre_rem_values else np.nan
        ),
        "cycle_entropy_drift": drift,
    }
    for phase, values in enumerate(phase_values, start=1):
        result[f"cycle_entropy_phase_{phase}"] = (
            float(np.mean(values)) if values else np.nan
        )
    return result


def extract_night_features(
    stages: Iterable[int],
    probabilities: Optional[np.ndarray] = None,
    config: FeatureConfig = FeatureConfig(),
) -> Dict[str, float]:
    stages = _as_stages(stages)
    result = architecture_features(stages, config)
    result.update(dynamics_features(stages, config))
    if probabilities is not None:
        result.update(uncertainty_features(probabilities, stages, config))
        result.update(cycle_uncertainty_features(probabilities, stages, config=config))
    return result
