from dataclasses import fields, replace
import subprocess
import sys
import json

import pytest

from experiments.inputs import MethodInput
from experiments.methods import Prediction, predict
from experiments.metrics import evaluate
from experiments.run_experiment import run, source_provenance
from experiments.synthetic import generate_dataset
from experiments.verify_report import verify


def test_future_mutation_and_prefix_do_not_change_earlier_predictions():
    records = list(generate_dataset(profile_count=4, days=20, seed=7).records[:20])
    inputs = [row.observable() for row in records]
    modified = [row if row.day_index < 12 else replace(
        row, sleep_hours=24, activity_minutes=0, pulse_bpm=200,
        check_in_text="Чувствую слабость сегодня.",
    ) for row in inputs]
    for method in ("baseline_a", "baseline_b", "method_c_no_text", "method_c"):
        original = predict(inputs, method)
        assert original[:12] == predict(inputs[:12], method)
        assert original[:12] == predict(modified, method)[:12]
        assert original == predict(list(reversed(inputs)), method)


def test_methods_cannot_receive_hidden_labels():
    records = generate_dataset(profile_count=4, days=16, seed=7).records
    with pytest.raises(TypeError, match="MethodInput only"):
        predict(records, "method_c")
    names = {field.name for field in fields(MethodInput)}
    assert not names & {"ground_truth_event", "ground_truth_facts", "scenario_type", "change_start_day", "symptom_present"}
    assert not {field.name for field in fields(Prediction)} & {"ground_truth_event", "scenario_type"}


def test_metrics_keep_insufficient_and_missed_episodes_and_repeat_alert_days():
    original = generate_dataset(profile_count=4, days=16, seed=7).records[0]
    records = [replace(original, profile_id="p", day_index=i,
                       ground_truth_event=i >= 2, change_start_day=2) for i in range(4)]
    predictions = [Prediction("p", i, "test", i < 2, i == 3) for i in range(4)]
    metrics = evaluate(predictions, records=records)
    assert (metrics.true_positives, metrics.false_positives, metrics.false_negatives, metrics.true_negatives) == (0, 2, 2, 0)
    assert metrics.person_days == 4
    assert metrics.false_alerts_per_100_person_days == 50
    assert metrics.alert_person_days == 2
    assert metrics.insufficient_data_count == 1
    assert metrics.missed_episodes == 1
    assert metrics.latency_samples == 0
    assert metrics.detection_latency_days is None
    with pytest.raises(ValueError):
        evaluate(predictions[:-1], records=records)


def test_report_exposes_denominators_and_template_overlap():
    report = run(100, 28, 42, 0.2)
    assert report["evaluation"]["person_days"] == 560
    assert report["evaluation"]["positive_person_days"] == 156
    assert report["evaluation"]["negative_person_days"] == 404
    for metrics in report["metrics"]:
        assert sum(metrics[name] for name in (
            "true_positives", "false_positives", "false_negatives", "true_negatives"
        )) == 560
        assert metrics["latency_samples"] + metrics["missed_episodes"] == metrics["event_episodes"]
    assert report["evaluation"]["template_overlap"]["unseen_test_template_count"] == 0
    assert report["extractor_metrics"]["uncertainty_samples"] == 0


def test_archive_cli_refuses_to_overwrite_existing_file(tmp_path):
    target = tmp_path / "archive.json"
    target.write_text("preserve")
    result = subprocess.run(
        [sys.executable, "-m", "experiments.run_experiment", "--archive", "--output", str(target)],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "archive already exists" in result.stderr
    assert target.read_text() == "preserve"


def test_saved_json_can_be_recomputed_and_checked(tmp_path):
    report = run(4, 16, 42, 0.25)
    report["provenance"] = source_provenance(require_clean=False)
    target = tmp_path / "report.json"
    target.write_text(json.dumps(report))
    verify(target)
    report["metrics"][0]["false_positives"] += 1
    target.write_text(json.dumps(report))
    with pytest.raises(ValueError, match="differs from archive"):
        verify(target)
