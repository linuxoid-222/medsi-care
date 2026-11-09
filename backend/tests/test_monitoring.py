from datetime import datetime, timedelta, timezone
from unittest import TestCase

from app.domain.monitoring import (
    Metric,
    MonitoringStatus,
    Observation,
    SymptomFact,
    analyze_observation,
    calculate_baseline,
)


class MonitoringTests(TestCase):
    def setUp(self) -> None:
        self.as_of = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
        self.history = [
            Observation(
                id=f"obs-{day}",
                profile_id="profile-demo",
                metric=Metric.SLEEP_HOURS,
                value=8.0,
                unit="hours",
                measured_at=self.as_of - timedelta(days=day),
            )
            for day in range(1, 9)
        ]

    def test_baseline_is_insufficient_below_minimum_sample_count(self) -> None:
        baseline = calculate_baseline(
            self.history[:6], Metric.SLEEP_HOURS, as_of=self.as_of
        )
        self.assertFalse(baseline.is_ready)
        self.assertEqual(baseline.sample_count, 6)

    def test_attention_event_keeps_measurement_and_rule_evidence(self) -> None:
        baseline = calculate_baseline(
            self.history, Metric.SLEEP_HOURS, as_of=self.as_of
        )
        current = Observation(
            id="obs-current",
            profile_id="profile-demo",
            metric=Metric.SLEEP_HOURS,
            value=5.0,
            unit="hours",
            measured_at=self.as_of,
        )
        event = analyze_observation(
            current,
            baseline,
            symptom_facts=[
                SymptomFact(
                    category="weakness",
                    polarity="present",
                    evidence="чувствую слабость",
                )
            ],
        )
        self.assertEqual(event.status, MonitoringStatus.ATTENTION)
        self.assertIn("sleep_hours=5 hours", event.evidence)
        self.assertIn("symptom:weakness", event.evidence)

    def test_stable_value_has_no_change(self) -> None:
        baseline = calculate_baseline(
            self.history, Metric.SLEEP_HOURS, as_of=self.as_of
        )
        current = Observation(
            id="obs-current",
            profile_id="profile-demo",
            metric=Metric.SLEEP_HOURS,
            value=8.1,
            unit="hours",
            measured_at=self.as_of,
        )
        event = analyze_observation(current, baseline)
        self.assertEqual(event.status, MonitoringStatus.NO_CHANGE)


if __name__ == "__main__":
    import unittest

    unittest.main()
