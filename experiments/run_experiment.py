"""Run the reproducible held-out comparison.

Usage:
    python -m experiments.run_experiment --output experiments/results/latest.json
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import subprocess
import sys
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

    inputs = [row.observable() for row in test_records]
    predictions_by_method = {}
    metrics = []
    for method in METHODS:
        predictions = predict(inputs, method, extractor=extractor)
        predictions_by_method[method] = predictions
        metrics.append(evaluate(predictions, records=test_records).as_dict())
    train_templates = {row.check_in_text for row in train_records}
    test_templates = {row.check_in_text for row in test_records}
    return {
        "report_schema_version": "research-report-v2.1",
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
            "baseline_window_days": 14,
            "min_numeric_samples": 7,
            "z_threshold": 2.5,
            "baseline_a_thresholds": {"sleep_lt_hours": 6.0, "activity_lt_minutes": 30.0, "pulse_gt_bpm": 100.0},
        },
        "split": {
            "train_profile_ids": list(train_ids),
            "test_profile_ids": list(test_ids),
            "train_record_count": len(train_records),
            "test_record_count": len(test_records),
        },
        "evaluation": {
            "unit": "person_day",
            "positive_person_days": sum(row.ground_truth_event for row in test_records),
            "negative_person_days": sum(not row.ground_truth_event for row in test_records),
            "person_days": len(test_records),
            "false_alert_denominator": "all held-out person-days, including insufficient_data",
            "repeated_alerts": "each positive day counts separately; no deduplication",
            "latency_unit": "days",
            "latency_policy": "mean for detected episodes only; missed episodes counted separately",
            "insufficient_policy": "attention=false; retained in confusion matrix and denominators",
            "template_overlap": {
                "train_templates": sorted(train_templates),
                "test_templates": sorted(test_templates),
                "shared_templates": sorted(train_templates & test_templates),
                "unseen_test_template_count": len(test_templates - train_templates),
            },
        },
        "metrics": metrics,
        "held_out_records": [asdict(row) for row in test_records],
        "predictions": {method: [asdict(row) for row in rows]
                        for method, rows in predictions_by_method.items()},
        "extractions": [{"profile_id": row.profile_id, "day_index": row.day_index,
                         **extractor.extract(row.check_in_text).model_dump()}
                        for row in test_records],
        "extractor_metrics": evaluate_extractor(test_records, extractor).as_dict(),
        "limitations": [
            "synthetic data only",
            "deterministic heuristic extractor is not clinically trained",
            "20 test profiles at default configuration; one seed; descriptive evaluation; statistical stability of improvement not established",
            "text templates overlap between train and test; extractor generalization not established",
        ],
    }


def source_provenance(*, require_clean: bool) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True)
    if require_clean and status.strip():
        raise RuntimeError("archive requires a clean Git working tree; commit reviewed changes first")
    sources = sorted((root / "experiments").glob("*.py"))
    return {
        "commit": commit, "working_tree_dirty": bool(status.strip()),
        "source_sha256": {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources},
        "python": sys.version,
        "packages": {name: version(name) for name in ("pydantic",)},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=int, default=100)
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-fraction", type=float, default=0.2)
    parser.add_argument("--output", type=Path, default=Path("experiments/results/latest.json"))
    parser.add_argument("--config-from", type=Path, help="Read generation/split config from a saved result")
    parser.add_argument("--archive", action="store_true", help="Require clean source commit and refuse overwrite")
    args = parser.parse_args()
    if args.config_from:
        saved = json.loads(args.config_from.read_text())
        args.profiles = saved["config"]["profile_count"]
        args.days = saved["config"]["days"]
        args.seed = saved["seed"]
        args.test_fraction = saved["config"]["test_fraction"]
    if args.archive and args.output.exists():
        parser.error("archive already exists; choose a new versioned path")
    provenance = source_provenance(require_clean=args.archive)
    result = run(args.profiles, args.days, args.seed, args.test_fraction)
    result["provenance"] = provenance
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x" if args.archive else "w") as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"held_out_records", "predictions", "extractions"}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
