"""Deterministic monitoring logic for the first manual-input vertical slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from statistics import median
from typing import Iterable
from zoneinfo import ZoneInfo


DEFAULT_PROFILE_TIMEZONE = "Europe/Moscow"
NUMERIC_RULE_VERSION = "daily-multimetric-v2"


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
    id: str | None = None
    check_in_id: str | None = None
    text_revision: int | None = None
    recorded_at: datetime | None = None
    confirmed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Baseline:
    metric: Metric
    center: float | None
    mad: float | None
    scale: float | None
    sample_count: int
    window_start: date
    window_end: date
    timezone: str = DEFAULT_PROFILE_TIMEZONE
    source_observation_ids: tuple[str, ...] = ()
    days: tuple[date, ...] = ()
    aggregation: str = "latest_daily_value"
    quality: str = "unknown"

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
    analysis_details: dict | None = None
    text_provenance: tuple[dict, ...] = ()


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
    profile_timezone: str = DEFAULT_PROFILE_TIMEZONE,
) -> Baseline:
    """Use valid daily aggregates from [D-window_days, D), in profile time."""
    if window_days < 1 or min_samples < 1:
        raise ValueError("window_days and min_samples must be positive")
    current_day = _utc(as_of).astimezone(ZoneInfo(profile_timezone)).date()
    start = current_day - timedelta(days=window_days)
    end = current_day - timedelta(days=1)
    points = [point for point in aggregate_daily(observations, metric, as_of=as_of,
              profile_timezone=profile_timezone) if start <= point.day <= end]
    values = [point.value for point in points]
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
        timezone=profile_timezone,
        source_observation_ids=tuple(sorted({id for point in points for id in point.observation_ids})),
        days=tuple(point.day for point in points),
        aggregation=daily_aggregation(metric),
        quality="unknown" if any(point.quality == "unknown" for point in points) or not points else "good",
    )


@dataclass(frozen=True, slots=True)
class DailyObservation:
    metric: Metric
    day: date
    measured_at: datetime
    value: float
    observation_ids: tuple[str, ...]
    quality: str


def daily_aggregation(metric: Metric) -> str:
    # Sleep/activity are already daily totals, not additive interval samples.
    return "latest_daily_value" if metric in {Metric.SLEEP_HOURS, Metric.ACTIVITY_MINUTES} else "daily_median"


def valid_numeric(observation: Observation, *, as_of: datetime) -> bool:
    if observation.quality == "questionable":
        return False
    try:
        validate_observation_fields(
            observation.metric, observation.value, observation.unit,
            observation.measured_at, source=observation.source,
            quality=observation.quality, now=as_of,
        )
    except (ValueError, TypeError):
        return False
    return True


def aggregate_daily(
    observations: Iterable[Observation], metric: Metric, *, as_of: datetime,
    profile_timezone: str = DEFAULT_PROFILE_TIMEZONE,
) -> list[DailyObservation]:
    """One order-independent value per local day, with source IDs."""
    zone = ZoneInfo(profile_timezone)
    by_day: dict[date, list[Observation]] = {}
    for observation in observations:
        if observation.metric == metric and valid_numeric(observation, as_of=as_of):
            day = _utc(observation.measured_at).astimezone(zone).date()
            by_day.setdefault(day, []).append(observation)
    result = []
    for day, rows in sorted(by_day.items()):
        latest = max(_utc(row.measured_at) for row in rows)
        used = [row for row in rows if _utc(row.measured_at) == latest] if daily_aggregation(metric) == "latest_daily_value" else rows
        result.append(DailyObservation(
            metric, day, latest, float(median(row.value for row in used)),
            tuple(sorted({row.id for row in used})),
            "unknown" if any(row.quality == "unknown" for row in used) else "good",
        ))
    return result


def baseline_details(baseline: Baseline) -> dict:
    return {
        "metric": baseline.metric.value, "center": baseline.center,
        "mad": baseline.mad, "scale": baseline.scale,
        "sample_count": baseline.sample_count,
        "window_start": baseline.window_start.isoformat(),
        "window_end": baseline.window_end.isoformat(), "timezone": baseline.timezone,
        "days": [day.isoformat() for day in baseline.days],
        "source_observation_ids": list(baseline.source_observation_ids),
        "aggregation": baseline.aggregation, "quality": baseline.quality,
    }


def analyze_metrics(
    observations: Iterable[Observation], *, as_of: datetime,
    profile_timezone: str = DEFAULT_PROFILE_TIMEZONE,
    symptom_facts: Iterable[SymptomFact] = (),
) -> MonitoringEvent:
    """Analyze every supported metric on local day D, with a UTC cutoff."""
    rows = list(observations)
    cutoff = _utc(as_of)
    zone = ZoneInfo(profile_timezone)
    day = cutoff.astimezone(zone).date()
    start = datetime.combine(day, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    metrics, evidence = [], []
    used_ids: set[str] = set()
    for metric in Metric:
        baseline = calculate_baseline(rows, metric, as_of=cutoff, profile_timezone=profile_timezone)
        current = next((point for point in aggregate_daily(rows, metric, as_of=cutoff,
                       profile_timezone=profile_timezone) if point.day == day), None)
        excluded = sorted({row.id for row in rows if row.metric == metric
                           and baseline.window_start <= _utc(row.measured_at).astimezone(zone).date() <= day
                           and not valid_numeric(row, as_of=cutoff)})
        z = None
        status = "missing_measurement"
        if current is not None:
            status = "insufficient_data"
            if baseline.is_ready:
                assert baseline.center is not None and baseline.scale is not None
                z = (current.value - baseline.center) / baseline.scale
                status = "attention" if abs(z) >= 2.5 else "no_change"
            used_ids.update(current.observation_ids)
            used_ids.update(baseline.source_observation_ids)
        detail = {
            "metric": metric.value, "status": status,
            "value": current.value if current else None, "unit": expected_unit(metric),
            "measured_at": current.measured_at.isoformat() if current else None,
            "day": day.isoformat(), "quality": current.quality if current else "missing",
            "z_score": z, "baseline": baseline_details(baseline),
            "source_observation_ids": list(current.observation_ids) if current else [],
            "excluded_observation_ids": excluded,
        }
        metrics.append(detail)
        evidence.append(f"{metric.value}: {status}" + (
            f"; value={current.value:g} {expected_unit(metric)}; sample_days={baseline.sample_count}"
            + (f"; baseline={baseline.center:g}; z={z:.2f}" if z is not None else "")
            if current else ""
        ))
    statuses = [item["status"] for item in metrics]
    status = (MonitoringStatus.ATTENTION if "attention" in statuses else
              MonitoringStatus.INSUFFICIENT_DATA if "insufficient_data" in statuses else
              MonitoringStatus.NO_CHANGE if "no_change" in statuses else MonitoringStatus.INSUFFICIENT_DATA)
    # The application passes only current facts selected by the lifecycle rules.
    facts = [fact for fact in symptom_facts if fact.confirmed and fact.polarity == "present"]
    if facts and any(item["z_score"] is not None for item in metrics):
        status = MonitoringStatus.ATTENTION
        evidence.extend(f"symptom:{fact.category}" for fact in facts)
    messages = {
        MonitoringStatus.ATTENTION: "Обнаружено изменение, заслуживающее внимания. Проверьте результаты отдельных показателей.",
        MonitoringStatus.NO_CHANGE: "Среди доступных для сравнения показателей значимого изменения не обнаружено.",
        MonitoringStatus.INSUFFICIENT_DATA: "Для части показателей недостаточно дневной истории или нет актуальных измерений.",
    }
    return MonitoringEvent(
        status, None, None, tuple(evidence), messages[status],
        algorithm_version=NUMERIC_RULE_VERSION, level="normal" if status == MonitoringStatus.NO_CHANGE else status.value,
        source_observation_ids=tuple(sorted(used_ids)), period_start=start, period_end=cutoff,
        analysis_details={"as_of": cutoff.isoformat(), "timezone": profile_timezone,
                          "period_start": start.isoformat(), "period_end": cutoff.isoformat(),
                          "data_complete": all(item == "no_change" or item == "attention" for item in statuses),
                          "metrics": metrics},
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
