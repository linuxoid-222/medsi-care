from unittest import TestCase

from app.demo import build_demo_scenario
from app.domain.monitoring import Metric
from app.store import InMemoryStore


class DemoScenarioTests(TestCase):
    def test_scenario_is_reproducible_and_contains_a_known_change(self) -> None:
        first = build_demo_scenario(seed=123, days=21)
        second = build_demo_scenario(seed=123, days=21)
        self.assertEqual(first, second)
        self.assertEqual(len(first.observations), 63)
        self.assertEqual(len(first.check_ins), 21)
        sleep = [item for item in first.observations if item.metric == Metric.SLEEP_HOURS]
        self.assertEqual(sleep[0].value, 8.0)
        self.assertEqual(sleep[14].value, 5.0)
        self.assertIn("слабость", first.check_ins[14].text)

    def test_reset_makes_loading_repeatable(self) -> None:
        store = InMemoryStore()
        scenario = build_demo_scenario(seed=123, days=14)
        for item in scenario.observations:
            store.add_observation(item)
        for item in scenario.check_ins:
            store.add_check_in(item)
        store.reset_demo_profile("profile-demo")
        for item in scenario.observations:
            store.add_observation(item)
        for item in scenario.check_ins:
            store.add_check_in(item)
        self.assertEqual(len(store.list_observations("profile-demo")), 42)
        self.assertEqual(len(store.list_check_ins("profile-demo")), 14)
