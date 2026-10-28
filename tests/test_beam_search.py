"""Domain and search checks; run: python3 -m unittest discover -s tests -v."""

import argparse
import csv
import itertools
import math
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from beam_search import (
    CSV_COLUMNS, DEFAULT_DATA, EARTH_RADIUS_KM, City, beam_search, evaluate_tour,
    format_arrival, haversine_km, is_day, load_cities, make_problem, parse_departure,
    resolve_city, result_as_dict, select_cities,
)


def city(identity, latitude=0.0, longitude=0.0, day_risk=10.0, night_risk=80.0):
    return City(
        geonameid=identity, name=f"City {identity}", latitude=latitude, longitude=longitude,
        feature_class="P", feature_code="PPL", admin1_code="01", population=100,
        crime_index=40.0, day_safety=100 - day_risk, night_safety=100 - night_risk,
        day_risk=day_risk, night_risk=night_risk, numbeo_contributors=5,
        numbeo_last_update="2026-01-01", numbeo_url="https://www.numbeo.com/crime/in/Test",
    )


def exact_problem(cities, matrix, departure=18 * 60, alpha=0.5):
    """Exact synthetic distances make time-boundary expectations independent of Haversine."""
    problem = make_problem(cities, cities[0].geonameid, departure, alpha)
    longest = max(max(row) for row in matrix)
    return replace(
        problem, distances_km=tuple(tuple(row) for row in matrix),
        distance_divisor_km=len(cities) * longest if longest else 1.0,
    )


class DatasetTests(unittest.TestCase):
    def write_csv(self, rows, columns=CSV_COLUMNS):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "cities.csv"
        with path.open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_master_data_and_leading_zero_state_codes(self):
        cities = load_cities(DEFAULT_DATA)
        self.assertEqual(len(cities), 43)
        self.assertEqual(len({location.geonameid for location in cities}), 43)
        self.assertEqual(resolve_city(cities, "Batu Pahat").admin1_code, "01")

    def test_reject_duplicate_ids(self):
        row = asdict(city(1))
        with self.assertRaisesRegex(ValueError, "duplicate geonameid"):
            load_cities(self.write_csv([row, row]))

    def test_reject_malformed_source_fields(self):
        invalid = (
            ("name", ""), ("latitude", "91"), ("longitude", "-181"),
            ("day_risk", "NaN"), ("night_safety", "Infinity"),
            ("crime_index", "101"), ("day_risk", "10.01"),
            ("population", "-1"), ("numbeo_contributors", "2.5"),
            ("numbeo_last_update", "2026-02-30"), ("numbeo_last_update", "20260101"),
            ("feature_class", "A"), ("geonameid", "0"), ("numbeo_url", "relative/url"),
        )
        for field, value in invalid:
            with self.subTest(field=field, value=value):
                row = asdict(city(1))
                row[field] = value
                with self.assertRaisesRegex(ValueError, "CSV row 2"):
                    load_cities(self.write_csv([row]))

    def test_reject_missing_header_and_empty_dataset(self):
        with self.assertRaisesRegex(ValueError, "16 documented columns"):
            load_cities(self.write_csv([], CSV_COLUMNS[:-1]))
        with self.assertRaisesRegex(ValueError, "no cities"):
            load_cities(self.write_csv([]))

    def test_subset_keeps_depot_and_master_unchanged(self):
        cities = load_cities()
        original = tuple(asdict(location) for location in cities)
        depot = resolve_city(cities, "1735161")
        subset = select_cities(cities, depot, ["ipoh", "Johor Bahru"])
        self.assertEqual({location.name for location in subset}, {"Kuala Lumpur", "Ipoh", "Johor Bahru"})
        self.assertEqual(tuple(asdict(location) for location in cities), original)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            select_cities(cities, depot, ["Ipoh", str(resolve_city(cities, "Ipoh").geonameid)])
        with self.assertRaisesRegex(ValueError, "unknown"):
            resolve_city(cities, "missing city")


class ModelTests(unittest.TestCase):
    def test_haversine_known_arc_symmetry_and_zero(self):
        first, second = city(1), city(2, longitude=90)
        expected = math.pi * EARTH_RADIUS_KM / 2
        self.assertAlmostEqual(haversine_km(first, second), expected)
        self.assertEqual(haversine_km(first, second), haversine_km(second, first))
        self.assertEqual(haversine_km(first, first), 0.0)
        problem = make_problem([first, second], 1)
        self.assertEqual(problem.distances_km[0][0], 0.0)
        self.assertEqual(problem.distances_km[0][1], problem.distances_km[1][0])

    def test_day_night_boundaries_repeat_each_day(self):
        for offset in (0, 1440, 3 * 1440):
            for minute, expected in ((0, False), (419.999, False), (420, True),
                                     (1139.999, True), (1140, False), (1439, False)):
                with self.subTest(offset=offset, minute=minute):
                    self.assertEqual(is_day(offset + minute), expected)

    def test_arrival_risks_and_downstream_recalculation(self):
        cities = [city(1, day_risk=100, night_risk=100),
                  city(2, day_risk=10, night_risk=90), city(3, day_risk=20, night_risk=40)]
        problem = exact_problem(cities, [[0, 30, 30], [30, 0, 30], [30, 30, 0]])
        first = evaluate_tour(problem, [0, 1, 2, 0])
        reverse = evaluate_tour(problem, [0, 2, 1, 0])
        self.assertEqual([visit.arrival_minutes for visit in first.visits], [1080, 1110, 1140, 1170])
        self.assertEqual(first.total_risk, 10 + 40)
        self.assertEqual(reverse.total_risk, 20 + 90)
        self.assertEqual(first.total_distance_km, 90)
        self.assertIsNone(first.visits[0].arrival_risk)
        self.assertIsNone(first.visits[-1].arrival_risk)
        self.assertEqual(cities[1].day_risk, 10)  # Evaluation never alters source scores.

    def test_exact_0700_arrival_no_waiting_and_zero_service(self):
        problem = exact_problem([city(1), city(2)], [[0, 30], [30, 0]], departure=6 * 60 + 30)
        evaluation = evaluate_tour(problem, [0, 1, 0])
        self.assertEqual(evaluation.visits[1].arrival_minutes, 420)
        self.assertEqual(evaluation.visits[1].arrival_risk, 10)
        self.assertEqual(evaluation.visits[-1].arrival_minutes, 450)
        night_problem = replace(problem, departure_minutes=5 * 60)
        night = evaluate_tour(night_problem, [0, 1, 0])
        self.assertEqual(night.visits[1].arrival_minutes, 330)
        self.assertEqual(night.visits[1].arrival_risk, 80)

    def test_midnight_and_multi_day_travel(self):
        problem = exact_problem([city(1), city(2)], [[0, 3000], [3000, 0]], departure=23 * 60 + 30)
        evaluation = evaluate_tour(problem, [0, 1, 0])
        self.assertEqual(format_arrival(evaluation.visits[1].arrival_minutes), "D+3 01:30:00")
        self.assertEqual(format_arrival(evaluation.visits[-1].arrival_minutes), "D+5 03:30:00")
        self.assertEqual(evaluation.total_risk, 80)
        self.assertEqual(format_arrival(1440), "D+1 00:00:00")

    def test_weighted_objective_and_fixed_scales(self):
        cities = [city(1), city(2), city(3)]
        matrix = [[0, 10, 20], [10, 0, 15], [20, 15, 0]]
        for alpha in (0.0, 0.3, 1.0):
            with self.subTest(alpha=alpha):
                problem = exact_problem(cities, matrix, departure=8 * 60, alpha=alpha)
                evaluation = evaluate_tour(problem, [0, 1, 2, 0])
                self.assertEqual(problem.distance_divisor_km, 60)
                self.assertEqual(problem.risk_divisor, 200)
                self.assertAlmostEqual(evaluation.distance_scaled, 45 / 60)
                self.assertAlmostEqual(evaluation.risk_scaled, 20 / 200)
                self.assertAlmostEqual(evaluation.cost, alpha * 45 / 60 + (1 - alpha) * 20 / 200)

    def test_all_day_all_night_and_equal_scores(self):
        matrix = [[0, 1, 1], [1, 0, 1], [1, 1, 0]]
        cities = [city(1), city(2), city(3)]
        for departure, expected in ((8 * 60, 20), (23 * 60, 160)):
            problem = exact_problem(cities, matrix, departure=departure)
            self.assertEqual(evaluate_tour(problem, [0, 1, 2, 0]).total_risk, expected)
        equal = [city(1, day_risk=25, night_risk=25), city(2, day_risk=25, night_risk=25)]
        for departure in (8 * 60, 23 * 60):
            problem = make_problem(equal, 1, departure)
            self.assertEqual(evaluate_tour(problem, [0, 1, 0]).total_risk, 25)

    def test_coincident_cities_have_zero_scaled_distance(self):
        problem = make_problem([city(1), city(2)], 1)
        evaluation = evaluate_tour(problem, [0, 1, 0])
        self.assertEqual(problem.distance_divisor_km, 1.0)
        self.assertEqual(evaluation.distance_scaled, 0.0)
        self.assertTrue(math.isfinite(evaluation.cost))

    def test_reject_invalid_tours(self):
        problem = make_problem([city(1), city(2), city(3)], 1)
        for route in ([], [0, 1, 0], [0, 1, 1, 0], [1, 0, 2, 1],
                      [0, 1, 3, 0], [0, 1, -1, 0], [0, True, 2, 0]):
            with self.subTest(route=route), self.assertRaisesRegex(ValueError, "tour must"):
                evaluate_tour(problem, route)

    def test_reject_invalid_instance_parameters(self):
        cities = [city(1), city(2)]
        for alpha in (-0.1, 1.1, math.nan, math.inf):
            with self.subTest(alpha=alpha), self.assertRaisesRegex(ValueError, "alpha"):
                make_problem(cities, 1, alpha=alpha)
        for departure in (-1, 1440, math.nan, math.inf):
            with self.subTest(departure=departure), self.assertRaisesRegex(ValueError, "departure"):
                make_problem(cities, 1, departure_minutes=departure)
        for selected, depot in (([city(1)], 1), ([city(1), city(1)], 1), (cities, 99)):
            with self.subTest(depot=depot, selected=selected), self.assertRaises(ValueError):
                make_problem(selected, depot)
        with self.assertRaisesRegex(ValueError, "latitude"):
            make_problem([city(1), city(2, latitude=math.nan)], 1)

    def test_departure_parser(self):
        self.assertEqual(parse_departure("00:00"), 0)
        self.assertEqual(parse_departure("23:59"), 1439)
        for value in ("24:00", "07:60", "7:00", "07:0", "noon", "-1:00", "07:00:00"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                parse_departure(value)


class BeamSearchTests(unittest.TestCase):
    def test_two_city_instance_with_width_one(self):
        problem = make_problem([city(1), city(2, longitude=1)], 1)
        result = beam_search(problem, 1)
        self.assertEqual(result.evaluation.tour, (0, 1, 0))
        self.assertEqual(result.generated_states, 1)
        self.assertEqual(result.expanded_states, 1)
        self.assertAlmostEqual(result.evaluation.total_distance_km, 2 * problem.distances_km[0][1])

    def test_return_distance_is_included_before_final_pruning(self):
        cities = [city(1), city(2, day_risk=10, night_risk=0), city(3, day_risk=0, night_risk=0)]
        problem = exact_problem(cities, [[0, 1, 10], [1, 0, 10], [10, 10, 0]], departure=18 * 60 + 45)
        # Ignoring closure would prefer prefix 0->1->2 (11 km + risk 10)
        # to 0->2->1 (20 km + risk 0). Closed tours both travel 21 km.
        result = beam_search(problem, 2)
        self.assertEqual(result.evaluation.tour, (0, 2, 1, 0))
        self.assertAlmostEqual(result.evaluation.cost, 0.35)

    def test_wide_beam_matches_exhaustive_optimum(self):
        master = load_cities()
        selected = [resolve_city(master, name) for name in
                    ("Kuala Lumpur", "Ipoh", "Johor Bahru", "Kuantan", "Alor Setar", "Miri")]
        for departure, alpha in itertools.product((6 * 60 + 30, 18 * 60, 23 * 60 + 45), (0.0, 0.5, 1.0)):
            with self.subTest(departure=departure, alpha=alpha):
                problem = make_problem(selected, 1735161, departure, alpha)
                stops = [index for index in range(len(selected)) if index != problem.depot]
                optimum = min(
                    evaluate_tour(problem, (problem.depot, *order, problem.depot)).cost
                    for order in itertools.permutations(stops)
                )
                result = beam_search(problem, math.factorial(len(stops)))
                self.assertAlmostEqual(result.evaluation.cost, optimum, places=12)

    def test_no_state_merging_when_visited_set_and_current_city_match(self):
        # An unpruned four-stop tree generates 4 + 12 + 24 + 24 states.
        # Deduplicating by (visited, current) would remove distinct prefixes.
        problem = make_problem([city(index, longitude=index * index) for index in range(1, 6)], 1)
        result = beam_search(problem, 24)
        self.assertEqual(result.generated_states, 64)
        self.assertEqual(result.expanded_states, 41)
        self.assertEqual(result.peak_beam_size, 24)

    def test_deterministic_ties_and_low_width(self):
        cities = [city(index) for index in (4, 2, 3, 1)]
        problem = make_problem(cities, 1)
        first = beam_search(problem, 1)
        second = beam_search(make_problem(list(reversed(cities)), 1), 1)
        self.assertEqual(first.evaluation, second.evaluation)
        self.assertEqual(first.evaluation.tour, (0, 1, 2, 3, 0))
        self.assertEqual(first.peak_beam_size, 1)

    def test_reject_invalid_beam_widths(self):
        problem = make_problem([city(1), city(2)], 1)
        for width in (0, -1, 1.5, True):
            with self.subTest(width=width), self.assertRaisesRegex(ValueError, "positive integer"):
                beam_search(problem, width)

    def test_full_master_produces_valid_closed_tour_and_export(self):
        problem = make_problem(load_cities(), 1735161, departure_minutes=18 * 60)
        result = beam_search(problem, 10)
        evaluation = evaluate_tour(problem, result.evaluation.tour)
        self.assertEqual(evaluation, result.evaluation)
        self.assertEqual(len(evaluation.tour), 44)
        self.assertLessEqual(result.peak_beam_size, 10)
        self.assertGreaterEqual(evaluation.cost, 0)
        self.assertLessEqual(evaluation.cost, 1)
        payload = result_as_dict(problem, result)
        self.assertEqual(len(payload["instance"]["selected_geonameids"]), 43)
        self.assertIsNone(payload["route"][-1]["arrival_risk"])
        self.assertEqual(payload["objective"]["cost"], evaluation.cost)


if __name__ == "__main__":
    unittest.main()
