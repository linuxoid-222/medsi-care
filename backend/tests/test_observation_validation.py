from datetime import datetime, timedelta, timezone
from unittest import TestCase

from pydantic import ValidationError

from app.domain.monitoring import Metric, validate_pressure_pair
from app.schemas import ObservationCreate


class ObservationValidationTests(TestCase):
    def _payload(self, metric: Metric, value: float, unit: str | None = None, **kwargs):
        return ObservationCreate(
            metric=metric,
            value=value,
            unit=unit or {
                Metric.SLEEP_HOURS: "hours",
                Metric.ACTIVITY_MINUTES: "minutes",
                Metric.PULSE_BPM: "bpm",
                Metric.SYSTOLIC_BP: "mmHg",
                Metric.DIASTOLIC_BP: "mmHg",
            }[metric],
            measured_at=datetime.now(timezone.utc) - timedelta(minutes=1),
            **kwargs,
        )

    def test_valid_values_and_technical_boundaries_are_accepted(self) -> None:
        self._payload(Metric.SLEEP_HOURS, 0)
        self._payload(Metric.SLEEP_HOURS, 24)
        self._payload(Metric.ACTIVITY_MINUTES, 0)
        self._payload(Metric.ACTIVITY_MINUTES, 1440)
        self._payload(Metric.PULSE_BPM, 20)
        self._payload(Metric.PULSE_BPM, 250)
        self._payload(Metric.SYSTOLIC_BP, 50)
        self._payload(Metric.DIASTOLIC_BP, 30)

    def test_negative_and_impossible_values_are_rejected(self) -> None:
        for metric, value in (
            (Metric.SLEEP_HOURS, -0.1),
            (Metric.SLEEP_HOURS, 24.1),
            (Metric.ACTIVITY_MINUTES, -1),
            (Metric.ACTIVITY_MINUTES, 1441),
            (Metric.PULSE_BPM, 19),
            (Metric.PULSE_BPM, 251),
            (Metric.SYSTOLIC_BP, 49),
            (Metric.DIASTOLIC_BP, 29),
        ):
            with self.assertRaises(ValidationError):
                self._payload(metric, value)

    def test_future_date_and_wrong_unit_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ObservationCreate(
                metric=Metric.SLEEP_HOURS,
                value=8,
                unit="hours",
                measured_at=datetime.now(timezone.utc) + timedelta(seconds=2),
            )
        with self.assertRaises(ValidationError):
            self._payload(Metric.PULSE_BPM, 72, unit="hours")

    def test_source_and_quality_are_constrained(self) -> None:
        with self.assertRaises(ValidationError):
            self._payload(Metric.SLEEP_HOURS, 8, source="device")
        with self.assertRaises(ValidationError):
            self._payload(Metric.SLEEP_HOURS, 8, quality="excellent")

    def test_pressure_pair_must_be_ordered(self) -> None:
        validate_pressure_pair(120, 80)
        with self.assertRaises(ValueError):
            validate_pressure_pair(80, 120)
