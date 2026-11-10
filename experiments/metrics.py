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

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate(predictions: list[Prediction], *, profile_count: int, days: int) -> MethodMetrics:
    tp = sum(item.attention and item.ground_truth_event for item in predictions)
    fp = sum(item.attention and not item.ground_truth_event for item in predictions)
    fn = sum((not item.attention) and item.ground_truth_event for item in predictions)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    by_profile: dict[str, list[Prediction]] = {}
    for item in predictions:
        by_profile.setdefault(item.profile_id, []).append(item)
    latencies: list[int] = []
    for rows in by_profile.values():
        onset = next((item.change_start_day for item in rows if item.change_start_day is not None), None)
        if onset is None:
            continue
        detections = [item.day_index for item in rows if item.attention and item.day_index >= onset]
        if detections:
            latencies.append(min(detections) - onset)
    person_days = max(1, profile_count * days)
    return MethodMetrics(
        method=predictions[0].method if predictions else "unknown",
        samples=len(predictions),
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        false_alerts_per_100_person_days=fp * 100 / person_days,
        detection_latency_days=mean(latencies) if latencies else None,
        latency_samples=len(latencies),
        insufficient_data_rate=sum(item.insufficient_data for item in predictions) / max(1, len(predictions)),
    )


def evaluate_extractor(records: Iterable[DayRecord], extractor: FactExtractor) -> ExtractorMetrics:
    true_positives = false_positives = false_negatives = 0
    negation_errors = uncertainty_errors = 0
    samples = 0
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
    )
