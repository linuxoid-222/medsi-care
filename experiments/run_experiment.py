"""Run the reproducible held-out comparison.

Usage:
    python -m experiments.run_experiment --output experiments/results/latest.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.extractor import DeterministicRuExtractor
from experiments.metrics import evaluate, evaluate_extractor
from experiments.methods import NUMERIC_RULES_VERSION, predict
from experiments.synthetic import EXPERIMENT_PROTOCOL_VERSION, generate_dataset, split_profiles


METHODS = ("baseline_a", "baseline_b", "method_c_no_text", "method_c")


def run(profile_count: int, days: int, seed: int, test_fraction: float) -> dict[str, object]:
    dataset = generate_dataset(profile_count=profile_count, days=days, seed=seed)
    train_ids, test_ids = split_profiles(dataset, test_fraction=test_fraction)
    train_set = set(train_ids)
    test_set = set(test_ids)
    train_records = [row for row in dataset.records if row.profile_id in train_set]
    test_records = [row for row in dataset.records if row.profile_id in test_set]
    extractor = DeterministicRuExtractor()

    metrics = []
    for method in METHODS:
        predictions = predict(test_records, method, extractor=extractor)
        metrics.append(evaluate(predictions, profile_count=len(test_ids), days=days).as_dict())
    return {
        "protocol_version": EXPERIMENT_PROTOCOL_VERSION,
        "seed": seed,
        "config": {
            "profile_count": profile_count,
            "days": days,
            "test_fraction": test_fraction,
            "split_strategy": "profile_id",
            "split_seed": seed + 17_071,
            "train_used_for_tuning": False,
            "numeric_rules_version": NUMERIC_RULES_VERSION,
            "extractor_version": extractor.version,
        },
        "split": {
            "train_profile_ids": list(train_ids),
            "test_profile_ids": list(test_ids),
            "train_record_count": len(train_records),
            "test_record_count": len(test_records),
        },
        "metrics": metrics,
        "extractor_metrics": evaluate_extractor(test_records, extractor).as_dict(),
        "limitations": [
            "synthetic data only",
            "deterministic heuristic extractor is not clinically trained",
            "confidence intervals are not calculated for this prototype sample size",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=int, default=100)
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--output", type=Path, default=Path("experiments/results/latest.json"))
    args = parser.parse_args()
    result = run(args.profiles, args.days, args.seed, args.test_fraction)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
