"""Evaluation metrics for held-out synthetic scenarios and text facts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from statistics import mean
from typing import Iterable

from experiments.extractor import FactExtractor
from experiments.methods import Prediction
from experiments.synthetic import DayRecord


@dataclass(frozen=True, slots=True)
class MethodMetrics:
    method: str
    samples: int
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    positive_person_days: int
    negative_person_days: int
    person_days: int
    alert_person_days: int
    insufficient_data_count: int
    event_episodes: int
    missed_episodes: int
    latency_sum_days: int
    precision: float
    recall: float
    f1: float
    false_alerts_per_100_person_days: float
    detection_latency_days: float | None
    latency_samples: int
    insufficient_data_rate: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExtractorMetrics:
    extractor_version: str
    samples: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    negation_errors: int
    uncertainty_errors: int
    negation_samples: int
    uncertainty_samples: int

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate(predictions: list[Prediction], *, records: list[DayRecord]) -> MethodMetrics:
    """Day-level confusion matrix; episode latency is conditional on detection.

    Every held-out person-day, including warm-up/insufficient_data, stays in
    the denominator. Repeated positive days count as separate alert-days.
    """
    truth = {(row.profile_id, row.day_index): row for row in records}
    keys = [(item.profile_id, item.day_index) for item in predictions]
    if len(truth) != len(records) or len(set(keys)) != len(keys) or set(keys) != set(truth):
        raise ValueError("predictions and truth must contain the same unique person-days")
    if len({item.method for item in predictions}) != 1:
        raise ValueError("evaluate expects one method")
    tp = fp = fn = tn = 0
    for item in predictions:
        positive = truth[item.profile_id, item.day_index].ground_truth_event
        tp += item.attention and positive
        fp += item.attention and not positive
        fn += not item.attention and positive
        tn += not item.attention and not positive
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    onsets = {row.profile_id: row.change_start_day for row in records
              if row.change_start_day is not None}
    latencies = []
    for profile_id, onset in onsets.items():
        detections = [item.day_index for item in predictions
                      if item.profile_id == profile_id and item.attention
                      and item.day_index >= onset
                      and truth[profile_id, item.day_index].ground_truth_event]
        if detections:
            latencies.append(min(detections) - onset)
    person_days = len(records)
    insufficient = sum(item.insufficient_data for item in predictions)
    return MethodMetrics(
        method=predictions[0].method,
        samples=person_days,
        true_positives=tp, false_positives=fp, false_negatives=fn, true_negatives=tn,
        positive_person_days=tp + fn, negative_person_days=fp + tn,
        person_days=person_days, alert_person_days=tp + fp,
        insufficient_data_count=insufficient, event_episodes=len(onsets),
        missed_episodes=len(onsets) - len(latencies), latency_sum_days=sum(latencies),
        precision=precision, recall=recall, f1=f1,
        false_alerts_per_100_person_days=fp * 100 / person_days if person_days else 0.0,
        detection_latency_days=mean(latencies) if latencies else None,
        latency_samples=len(latencies),
        insufficient_data_rate=insufficient / person_days if person_days else 0.0,
    )


def evaluate_extractor(records: Iterable[DayRecord], extractor: FactExtractor) -> ExtractorMetrics:
    true_positives = false_positives = false_negatives = 0
    negation_errors = uncertainty_errors = 0
    samples = 0
    negation_samples = uncertainty_samples = 0
    for row in records:
        samples += 1
        expected = {(fact.category, fact.polarity) for fact in row.ground_truth_facts}
        result = extractor.extract(row.check_in_text)
        predicted = {(fact.category, fact.polarity) for fact in result.facts}
        true_positives += len(expected & predicted)
        false_positives += len(predicted - expected)
        false_negatives += len(expected - predicted)
        expected_by_category = {fact.category: fact.polarity for fact in row.ground_truth_facts}
        predicted_by_category = {fact.category: fact.polarity for fact in result.facts}
        negation_samples += any(value == "absent" for value in expected_by_category.values())
        uncertainty_samples += any(value == "uncertain" for value in expected_by_category.values())
        if any(
            polarity == "absent" and predicted_by_category.get(category) != "absent"
            for category, polarity in expected_by_category.items()
        ):
            negation_errors += 1
        if any(
            polarity == "uncertain" and predicted_by_category.get(category) != "uncertain"
            for category, polarity in expected_by_category.items()
        ):
            uncertainty_errors += 1
    precision = true_positives / (true_positives + false_positives) if true_positives + false_positives else 0.0
    recall = true_positives / (true_positives + false_negatives) if true_positives + false_negatives else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ExtractorMetrics(
        extractor_version=extractor.version,
        samples=samples,
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
        precision=precision,
        recall=recall,
        f1=f1,
        negation_errors=negation_errors,
        uncertainty_errors=uncertainty_errors,
        negation_samples=negation_samples, uncertainty_samples=uncertainty_samples,
    )
