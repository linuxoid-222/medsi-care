"""Synthetic histories with labels independent of detector inputs."""

from __future__ import annotations

from dataclasses import dataclass
import random


EXPERIMENT_PROTOCOL_VERSION = "research-v2"
SCENARIOS = (
    "stable",
    "sleep_drop",
    "activity_drop",
    "multimodal",
    "symptom_only",
    "pulse_change",
    "missing_change",
    "negation",
    "ambiguous",
    "discordant",
)


@dataclass(frozen=True, slots=True)
class GroundTruthFact:
    """Hidden evaluation label; never passed to an extractor or detector."""

    category: str
    polarity: str


@dataclass(frozen=True, slots=True)
class DayRecord:
    profile_id: str
    day_index: int
    scenario_type: str
    sleep_hours: float | None
    activity_minutes: float | None
    pulse_bpm: float | None
    check_in_text: str
    quality: str
    ground_truth_event: bool
    ground_truth_facts: tuple[GroundTruthFact, ...]
    change_start_day: int | None

    @property
    def completeness(self) -> float:
        values = (self.sleep_hours, self.activity_minutes, self.pulse_bpm)
        return sum(value is not None for value in values) / len(values)


@dataclass(frozen=True, slots=True)
class SyntheticDataset:
    records: tuple[DayRecord, ...]
    profile_ids: tuple[str, ...]
    seed: int
    protocol_version: str = EXPERIMENT_PROTOCOL_VERSION


def _bounded(value: float, low: float, high: float) -> float:
    return round(max(low, min(high, value)), 2)


def _scenario_text(scenario: str, active: bool) -> tuple[str, tuple[GroundTruthFact, ...]]:
    if not active:
        return "Сегодня чувствую себя обычно.", ()
    if scenario in {"multimodal", "symptom_only", "discordant"}:
        return "Чувствую слабость сегодня.", (GroundTruthFact("weakness", "present"),)
    if scenario == "negation":
        return "Слабости сегодня нет.", (GroundTruthFact("weakness", "absent"),)
    if scenario == "ambiguous":
        return "Возможно, чувствую слабость, но не уверен.", (GroundTruthFact("weakness", "uncertain"),)
    return "Сегодня чувствую себя обычно.", ()


def generate_dataset(
    *,
    profile_count: int = 100,
    days: int = 28,
    seed: int = 42,
) -> SyntheticDataset:
    """Generate histories and independent hidden labels from scenario specs."""

    if profile_count < 4 or days < 16:
        raise ValueError("profile_count must be >= 4 and days must be >= 16")
    rng = random.Random(seed)
    records: list[DayRecord] = []
    profile_ids = tuple(f"synthetic-{index:03d}" for index in range(profile_count))

    for profile_id in profile_ids:
        scenario = rng.choice(SCENARIOS)
        onset = rng.randint(days // 2, days - 5) if scenario != "stable" else None
        base_sleep = rng.uniform(6.5, 9.0)
        base_activity = rng.uniform(35.0, 110.0)
        base_pulse = rng.uniform(58.0, 86.0)
        for day_index in range(days):
            active = onset is not None and day_index >= onset
            sleep = _bounded(base_sleep + rng.gauss(0, 0.25), 3.0, 12.0)
            activity = _bounded(base_activity + rng.gauss(0, 5), 0.0, 240.0)
            pulse = _bounded(base_pulse + rng.gauss(0, 2.5), 35.0, 180.0)

            if active and scenario in {"sleep_drop", "multimodal", "missing_change", "negation", "ambiguous"}:
                sleep = _bounded(sleep - 2.0, 2.0, 12.0)
            if active and scenario == "activity_drop":
                activity = _bounded(activity - 50.0, 0.0, 240.0)
            if active and scenario == "pulse_change":
                pulse = _bounded(pulse + 22.0, 35.0, 180.0)

            # Missingness is generated before labels are evaluated and is an
            # observable quality/completeness property of the current record.
            if rng.random() < 0.04:
                sleep = None
            if rng.random() < 0.04:
                activity = None
            if rng.random() < 0.04:
                pulse = None
            if scenario == "missing_change" and active and rng.random() < 0.65:
                sleep = None

            text, facts = _scenario_text(scenario, active)
            observed_count = sum(value is not None for value in (sleep, activity, pulse))
            quality = "good" if observed_count == 3 else "questionable"
            records.append(
                DayRecord(
                    profile_id=profile_id,
                    day_index=day_index,
                    scenario_type=scenario,
                    sleep_hours=sleep,
                    activity_minutes=activity,
                    pulse_bpm=pulse,
                    check_in_text=text,
                    quality=quality,
                    ground_truth_event=active,
                    ground_truth_facts=facts,
                    change_start_day=onset,
                )
            )
    return SyntheticDataset(records=tuple(records), profile_ids=profile_ids, seed=seed)


def split_profiles(
    dataset: SyntheticDataset,
    *,
    test_fraction: float = 0.2,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Create a deterministic profile-level held-out split with no leakage."""

    if not 0 < test_fraction < 1:
        raise ValueError("test_fraction must be between 0 and 1")
    shuffled = list(dataset.profile_ids)
    random.Random(dataset.seed + 17_071).shuffle(shuffled)
    test_count = max(1, round(len(shuffled) * test_fraction))
    test_ids = tuple(sorted(shuffled[-test_count:]))
    train_ids = tuple(sorted(shuffled[:-test_count]))
    return train_ids, test_ids
