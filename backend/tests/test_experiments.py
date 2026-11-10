import inspect
from unittest import TestCase

from experiments.extractor import DeterministicRuExtractor, ExtractedFact, ExtractorResult, LlmExtractorAdapter
from experiments.metrics import evaluate_extractor
from experiments.methods import method_c, predict
from experiments.run_experiment import run
from experiments.synthetic import DayRecord, GroundTruthFact, generate_dataset, split_profiles


class _SpyExtractor:
    version = "spy-v1"

    def __init__(self) -> None:
        self.inputs: list[str] = []

    def extract(self, text: str) -> ExtractorResult:
        self.inputs.append(text)
        return ExtractorResult(extractor_version=self.version, facts=[])


class _FakeLlmProvider:
    def extract_facts(self, text: str) -> list[object]:
        return [ExtractedFact(category="weakness", polarity="present", evidence=text)]


class ExperimentTests(TestCase):
    def test_generation_and_split_are_reproducible_without_profile_leakage(self) -> None:
        first = generate_dataset(profile_count=10, days=20, seed=7)
        second = generate_dataset(profile_count=10, days=20, seed=7)
        self.assertEqual(first, second)
        train_ids, test_ids = split_profiles(first, test_fraction=0.2)
        self.assertEqual(set(train_ids).intersection(test_ids), set())
        self.assertEqual(set(train_ids) | set(test_ids), set(first.profile_ids))

    def test_protocol_result_contains_split_config_and_all_comparators(self) -> None:
        result = run(profile_count=10, days=20, seed=7, test_fraction=0.2)
        self.assertEqual(result["config"]["split_strategy"], "profile_id")
        self.assertEqual(result["split"]["train_record_count"], 8 * 20)
        self.assertEqual(result["split"]["test_record_count"], 2 * 20)
        self.assertEqual(
            {item["method"] for item in result["metrics"]},
            {"baseline_a", "baseline_b", "method_c_no_text", "method_c"},
        )
        self.assertEqual(result["extractor_metrics"]["extractor_version"], "deterministic-ru-v1")

    def test_extractor_handles_present_negated_uncertain_and_absent_text(self) -> None:
        extractor = DeterministicRuExtractor()
        self.assertEqual(extractor.extract("Чувствую слабость сегодня.").facts[0].polarity, "present")
        self.assertEqual(extractor.extract("Слабости сегодня нет.").facts[0].polarity, "absent")
        self.assertEqual(
            extractor.extract("Возможно, чувствую слабость, но не уверен.").facts[0].polarity,
            "uncertain",
        )
        self.assertEqual(extractor.extract("Сегодня всё обычно.").facts, [])

    def test_optional_llm_adapter_uses_the_same_validated_schema(self) -> None:
        result = LlmExtractorAdapter(_FakeLlmProvider()).extract("синтетический текст")
        self.assertEqual(result.extractor_version, "llm-adapter-v1")
        self.assertEqual(result.facts[0].category, "weakness")

    def test_extractor_receives_only_text_and_method_c_does_not_read_labels(self) -> None:
        dataset = generate_dataset(profile_count=4, days=16, seed=11)
        records = list(dataset.records[:16])
        spy = _SpyExtractor()
        predictions = predict([row.observable() for row in records], "method_c", extractor=spy)
        self.assertEqual(len(spy.inputs), len(records))
        self.assertEqual(set(spy.inputs), {row.check_in_text for row in records})
        source = inspect.getsource(method_c)
        self.assertNotIn("symptom_present", source)
        self.assertNotIn("ground_truth", source)
        self.assertEqual(len(predictions), len(records))

    def test_method_c_decision_is_independent_of_changed_evaluation_labels(self) -> None:
        history = [
            DayRecord(
                profile_id="p",
                day_index=index,
                scenario_type="stable",
                sleep_hours=8.0,
                activity_minutes=70.0,
                pulse_bpm=70.0,
                check_in_text="Сегодня обычно.",
                quality="good",
                ground_truth_event=False,
                ground_truth_facts=(),
                change_start_day=None,
            )
            for index in range(8)
        ]
        first = history[-1]
        current_a = DayRecord(
            profile_id="p", day_index=8, scenario_type="stable", sleep_hours=5.0,
            activity_minutes=70.0, pulse_bpm=70.0, check_in_text="Сегодня обычно.",
            quality="good", ground_truth_event=True,
            ground_truth_facts=(GroundTruthFact("weakness", "present"),), change_start_day=8,
        )
        current_b = DayRecord(
            profile_id="p", day_index=8, scenario_type="stable", sleep_hours=5.0,
            activity_minutes=70.0, pulse_bpm=70.0, check_in_text="Сегодня обычно.",
            quality="good", ground_truth_event=False, ground_truth_facts=(), change_start_day=None,
        )
        extractor = DeterministicRuExtractor()
        self.assertEqual(
            method_c([row.observable() for row in history], current_a.observable(), extracted=extractor.extract(current_a.check_in_text)),
            method_c([row.observable() for row in history], current_b.observable(), extracted=extractor.extract(current_b.check_in_text)),
        )

    def test_extractor_metrics_include_negation_and_uncertainty_errors(self) -> None:
        dataset = generate_dataset(profile_count=20, days=16, seed=4)
        metrics = evaluate_extractor(dataset.records, DeterministicRuExtractor())
        self.assertGreaterEqual(metrics.samples, 20 * 16)
        self.assertEqual(metrics.negation_errors, 0)
        self.assertEqual(metrics.uncertainty_errors, 0)

    def test_repeated_run_has_identical_results(self) -> None:
        self.assertEqual(
            run(profile_count=12, days=20, seed=17, test_fraction=0.25),
            run(profile_count=12, days=20, seed=17, test_fraction=0.25),
        )
