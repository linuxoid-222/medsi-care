"""Run the reproducible held-out comparison.

Usage:
    python -m experiments.run_experiment --output experiments/results/latest.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from experiments.metrics import evaluate
from experiments.methods import predict
from experiments.synthetic import generate_dataset, split_profiles


def run(profile_count: int, days: int, seed: int, test_fraction: float) -> dict[str, object]:
    dataset = generate_dataset(profile_count=profile_count, days=days, seed=seed)
    train_ids, test_ids = split_profiles(dataset, test_fraction=test_fraction)
    test_records = [row for row in dataset.records if row.profile_id in set(test_ids)]
    metrics = []
    for method in ("baseline_a", "baseline_b", "method_c"):
        predictions = predict(test_records, method)
        metrics.append(evaluate(predictions, profile_count=len(test_ids), days=days).as_dict())
    return {
        "seed": seed,
        "profile_count": profile_count,
        "days": days,
        "train_profile_count": len(train_ids),
        "test_profile_count": len(test_ids),
        "metrics": metrics,
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
