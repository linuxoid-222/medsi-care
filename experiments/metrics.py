"""Evaluation metrics for held-out synthetic scenarios."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from experiments.methods import Prediction


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
    insufficient_data_rate: float

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate(predictions: list[Prediction], *, profile_count: int, days: int) -> MethodMetrics:
    tp = sum(item.attention and item.target_event for item in predictions)
    fp = sum(item.attention and not item.target_event for item in predictions)
    fn = sum((not item.attention) and item.target_event for item in predictions)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
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
        insufficient_data_rate=sum(item.insufficient_data for item in predictions) / max(1, len(predictions)),
    )
