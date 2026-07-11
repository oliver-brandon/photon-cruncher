from __future__ import annotations

from dataclasses import dataclass

import numpy as np


TRIAL_TYPES = (
    "correct rewarded",
    "correct not rewarded",
    "incorrect rewarded",
    "incorrect not rewarded",
    "unclassified",
)

TRIAL_TYPE_TITLES = {
    "correct rewarded": "Correct rewarded",
    "correct not rewarded": "Correct · no reward",
    "incorrect rewarded": "Incorrect rewarded",
    "incorrect not rewarded": "Incorrect · no reward",
    "unclassified": "Unclassified",
}


@dataclass(frozen=True)
class TrialDemo:
    number: int
    outcome: str
    artifact: bool = False


@dataclass(frozen=True)
class ChannelDemo:
    key: str
    title: str
    store: str
    color: str
    trials: np.ndarray
    mean: np.ndarray
    sem: np.ndarray


@dataclass(frozen=True)
class BatchSourceDemo:
    name: str
    source_type: str
    duration: str
    status: str


@dataclass(frozen=True)
class DemoSession:
    name: str
    subtitle: str
    source_type: str
    duration: str
    sample_rate: float
    event_count: int
    valid_trials: int
    dropped_trials: tuple[int, ...]
    epocs: tuple[str, ...]
    times: np.ndarray
    trials: tuple[TrialDemo, ...]
    channels: tuple[ChannelDemo, ...]
    batch_sources: tuple[BatchSourceDemo, ...]


def _smooth_rows(values: np.ndarray, width: int = 9) -> np.ndarray:
    kernel = np.ones(width, dtype=float) / width
    return np.stack([np.convolve(row, kernel, mode="same") for row in values])


def _trial_outcomes(rng: np.random.Generator) -> list[str]:
    outcomes = (
        ["correct rewarded"] * 19
        + ["correct not rewarded"] * 9
        + ["incorrect rewarded"] * 8
        + ["incorrect not rewarded"] * 8
        + ["unclassified"] * 4
    )
    rng.shuffle(outcomes)
    return outcomes


def _make_channel(
    rng: np.random.Generator,
    times: np.ndarray,
    trial_records: list[TrialDemo],
    key: str,
    title: str,
    store: str,
    color: str,
    response_scale: float,
    delayed_scale: float,
) -> ChannelDemo:
    count = len(trial_records)
    raw_noise = rng.normal(0.0, 0.34, size=(count, times.size))
    noise = _smooth_rows(raw_noise, width=11)
    slow_drift = rng.normal(0.0, 0.035, size=(count, 1)) * times[None, :]

    fast_response = np.exp(-0.5 * ((times - 0.72) / 0.42) ** 2)
    delayed_response = np.exp(-0.5 * ((times - 2.25) / 0.88) ** 2)
    anticipation = -0.22 * np.exp(-0.5 * ((times + 0.45) / 0.34) ** 2)

    rows: list[np.ndarray] = []
    for index, trial in enumerate(trial_records):
        outcome_gain = {
            "correct rewarded": 1.0,
            "correct not rewarded": 0.35,
            "incorrect rewarded": 0.72,
            "incorrect not rewarded": -0.18,
            "unclassified": 0.12,
        }[trial.outcome]
        amplitude = response_scale * outcome_gain * rng.normal(1.0, 0.13)
        delayed = delayed_scale * outcome_gain * rng.normal(1.0, 0.16)
        row = (
            noise[index]
            + slow_drift[index]
            + amplitude * fast_response
            + delayed * delayed_response
            + response_scale * anticipation
        )
        if trial.artifact:
            artifact_center = 3.4 + 0.35 * ((trial.number % 3) - 1)
            row = row + 2.8 * np.exp(-0.5 * ((times - artifact_center) / 0.08) ** 2)
        rows.append(row)

    trial_matrix = np.asarray(rows, dtype=np.float32)
    mean = trial_matrix.mean(axis=0)
    sem = trial_matrix.std(axis=0, ddof=1) / np.sqrt(count)
    return ChannelDemo(
        key=key,
        title=title,
        store=store,
        color=color,
        trials=trial_matrix,
        mean=mean,
        sem=sem,
    )


def create_demo_session(seed: int = 2402) -> DemoSession:
    """Create deterministic, realistic-looking data without reading lab files."""

    rng = np.random.default_rng(seed)
    times = np.linspace(-4.0, 8.0, 721, dtype=np.float32)
    outcomes = _trial_outcomes(rng)
    artifact_trials = {9, 27, 43}
    trial_records = [
        TrialDemo(number=index + 2, outcome=outcome, artifact=index + 2 in artifact_trials)
        for index, outcome in enumerate(outcomes)
    ]

    channels = (
        _make_channel(
            rng,
            times,
            trial_records,
            key="x465A",
            title="Dopamine · 465 nm",
            store="x465A / x405A",
            color="#2563EB",
            response_scale=1.65,
            delayed_scale=0.58,
        ),
        _make_channel(
            rng,
            times,
            trial_records,
            key="x560B",
            title="Calcium · 560 nm",
            store="x560B / x405B",
            color="#137C8B",
            response_scale=1.16,
            delayed_scale=0.82,
        ),
        _make_channel(
            rng,
            times,
            trial_records,
            key="control",
            title="Control · 405 nm",
            store="x405A",
            color="#7C6DB0",
            response_scale=0.18,
            delayed_scale=0.08,
        ),
    )

    batch_sources = tuple(
        BatchSourceDemo(*row)
        for row in (
            ("Demo_Mouse_042_Acq", "TDT block", "42m 18s", "Ready"),
            ("Demo_Mouse_043_Acq", "MAT export", "39m 54s", "Ready"),
            ("Demo_Mouse_044_Acq", "TDT block", "44m 06s", "Ready"),
            ("Demo_Mouse_042_Rev", "TDT block", "47m 21s", "Ready"),
            ("Demo_Mouse_043_Rev", "MAT export", "45m 12s", "Ready"),
            ("Demo_Mouse_044_Rev", "TDT block", "46m 03s", "Ready"),
        )
    )

    return DemoSession(
        name="Demo_Mouse_042_Acq",
        subtitle="Synthetic acquisition session · no lab data loaded",
        source_type="TDT block",
        duration="42m 18s",
        sample_rate=1017.25,
        event_count=50,
        valid_trials=48,
        dropped_trials=(1, 50),
        epocs=("LeverA", "LeverC", "Reward", "Timeout"),
        times=times,
        trials=tuple(trial_records),
        channels=channels,
        batch_sources=batch_sources,
    )
