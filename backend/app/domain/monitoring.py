"""Deterministic monitoring logic for the first manual-input vertical slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from statistics import median
from typing import Iterable


class Metric(StrEnum):
    SLEEP_HOURS = "sleep_hours"
    ACTIVITY_MINUTES = "activity_minutes"
    PULSE_BPM = "pulse_bpm"
    SYSTOLIC_BP = "systolic_bp"
    DIASTOLIC_BP = "diastolic_bp"


class MonitoringStatus(StrEnum):
    NO_CHANGE = "no_change"
    ATTENTION = "attention"
    INSUFFICIENT_DATA = "insufficient_data"
    SAFETY = "safety"


@dataclass(frozen=True, slots=True)
class Observation:
    id: str
    profile_id: str
    metric: Metric
    value: float
    unit: str
    measured_at: datetime
    source: str = "manual"
    quality: str = "unknown"


@dataclass(frozen=True, slots=True)
class SymptomFact:
    category: str
    polarity: str
    evidence: str
    confirmed: bool = True
    temporal_context: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class Baseline:
    metric: Metric
    center: float | None
    mad: float | None
    scale: float | None
    sample_count: int
    window_start: date
    window_end: date

    @property
    def is_ready(self) -> bool:
        return self.center is not None and self.scale is not None


@dataclass(frozen=True, slots=True)
class MonitoringEvent:
    status: MonitoringStatus
    metric: Metric | None
    z_score: float | None
    evidence: tuple[str, ...]
    message: str
    algorithm_version: str = "manual-slice-v1"
    level: str = "attention"
    source_observation_ids: tuple[str, ...] = ()
    period_start: datetime | None = None
    period_end: datetime | None = None


_UNITS: dict[Metric, str] = {
    Metric.SLEEP_HOURS: "hours",
    Metric.ACTIVITY_MINUTES: "minutes",
    Metric.PULSE_BPM: "bpm",
    Metric.SYSTOLIC_BP: "mmHg",
    Metric.DIASTOLIC_BP: "mmHg",
}

# These are technical bounds for the synthetic demo prototype. They are not
# medical reference ranges and must not be presented as clinical guidance.
TECHNICAL_RANGES: dict[Metric, tuple[float, float]] = {
    Metric.SLEEP_HOURS: (0.0, 24.0),
    Metric.ACTIVITY_MINUTES: (0.0, 1440.0),
    Metric.PULSE_BPM: (20.0, 250.0),
    Metric.SYSTOLIC_BP: (50.0, 250.0),
    Metric.DIASTOLIC_BP: (30.0, 150.0),
}

OBSERVATION_SOURCES = frozenset({"manual", "simulator"})
OBSERVATION_QUALITIES = frozenset({"unknown", "good", "questionable"})


def expected_unit(metric: Metric) -> str:
    return _UNITS[metric]


def validate_observation_fields(
    metric: Metric,
    value: float,
    unit: str,
    measured_at: datetime,
    *,
    source: str = "manual",
    quality: str = "unknown",
    now: datetime | None = None,
) -> None:
    """Validate technical invariants before an observation enters storage."""

    if unit != expected_unit(metric):
        raise ValueError(f"unit must be {expected_unit(metric)} for {metric.value}")
    lower, upper = TECHNICAL_RANGES[metric]
    if not lower <= value <= upper:
        raise ValueError(f"value for {metric.value} must be between {lower:g} and {upper:g}")
    if source not in OBSERVATION_SOURCES:
        raise ValueError("source must be manual or simulator")
    if quality not in OBSERVATION_QUALITIES:
        raise ValueError("quality must be unknown, good, or questionable")
    normalized = _utc(measured_at)
    reference = _utc(now or datetime.now(timezone.utc))
    if normalized > reference:
        raise ValueError("measured_at cannot be in the future")


def validate_pressure_pair(systolic: float, diastolic: float) -> None:
    """Validate technical ordering when both pressure values share a timestamp."""

    if systolic <= diastolic:
        raise ValueError("systolic pressure must be greater than diastolic pressure")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calculate_baseline(
    observations: Iterable[Observation],
    metric: Metric,
    *,
    as_of: datetime,
    window_days: int = 14,
    min_samples: int = 7,
) -> Baseline:
    """Calculate a robust personal baseline without medical thresholds."""

    end = _utc(as_of).date()
    start = end - timedelta(days=window_days - 1)
    values = [
        obs.value
        for obs in observations
        if obs.metric == metric
        and start <= _utc(obs.measured_at).date() <= end
        and obs.unit == expected_unit(metric)
    ]
    center = median(values) if len(values) >= min_samples else None
    mad = median([abs(value - center) for value in values]) if center is not None else None

    # A zero MAD is valid for stable synthetic histories. Use a small, explicit
    # fallback scale so the rule engine never divides by zero.
    scale = None
    if center is not None and mad is not None:
        scale = 1.4826 * mad
        if scale < 1e-9:
            scale = max(abs(center) * 0.05, 0.1)

    return Baseline(
        metric=metric,
        center=float(center) if center is not None else None,
        mad=float(mad) if mad is not None else None,
        scale=float(scale) if scale is not None else None,
        sample_count=len(values),
        window_start=start,
        window_end=end,
    )


def analyze_observation(
    observation: Observation,
    baseline: Baseline,
    *,
    symptom_facts: Iterable[SymptomFact] = (),
    attention_threshold: float = 2.5,
) -> MonitoringEvent:
    """Return an explainable event from validated facts and measurements."""

    if not baseline.is_ready:
        return MonitoringEvent(
            status=MonitoringStatus.INSUFFICIENT_DATA,
            metric=observation.metric,
            z_score=None,
            evidence=(f"sample_count={baseline.sample_count}",),
            message="Недостаточно наблюдений для формирования индивидуального базового уровня.",
        )

    assert baseline.center is not None
    assert baseline.scale is not None
    z_score = (observation.value - baseline.center) / baseline.scale
    evidence = [
        f"{observation.metric.value}={observation.value:g} {observation.unit}",
        f"baseline={baseline.center:g} {observation.unit}",
        f"z={z_score:.2f}",
    ]
    confirmed_symptoms = [fact for fact in symptom_facts if fact.confirmed and fact.polarity == "present"]
    evidence.extend(f"symptom:{fact.category}" for fact in confirmed_symptoms)

    if abs(z_score) >= attention_threshold or confirmed_symptoms:
        reason = "изменение показателя относительно индивидуального уровня"
        if confirmed_symptoms:
            reason += " и подтверждённая жалоба"
        return MonitoringEvent(
            status=MonitoringStatus.ATTENTION,
            metric=observation.metric,
            z_score=z_score,
            evidence=tuple(evidence),
            message=f"Обнаружено изменение, заслуживающее внимания: {reason}.",
        )

    return MonitoringEvent(
        status=MonitoringStatus.NO_CHANGE,
        metric=observation.metric,
        z_score=z_score,
        evidence=tuple(evidence),
        message="По проверяемому правилу значимого изменения не обнаружено.",
    )
