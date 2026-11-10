"""Numeric baselines and text-aware Method C without label leakage."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable

from experiments.extractor import DeterministicRuExtractor, ExtractorResult, FactExtractor
from experiments.synthetic import DayRecord, GroundTruthFact


NUMERIC_RULES_VERSION = "numeric-rules-v1"


@dataclass(frozen=True, slots=True)
class Prediction:
    profile_id: str
    day_index: int
    method: str
    attention: bool
    insufficient_data: bool
    ground_truth_event: bool
    scenario_type: str
    change_start_day: int | None
    ground_truth_facts: tuple[GroundTruthFact, ...]


def _values(history: Iterable[DayRecord], attribute: str) -> list[float]:
    return [value for row in history if (value := getattr(row, attribute)) is not None]


def _z_score(history: list[DayRecord], current: DayRecord, attribute: str) -> float | None:
    values = _values(history[-14:], attribute)
    current_value = getattr(current, attribute)
    if len(values) < 7 or current_value is None:
        return None
    center = median(values)
    mad = median(abs(value - center) for value in values)
    scale = 1.4826 * mad
    if scale < 1e-9:
        scale = max(abs(center) * 0.05, 0.1)
    return (current_value - center) / scale


def baseline_a(current: DayRecord) -> tuple[bool, bool]:
    """Fixed experimental thresholds; these are not clinical limits."""

    available = [current.sleep_hours, current.activity_minutes, current.pulse_bpm]
    if not any(value is not None for value in available):
        return False, True
    attention = (
        (current.sleep_hours is not None and current.sleep_hours < 6.0)
        or (current.activity_minutes is not None and current.activity_minutes < 30.0)
        or (current.pulse_bpm is not None and current.pulse_bpm > 100.0)
    )
    return attention, False


def baseline_b(history: list[DayRecord], current: DayRecord) -> tuple[bool, bool]:
    scores = [
        _z_score(history, current, "sleep_hours"),
        _z_score(history, current, "activity_minutes"),
        _z_score(history, current, "pulse_bpm"),
    ]
    available = [score for score in scores if score is not None]
    if not available:
        return False, True
    return any(abs(score) >= 2.5 for score in available), False


def method_c(
    history: list[DayRecord],
    current: DayRecord,
    *,
    extracted: ExtractorResult,
) -> tuple[bool, bool]:
    """Combine numeric history with independently extracted current text facts."""

    numeric_attention, insufficient = baseline_b(history, current)
    if insufficient:
        return False, True
    text_attention = any(
        fact.category == "weakness" and fact.polarity == "present"
        for fact in extracted.facts
    )
    # Quality/completeness is an observable input. Explicit uncertainty and
    # absent facts never become a positive symptom signal.
    usable_text = current.quality in {"good", "questionable"} and current.completeness > 0
    return numeric_attention or (text_attention and usable_text), False


def method_c_no_text(history: list[DayRecord], current: DayRecord) -> tuple[bool, bool]:
    """Ablation: same numeric personal baseline, with text excluded."""

    return baseline_b(history, current)


def predict(
    dataset_records: Iterable[DayRecord],
    method: str,
    *,
    extractor: FactExtractor | None = None,
) -> list[Prediction]:
    """Predict using observable records; hidden labels are attached only for evaluation."""

    by_profile: dict[str, list[DayRecord]] = {}
    for row in dataset_records:
        by_profile.setdefault(row.profile_id, []).append(row)
    active_extractor = extractor or DeterministicRuExtractor()
    result: list[Prediction] = []
    for profile_id, rows in by_profile.items():
        rows.sort(key=lambda row: row.day_index)
        for index, current in enumerate(rows):
            history = rows[:index]
            if method == "baseline_a":
                attention, insufficient = baseline_a(current)
            elif method == "baseline_b":
                attention, insufficient = baseline_b(history, current)
            elif method == "method_c_no_text":
                attention, insufficient = method_c_no_text(history, current)
            elif method == "method_c":
                extracted = active_extractor.extract(current.check_in_text)
                attention, insufficient = method_c(history, current, extracted=extracted)
            else:
                raise ValueError(f"Unknown method: {method}")
            result.append(
                Prediction(
                    profile_id=profile_id,
                    day_index=current.day_index,
                    method=method,
                    attention=attention,
                    insufficient_data=insufficient,
                    ground_truth_event=current.ground_truth_event,
                    scenario_type=current.scenario_type,
                    change_start_day=current.change_start_day,
                    ground_truth_facts=current.ground_truth_facts,
                )
            )
    return result
