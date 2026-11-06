"""Checks for the 2-opt comparison script. These do not run the full study."""

import random
import unittest

from beam_search import load_cities, parse_departure
from experiments.compare_two_opt import (
    CURRENT_DEFAULT, EAST_MALAYSIA_NAMES, GAP_DEPARTURES, KLANG_VALLEY_NAMES,
    check_city_groups, choose_default, contributor_pool, costs_are_equal, draw_instances,
    east_malaysia_cities, gap_to_optimum, klang_valley_cities, outcome, solve_instance,
    summarise_gap_rows,
)


class ComparisonHelperTests(unittest.TestCase):
    def test_gap_rejects_a_search_that_beats_the_optimum(self):
        self.assertEqual(gap_to_optimum(5, 5), 0.0)
        self.assertAlmostEqual(gap_to_optimum(6, 5), 0.2)
        with self.assertRaises(RuntimeError):
            gap_to_optimum(4, 5)

    def test_outcome_names_the_cheaper_algorithm(self):
        self.assertEqual(outcome(1.0, 2.0), "two_opt_cheaper")
        self.assertEqual(outcome(2.0, 1.0), "beam_cheaper")
        self.assertEqual(outcome(1.0, 1.0), "tie")

    def test_city_groups_match_the_master_file(self):
        cities = list(load_cities())
        check_city_groups(cities)
        self.assertEqual({city.name for city in east_malaysia_cities(cities)}, EAST_MALAYSIA_NAMES)
        self.assertEqual({city.name for city in klang_valley_cities(cities)}, KLANG_VALLEY_NAMES)
        self.assertEqual(len(contributor_pool(cities)), 19)
        self.assertNotIn("Kuching", {city.name for city in contributor_pool(cities)})

    def test_sampling_is_repeatable(self):
        pool = contributor_pool(list(load_cities()))
        drawn = draw_instances(pool, 3, 201, GAP_DEPARTURES, 9)
        generator = random.Random(201)
        departure_minutes = [parse_departure(name) for name in GAP_DEPARTURES]
        for spec in drawn:
            chosen = generator.sample(pool, 9)
            minutes = generator.choice(departure_minutes)
            self.assertEqual([city.geonameid for city in spec["cities"]],
                             [city.geonameid for city in chosen])
            self.assertEqual(spec["departure_minutes"], minutes)
            self.assertEqual(spec["depot_id"], chosen[0].geonameid)
            self.assertEqual(len(spec["cities"]), 9)

    def test_weight_study_departures_are_balanced(self):
        pool = contributor_pool(list(load_cities()))
        drawn = draw_instances(pool, 20, 203, ("06:00", "08:00", "10:00", "14:00", "18:00"), 9,
                               balance_departures=True)
        counts = {}
        for spec in drawn:
            counts[spec["departure"]] = counts.get(spec["departure"], 0) + 1
        self.assertEqual(counts, {"06:00": 4, "08:00": 4, "10:00": 4, "14:00": 4, "18:00": 4})

    def test_summary_counts_wins_and_keeps_a_close_default(self):
        rows = [
            _fake_row("08:00", two_opt_costs={"best, nearest-neighbor": 1.0, "first, id-order": 1.2},
                      beam_costs={"100": 1.5}),
            _fake_row("18:00", two_opt_costs={"best, nearest-neighbor": 1.1, "first, id-order": 1.0},
                      beam_costs={"100": 0.9}),
        ]
        summary = summarise_gap_rows(rows)
        self.assertEqual(summary["trials"], 2)
        self.assertEqual(summary["two_opt_setting_wins"]["best, nearest-neighbor"], 1)
        self.assertEqual(summary["two_opt_setting_wins"]["first, id-order"], 1)
        self.assertEqual(summary["comparisons"]["best, nearest-neighbor vs beam 100"]["two_opt_cheaper"], 1)
        self.assertEqual(summary["comparisons"]["best, nearest-neighbor vs beam 100"]["beam_cheaper"], 1)
        self.assertIn("08:00", summary["by_departure"])
        self.assertEqual(summary["by_departure"]["08:00"]["by_departure"], {})
        self.assertEqual(summary["by_departure"]["08:00"]["trials"], 1)

        decision = choose_default(summary["two_opt"])
        self.assertEqual(decision["action"], "keep")
        self.assertEqual(decision["setting"], CURRENT_DEFAULT)
        close = {
            CURRENT_DEFAULT: {"mean_gap": 0.014, "median_runtime_seconds": 1.0},
            "first, id-order": {"mean_gap": 0.010, "median_runtime_seconds": 1.0},
        }
        self.assertEqual(choose_default(close)["action"], "keep")

    def test_default_changes_only_for_a_clearly_better_gap(self):
        summary = {
            CURRENT_DEFAULT: {"mean_gap": 0.05, "median_runtime_seconds": 1.0},
            "first, id-order": {"mean_gap": 0.01, "median_runtime_seconds": 2.0},
        }
        decision = choose_default(summary)
        self.assertEqual(decision["action"], "change")
        self.assertEqual(decision["setting"], "first, id-order")

    def test_readme_example_does_not_beat_the_optimum(self):
        cities = list(load_cities())
        chosen = [next(city for city in cities if city.name == name)
                  for name in ("Kuala Lumpur", "Ipoh", "Johor Bahru", "Kuantan", "Malacca")]
        kuala_lumpur = next(city.geonameid for city in chosen if city.name == "Kuala Lumpur")
        row = solve_instance(chosen, kuala_lumpur, parse_departure("18:00"), 0.4, 0.2, with_optimum=True)
        self.assertEqual(row["depot_name"], "Kuala Lumpur")
        self.assertEqual(row["geonameids"][0], min(row["geonameids"]))  # make_problem sorts by id
        for result in row["two_opt"].values():
            self.assertGreaterEqual(result["cost"] + 1e-9, row["optimum"])
            self.assertLessEqual(result["cost"], result["start_cost"] + 1e-12)
        for result in row["beam"].values():
            self.assertGreaterEqual(result["cost"] + 1e-9, row["optimum"])
        nearest = row["two_opt"]["best, nearest-neighbor"]
        self.assertTrue(costs_are_equal(nearest["start_cost"], row["nearest_neighbor"]["cost"]))
        self.assertEqual(set(row["beam"]), {"1", "20", "100"})
        self.assertEqual(row["geonameids"], sorted(row["geonameids"]))


def _fake_row(departure, two_opt_costs, beam_costs):
    two_opt = {}
    for name, cost in two_opt_costs.items():
        two_opt[name] = {"cost": cost, "gap": cost - 1, "runtime_seconds": cost}
    beam = {}
    for width, cost in beam_costs.items():
        beam[width] = {"cost": cost, "gap": cost - 1, "runtime_seconds": 0.1}
    return {
        "departure": departure,
        "nearest_neighbor": {"cost": 2.0, "gap": 1.0},
        "two_opt": two_opt,
        "beam": beam,
    }


if __name__ == "__main__":
    unittest.main()
