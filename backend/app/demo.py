"""Synthetic demo scenario loader, isolated from normal production flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.monitoring import Metric, Observation
from app.store import CheckInRecord


@dataclass(frozen=True, slots=True)
class DemoScenario:
    seed: int
    days: int
    observations: tuple[Observation, ...]
    check_ins: tuple[CheckInRecord, ...]


def build_demo_scenario(
    *,
    profile_id: str = "profile-demo",
    seed: int = 20261110,
    days: int = 21,
) -> DemoScenario:
    """Build a deterministic 14-day baseline plus a 7-day change."""

    if days < 14 or days > 28:
        raise ValueError("Demo scenario must contain between 14 and 28 days")
    start = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    observations: list[Observation] = []
    check_ins: list[CheckInRecord] = []
    for day in range(days):
        changed = day >= 14
        measured_at = start + timedelta(days=day)
        sleep = 5.0 if changed else 8.0
        activity = 25.0 if changed else 65.0
        pulse = 90.0 if changed else 70.0
        observations.extend(
            [
                Observation(
                    id=f"demo-{seed}-sleep-{day:02d}",
                    profile_id=profile_id,
                    metric=Metric.SLEEP_HOURS,
                    value=sleep,
                    unit="hours",
                    measured_at=measured_at,
                    source="simulator",
                ),
                Observation(
                    id=f"demo-{seed}-activity-{day:02d}",
                    profile_id=profile_id,
                    metric=Metric.ACTIVITY_MINUTES,
                    value=activity,
                    unit="minutes",
                    measured_at=measured_at,
                    source="simulator",
                ),
                Observation(
                    id=f"demo-{seed}-pulse-{day:02d}",
                    profile_id=profile_id,
                    metric=Metric.PULSE_BPM,
                    value=pulse,
                    unit="bpm",
                    measured_at=measured_at,
                    source="simulator",
                ),
            ]
        )
        check_ins.append(
            CheckInRecord(
                id=f"demo-{seed}-checkin-{day:02d}",
                profile_id=profile_id,
                text=(
                    "Последние дни чувствую слабость и плохо сплю."
                    if changed
                    else "Сегодня чувствую себя обычно."
                ),
                source="simulator",
                created_at=measured_at,
            )
        )
    return DemoScenario(seed, days, tuple(observations), tuple(check_ins))
