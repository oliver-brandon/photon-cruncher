from __future__ import annotations

from dataclasses import dataclass, field
import re

import numpy as np

from photon_cruncher.model import Epoc, PhotometrySession


TIMESTAMP_TOLERANCE_SECONDS = 0.02
STARTUP_EPSILON_SECONDS = 1e-9

CORRECT_REWARDED = "correct rewarded"
CORRECT_NOT_REWARDED = "correct not rewarded"
INCORRECT_REWARDED = "incorrect rewarded"
INCORRECT_NOT_REWARDED = "incorrect not rewarded"
UNCLASSIFIED = "unclassified"

EXPLICIT_OUTCOME_PREFIXES = {
    "cRew": CORRECT_REWARDED,
    "cNoRew": CORRECT_NOT_REWARDED,
    "iRew": INCORRECT_REWARDED,
    "iNoRew": INCORRECT_NOT_REWARDED,
}


@dataclass
class ClassifiedTrial:
    trial_number: int
    onset: float
    trial_type: str


@dataclass
class ClassifiedTrialSource:
    key: str
    label: str
    epoc: Epoc
    trials: list[ClassifiedTrial]
    warnings: list[str] = field(default_factory=list)


def classified_trial_sources(
    session: PhotometrySession,
    tolerance: float = TIMESTAMP_TOLERANCE_SECONDS,
) -> list[ClassifiedTrialSource]:
    explicit = _explicit_outcome_source(session, tolerance)
    if explicit is not None:
        return [explicit]
    return _cl_il_pe_sources(session, tolerance)


def _explicit_outcome_source(
    session: PhotometrySession,
    tolerance: float,
) -> ClassifiedTrialSource | None:
    events: list[tuple[float, str]] = []
    for name, epoc in session.epocs.items():
        trial_type = _explicit_trial_type(name)
        if trial_type is None:
            continue
        events.extend(
            (float(onset), trial_type)
            for onset in epoc.onset
            if not _is_startup_timestamp(float(onset))
        )
    if not events:
        return None

    trials = _cluster_labeled_events(events, tolerance)
    warnings = _explicit_source_warnings(session, trials, tolerance)
    label = "Classified trials levers" if "levers" in session.epocs else "Classified trials"
    return _source_from_trials(
        key="classified:explicit",
        label=label,
        trials=trials,
        warnings=warnings,
    )


def _explicit_trial_type(epoc_name: str) -> str | None:
    for prefix, trial_type in EXPLICIT_OUTCOME_PREFIXES.items():
        if epoc_name.startswith(prefix):
            return trial_type
    return None


def _cluster_labeled_events(
    events: list[tuple[float, str]],
    tolerance: float,
) -> list[ClassifiedTrial]:
    trials: list[ClassifiedTrial] = []
    for event_time, trial_type in sorted(events):
        if trials and abs(trials[-1].onset - event_time) <= tolerance:
            if trials[-1].trial_type != trial_type:
                trials[-1].trial_type = UNCLASSIFIED
            continue
        trials.append(
            ClassifiedTrial(
                trial_number=len(trials) + 1,
                onset=event_time,
                trial_type=trial_type,
            )
        )
    return trials


def _explicit_source_warnings(
    session: PhotometrySession,
    trials: list[ClassifiedTrial],
    tolerance: float,
) -> list[str]:
    warnings: list[str] = []
    trial_times = np.array([trial.onset for trial in trials], dtype=float)
    if "levers" in session.epocs:
        lever_times = _nonstartup_onsets(session.epocs["levers"])
        if not _same_times(trial_times, lever_times, tolerance):
            warnings.append("Classified outcomes do not fully match the levers epoc.")

    validation_groups = [
        (
            "correct outcomes",
            [CORRECT_REWARDED, CORRECT_NOT_REWARDED],
            "CL",
        ),
        (
            "incorrect outcomes",
            [INCORRECT_REWARDED, INCORRECT_NOT_REWARDED],
            "IL",
        ),
        (
            "rewarded outcomes",
            [CORRECT_REWARDED, INCORRECT_REWARDED],
            "Pe",
        ),
    ]
    for label, trial_types, epoc_prefix in validation_groups:
        expected = np.array(
            [
                trial.onset
                for trial in trials
                if trial.trial_type in set(trial_types)
            ],
            dtype=float,
        )
        candidates = [
            _nonstartup_onsets(epoc)
            for name, epoc in session.epocs.items()
            if name.startswith(epoc_prefix)
        ]
        if candidates and not any(
            _same_times(expected, candidate, tolerance) for candidate in candidates
        ):
            warnings.append(f"Classified {label} do not match any {epoc_prefix} epoc.")
    return warnings


def _cl_il_pe_sources(
    session: PhotometrySession,
    tolerance: float,
) -> list[ClassifiedTrialSource]:
    suffixes = sorted(
        {
            match.group("suffix")
            for name in session.epocs
            for match in [re.fullmatch(r"(?:CL|IL|Pe)(?P<suffix>.+)", name)]
            if match is not None
        }
    )
    sources: list[ClassifiedTrialSource] = []
    for suffix in suffixes:
        cl_epoc = session.epocs.get(f"CL{suffix}")
        il_epoc = session.epocs.get(f"IL{suffix}")
        if cl_epoc is None and il_epoc is None:
            continue
        pe_times = (
            _nonstartup_onsets(session.epocs[f"Pe{suffix}"])
            if f"Pe{suffix}" in session.epocs
            else np.array([], dtype=float)
        )
        events: list[tuple[float, str]] = []
        if cl_epoc is not None:
            events.extend(
                (float(onset), "CL")
                for onset in _nonstartup_onsets(cl_epoc)
            )
        if il_epoc is not None:
            events.extend(
                (float(onset), "IL")
                for onset in _nonstartup_onsets(il_epoc)
            )
        trials = _classify_cl_il_events(events, pe_times, tolerance)
        if not trials:
            continue
        warnings = []
        if f"Pe{suffix}" not in session.epocs:
            warnings.append(f"No Pe{suffix} epoc found; all trials marked unrewarded.")
        sources.append(
            _source_from_trials(
                key=f"classified:{suffix}",
                label=f"Classified trials {suffix}",
                trials=trials,
                warnings=warnings,
            )
        )
    return sources


def _classify_cl_il_events(
    events: list[tuple[float, str]],
    pe_times: np.ndarray,
    tolerance: float,
) -> list[ClassifiedTrial]:
    trials: list[ClassifiedTrial] = []
    for event_time, lever_kind in sorted(events):
        if trials and abs(trials[-1].onset - event_time) <= tolerance:
            trials[-1].trial_type = UNCLASSIFIED
            continue
        rewarded = _has_match(event_time, pe_times, tolerance)
        if lever_kind == "CL":
            trial_type = CORRECT_REWARDED if rewarded else CORRECT_NOT_REWARDED
        elif lever_kind == "IL":
            trial_type = INCORRECT_REWARDED if rewarded else INCORRECT_NOT_REWARDED
        else:
            trial_type = UNCLASSIFIED
        trials.append(
            ClassifiedTrial(
                trial_number=len(trials) + 1,
                onset=event_time,
                trial_type=trial_type,
            )
        )
    return trials


def _source_from_trials(
    key: str,
    label: str,
    trials: list[ClassifiedTrial],
    warnings: list[str],
) -> ClassifiedTrialSource:
    epoc = Epoc(
        name=label,
        onset=np.array([trial.onset for trial in trials], dtype=float),
        values=np.array([trial.trial_number for trial in trials], dtype=float),
    )
    return ClassifiedTrialSource(
        key=key,
        label=label,
        epoc=epoc,
        trials=trials,
        warnings=warnings,
    )


def _nonstartup_onsets(epoc: Epoc) -> np.ndarray:
    return np.array(
        [
            float(onset)
            for onset in epoc.onset
            if not _is_startup_timestamp(float(onset))
        ],
        dtype=float,
    )


def _is_startup_timestamp(value: float) -> bool:
    return abs(value) <= STARTUP_EPSILON_SECONDS


def _same_times(left: np.ndarray, right: np.ndarray, tolerance: float) -> bool:
    if left.size != right.size:
        return False
    if left.size == 0:
        return True
    unmatched = list(float(value) for value in np.sort(right))
    for value in np.sort(left):
        match_idx = _nearest_index(float(value), unmatched, tolerance)
        if match_idx is None:
            return False
        unmatched.pop(match_idx)
    return not unmatched


def _has_match(value: float, candidates: np.ndarray, tolerance: float) -> bool:
    if candidates.size == 0:
        return False
    diffs = np.abs(candidates - value)
    return bool(np.any(diffs <= tolerance))


def _nearest_index(
    value: float,
    candidates: list[float],
    tolerance: float,
) -> int | None:
    if not candidates:
        return None
    diffs = [abs(candidate - value) for candidate in candidates]
    idx = int(np.argmin(diffs))
    if diffs[idx] <= tolerance:
        return idx
    return None
