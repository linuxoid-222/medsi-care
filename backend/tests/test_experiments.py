from unittest import TestCase

from experiments.metrics import evaluate
from experiments.methods import predict
from experiments.run_experiment import run
from experiments.synthetic import generate_dataset, split_profiles


class ExperimentTests(TestCase):
    def test_generation_is_reproducible_and_split_by_profile(self) -> None:
        first = generate_dataset(profile_count=10, days=20, seed=7)
        second = generate_dataset(profile_count=10, days=20, seed=7)
        self.assertEqual(first, second)
        train_ids, test_ids = split_profiles(first, test_fraction=0.2)
        self.assertEqual(set(train_ids).intersection(test_ids), set())

    def test_methods_produce_held_out_metrics(self) -> None:
        result = run(profile_count=10, days=20, seed=7, test_fraction=0.2)
        self.assertEqual(result["train_profile_count"], 8)
        self.assertEqual(result["test_profile_count"], 2)
        self.assertEqual({item["method"] for item in result["metrics"]}, {"baseline_a", "baseline_b", "method_c"})

    def test_method_c_can_use_synthetic_symptom_signal(self) -> None:
        dataset = generate_dataset(profile_count=10, days=20, seed=7)
        _, test_ids = split_profiles(dataset, test_fraction=0.2)
        records = [row for row in dataset.records if row.profile_id in set(test_ids)]
        predictions = predict(records, "method_c")
        metrics = evaluate(predictions, profile_count=2, days=20)
        self.assertGreaterEqual(metrics.samples, 40)
