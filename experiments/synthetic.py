"""Deterministic synthetic histories with labels independent of detector code."""

from __future__ import annotations

from dataclasses import dataclass
import random


SCENARIOS = (
    "stable",
    "sleep_drop",
    "activity_drop",
    "multimodal",
    "symptom_only",
    "pulse_change",
    "missing_change",
)


@dataclass(frozen=True, slots=True)
class DayRecord:
    profile_id: str
    day_index: int
    scenario: str
    sleep_hours: float | None
    activity_minutes: float | None
    pulse_bpm: float | None
    symptom_present: bool
    symptom_text: str
    target_event: bool


@dataclass(frozen=True, slots=True)
class SyntheticDataset:
    records: tuple[DayRecord, ...]
    profile_ids: tuple[str, ...]
    seed: int


def _bounded(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 2)


def generate_dataset(
    *,
    profile_count: int = 100,
    days: int = 28,
    seed: int = 42,
) -> SyntheticDataset:
    """Generate labelled histories from an independent scenario specification."""

    if profile_count < 4 or days < 16:
        raise ValueError("profile_count must be >= 4 and days must be >= 16")
    rng = random.Random(seed)
    records: list[DayRecord] = []
    profile_ids = tuple(f"synthetic-{index:03d}" for index in range(profile_count))

    for profile_id in profile_ids:
        scenario = rng.choice(SCENARIOS)
        onset = rng.randint(days // 2, days - 5)
        base_sleep = rng.uniform(6.5, 9.0)
        base_activity = rng.uniform(35.0, 110.0)
        base_pulse = rng.uniform(58.0, 86.0)
        for day_index in range(days):
            active = day_index >= onset and scenario != "stable"
            sleep = _bounded(base_sleep + rng.gauss(0, 0.25), 3.0, 12.0)
            activity = _bounded(base_activity + rng.gauss(0, 5), 0.0, 240.0)
            pulse = _bounded(base_pulse + rng.gauss(0, 2.5), 35.0, 180.0)

            if active and scenario in {"sleep_drop", "multimodal", "missing_change"}:
                sleep = _bounded(sleep - 2.0, 2.0, 12.0)
            if active and scenario == "activity_drop":
                activity = _bounded(activity - 50.0, 0.0, 240.0)
            if active and scenario == "pulse_change":
                pulse = _bounded(pulse + 22.0, 35.0, 180.0)

            symptom_present = active and scenario in {"multimodal", "symptom_only"}
            symptom_text = "Чувствую слабость сегодня." if symptom_present else "Сегодня чувствую себя обычно."

            # Missingness is part of the independent scenario generator, not a
            # consequence of a detector decision.
            if rng.random() < 0.04:
                sleep = None
            if rng.random() < 0.04:
                activity = None
            if rng.random() < 0.04:
                pulse = None
            if scenario == "missing_change" and active and rng.random() < 0.65:
                sleep = None

            records.append(
                DayRecord(
                    profile_id=profile_id,
                    day_index=day_index,
                    scenario=scenario,
                    sleep_hours=sleep,
                    activity_minutes=activity,
                    pulse_bpm=pulse,
                    symptom_present=symptom_present,
                    symptom_text=symptom_text,
                    target_event=active,
                )
            )
    return SyntheticDataset(records=tuple(records), profile_ids=profile_ids, seed=seed)


def split_profiles(
    dataset: SyntheticDataset,
    *,
    test_fraction: float = 0.2,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between 0 and 1")
    test_count = max(1, round(len(dataset.profile_ids) * test_fraction))
    test_ids = dataset.profile_ids[-test_count:]
    train_ids = dataset.profile_ids[:-test_count]
    return train_ids, test_ids
