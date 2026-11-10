"""Synthetic demo scenario loader, isolated from normal production flows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from zoneinfo import ZoneInfo

from app.domain.monitoring import Metric, Observation
from app.store import CheckInRecord


@dataclass(frozen=True, slots=True)
class DemoScenario:
    seed: int
    days: int
    anchor_date: date
    timezone: str
    observations: tuple[Observation, ...]
    check_ins: tuple[CheckInRecord, ...]


def build_demo_scenario(
    *,
    profile_id: str = "profile-demo",
    seed: int = 20261110,
    days: int = 21,
    anchor_date: date,
    profile_timezone: str,
) -> DemoScenario:
    """Place a deterministic scenario on local days ending at the anchor."""

    if days < 14 or days > 28:
        raise ValueError("Demo scenario must contain between 14 and 28 days")
    zone = ZoneInfo(profile_timezone)
    start = anchor_date - timedelta(days=days - 1)
    identity = f"{profile_id}|{seed}|{anchor_date}|{profile_timezone}|{days}"
    prefix = f"demo-{seed}-{sha256(identity.encode()).hexdigest()[:16]}"
    observations: list[Observation] = []
    check_ins: list[CheckInRecord] = []
    for day in range(days):
        changed = day >= 14
        local_day = start + timedelta(days=day)
        measured_at = datetime.combine(local_day, time.min, zone).astimezone(timezone.utc)
        sleep = 5.0 if changed else 8.0
        activity = 25.0 if changed else 65.0
        pulse = 90.0 if changed else 70.0
        observations.extend(
            [
                Observation(
                    id=f"{prefix}-sleep-{day:02d}",
                    profile_id=profile_id,
                    metric=Metric.SLEEP_HOURS,
                    value=sleep,
                    unit="hours",
                    measured_at=measured_at,
                    source="simulator",
                ),
                Observation(
                    id=f"{prefix}-activity-{day:02d}",
                    profile_id=profile_id,
                    metric=Metric.ACTIVITY_MINUTES,
                    value=activity,
                    unit="minutes",
                    measured_at=measured_at,
                    source="simulator",
                ),
                Observation(
                    id=f"{prefix}-pulse-{day:02d}",
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
                id=f"{prefix}-checkin-{day:02d}",
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
    return DemoScenario(seed, days, anchor_date, profile_timezone, tuple(observations), tuple(check_ins))
