"""Black-box regressions from independent findings F1/F5/F10."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import main
from app.auth import UserContext
from app.domain.monitoring import Metric, Observation, calculate_baseline, aggregate_daily, analyze_metrics
from app.store import InMemoryStore


NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
USER = UserContext("demo-user", "user", "profile-demo")


def observation(id, metric, value, when):
    units = {Metric.SLEEP_HOURS: "hours", Metric.PULSE_BPM: "bpm"}
    return Observation(id, "profile-demo", metric, value, units[metric], when)


def history():
    return [observation(f"{metric.value}-{day}", metric, value, NOW - timedelta(days=day))
            for day in range(1, 9)
            for metric, value in ((Metric.SLEEP_HOURS, 8), (Metric.PULSE_BPM, 70))]


@pytest.fixture
def store(monkeypatch):
    store = InMemoryStore()
    monkeypatch.setattr(main, "store", store)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(main, "datetime", Clock)
    return store


def test_f1_normal_pulse_cannot_hide_sleep_change(store):
    for row in history():
        store.add_observation(row)
    store.add_observation(observation("sleep-current", Metric.SLEEP_HOURS, 4, NOW - timedelta(minutes=2)))
    store.add_observation(observation("pulse-current", Metric.PULSE_BPM, 70, NOW - timedelta(minutes=1)))
    assert main.analyze_profile("profile-demo", USER).status.value == "attention"


def test_f1_input_order_of_identical_observations_does_not_change_analysis(store):
    # Equal timestamps in the same set, with different insertion order.
    current = [observation("sleep-current", Metric.SLEEP_HOURS, 4, NOW),
               observation("pulse-current", Metric.PULSE_BPM, 70, NOW)]
    results = []
    for rows in (history() + current, list(reversed(history() + current))):
        store.reset_demo_profile("profile-demo")
        for row in rows:
            store.add_observation(row)
        result = main.analyze_profile("profile-demo", USER)
        results.append((result.status, result.evidence, result.metric, result.z_score))
    assert results[0] == results[1]


def test_f5_seven_rows_on_one_day_are_not_seven_history_days():
    rows = [observation(f"same-day-{i}", Metric.SLEEP_HOURS, 8,
                        NOW - timedelta(days=1, seconds=i)) for i in range(7)]
    baseline = calculate_baseline(rows, Metric.SLEEP_HOURS, as_of=NOW)
    assert not baseline.is_ready
    assert baseline.sample_count == 1


def test_f5_analysis_day_is_excluded_from_baseline():
    rows = [observation(f"today-{i}", Metric.SLEEP_HOURS, 8,
                        NOW - timedelta(minutes=i)) for i in range(8)]
    baseline = calculate_baseline(rows, Metric.SLEEP_HOURS, as_of=NOW)
    assert baseline.sample_count == 0
    assert not baseline.is_ready


def test_f10_trend_display_limit_does_not_cut_baseline_history(store):
    for day in range(21):
        store.add_observation(observation(f"sleep-{day}", Metric.SLEEP_HOURS, 8,
                                          NOW - timedelta(days=day)))
    short = main.trends("profile-demo", USER, metric=Metric.SLEEP_HOURS, days=7)
    full = main.trends("profile-demo", USER, metric=Metric.SLEEP_HOURS, days=28)
    assert len(short) == 7
    assert short[-1].baseline == full[-1].baseline == 8


def test_attention_survives_insufficient_and_missing_metrics(store):
    for row in history():
        if row.metric == Metric.SLEEP_HOURS:
            store.add_observation(row)
    store.add_observation(observation("sleep-current", Metric.SLEEP_HOURS, 4, NOW))
    store.add_observation(observation("pulse-current", Metric.PULSE_BPM, 70, NOW))
    result = main.analyze_profile("profile-demo", USER)
    assert result.status.value == "attention"
    details = {item.metric: item for item in result.analysis_details.metrics}
    assert details[Metric.SLEEP_HOURS].status == "attention"
    assert details[Metric.SLEEP_HOURS].baseline.center == 8
    assert details[Metric.SLEEP_HOURS].z_score == -10
    assert details[Metric.PULSE_BPM].status == "insufficient_data"
    assert details[Metric.ACTIVITY_MINUTES].status == "missing_measurement"
    assert not result.analysis_details.data_complete
    assert details[Metric.SLEEP_HOURS].source_observation_ids == ["sleep-current"]
    assert len(details[Metric.SLEEP_HOURS].baseline.source_observation_ids) == 8


@pytest.mark.parametrize("zone", ["Europe/Moscow", "America/New_York"])
def test_window_boundaries_are_local_calendar_days(zone):
    tz = ZoneInfo(zone)
    cutoff = datetime(2026, 11, 10, 0, 30, tzinfo=tz)
    start = datetime(2026, 10, 27, 0, 0, tzinfo=tz)
    rows = [observation("start", Metric.SLEEP_HOURS, 8, start),
            observation("too-old", Metric.SLEEP_HOURS, 3, start - timedelta(microseconds=1)),
            observation("yesterday", Metric.SLEEP_HOURS, 8,
                        datetime(2026, 11, 9, 23, 59, 59, tzinfo=tz)),
            observation("today", Metric.SLEEP_HOURS, 1,
                        datetime(2026, 11, 10, 0, 0, tzinfo=tz)),
            observation("future", Metric.SLEEP_HOURS, 2, cutoff + timedelta(hours=1))]
    baseline = calculate_baseline(rows, Metric.SLEEP_HOURS, as_of=cutoff, profile_timezone=zone)
    assert baseline.sample_count == 2
    assert set(baseline.source_observation_ids) == {"start", "yesterday"}
    assert baseline.window_start.isoformat() == "2026-10-27"
    assert baseline.window_end.isoformat() == "2026-11-09"


def test_daily_aggregation_does_not_sum_daily_totals_and_resolves_ties():
    rows = [observation("sleep-early", Metric.SLEEP_HOURS, 7, NOW - timedelta(hours=1)),
            observation("sleep-latest-a", Metric.SLEEP_HOURS, 8, NOW),
            observation("sleep-latest-b", Metric.SLEEP_HOURS, 10, NOW),
            observation("pulse-a", Metric.PULSE_BPM, 60, NOW - timedelta(hours=1)),
            observation("pulse-b", Metric.PULSE_BPM, 100, NOW)]
    for records in (rows, list(reversed(rows))):
        sleep = aggregate_daily(records, Metric.SLEEP_HOURS, as_of=NOW)[0]
        pulse = aggregate_daily(records, Metric.PULSE_BPM, as_of=NOW)[0]
        assert sleep.value == 9
        assert sleep.observation_ids == ("sleep-latest-a", "sleep-latest-b")
        assert pulse.value == 80
    activity = [Observation("a", "profile-demo", Metric.ACTIVITY_MINUTES, 20, "minutes", NOW - timedelta(hours=1)),
                Observation("b", "profile-demo", Metric.ACTIVITY_MINUTES, 35, "minutes", NOW)]
    assert aggregate_daily(activity, Metric.ACTIVITY_MINUTES, as_of=NOW)[0].value == 35


def test_invalid_and_questionable_history_is_excluded_and_missing_is_explicit():
    rows = [Observation(f"bad-{day}", "profile-demo", Metric.SLEEP_HOURS, 8,
                        "hours", NOW - timedelta(days=day), quality="questionable")
            for day in range(1, 9)]
    rows.extend([observation("current", Metric.SLEEP_HOURS, 8, NOW),
                 observation("future", Metric.PULSE_BPM, 70, NOW + timedelta(minutes=1)),
                 observation("stale-pulse", Metric.PULSE_BPM, 70, NOW - timedelta(days=1)),
                 Observation("bad-unit", "profile-demo", Metric.SLEEP_HOURS, 8, "bpm", NOW)])
    event = analyze_metrics(rows, as_of=NOW)
    detail = {item["metric"]: item for item in event.analysis_details["metrics"]}
    assert event.status.value == "insufficient_data"
    assert detail["sleep_hours"]["status"] == "insufficient_data"
    assert detail["sleep_hours"]["baseline"]["sample_count"] == 0
    assert len(detail["sleep_hours"]["excluded_observation_ids"]) == 9
    assert detail["pulse_bpm"]["status"] == "missing_measurement"
    assert not set(event.source_observation_ids) & {"bad-unit", "future", "stale-pulse"}


def test_explicit_historical_cutoff_and_future_cutoff(store):
    for row in history():
        store.add_observation(row)
    store.add_observation(observation("old-sleep", Metric.SLEEP_HOURS, 4, NOW - timedelta(days=1)))
    # No measurement today, even though a past deviation exists.
    assert main.analyze_profile("profile-demo", USER).status.value == "insufficient_data"
    assert main.analyze_profile("profile-demo", USER, as_of=NOW - timedelta(days=1)).status.value == "attention"
    with pytest.raises(main.HTTPException) as future:
        main.analyze_profile("profile-demo", USER, as_of=NOW + timedelta(seconds=1))
    assert future.value.status_code == 422


def test_analysis_and_trends_share_daily_baseline_and_sources(store):
    for row in history():
        store.add_observation(row)
    store.add_observation(observation("current", Metric.SLEEP_HOURS, 4, NOW))
    result = main.analyze_profile("profile-demo", USER)
    detail = next(item for item in result.analysis_details.metrics if item.metric == Metric.SLEEP_HOURS)
    point = main.trends("profile-demo", USER, metric=Metric.SLEEP_HOURS, days=1)[0]
    assert point.baseline_details == detail.baseline
    assert point.source_observation_ids == detail.source_observation_ids
    assert point.baseline == 8
    assert point.event_ids == [store.list_monitoring_events("profile-demo")[0].id]
