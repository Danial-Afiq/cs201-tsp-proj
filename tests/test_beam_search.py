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
    format_arrival, haversine_km, instance_scales, is_day, load_cities, make_problem,
    parse_departure, resolve_city, result_as_dict, schedule_tour, select_cities,
)


def city(identity, latitude=0.0, longitude=0.0, day_risk=10.0, night_risk=80.0):
    return City(
        geonameid=identity, name=f"City {identity}", latitude=latitude, longitude=longitude,
        feature_class="P", feature_code="PPL", admin1_code="01", population=100,
        crime_index=40.0, day_safety=100 - day_risk, night_safety=100 - night_risk,
        day_risk=day_risk, night_risk=night_risk, numbeo_contributors=5,
        numbeo_last_update="2026-01-01", numbeo_url="https://www.numbeo.com/crime/in/Test",
    )


def exact_problem(cities, matrix, departure=18 * 60, alpha=0.5, beta=0.0):
    """Exact synthetic distances make time-boundary expectations independent of Haversine."""
    problem = make_problem(cities, cities[0].geonameid, departure, alpha, beta)
    distance_divisor, _, time_divisor = instance_scales(len(cities), max(max(row) for row in matrix))
    return replace(
        problem, distances_km=tuple(tuple(row) for row in matrix),
        distance_divisor_km=distance_divisor, time_divisor_minutes=time_divisor,
    )


def assert_no_night_driving(test, evaluation):
    """Every departure is by day and arrives before the next 07:00, unless it leaves at 07:00."""
    for visit, following in zip(evaluation.visits, evaluation.visits[1:]):
        departure = visit.arrival_minutes + visit.wait_minutes
        morning = (7 * 60 - departure) % 1440
        test.assertTrue(is_day(departure))
        test.assertTrue(morning == 0 or following.arrival_minutes - departure < morning)


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
        first = schedule_tour(problem, [0, 1, 2, 0])
        reverse = schedule_tour(problem, [0, 2, 1, 0])
        # The 19:00 arrival forces a night rest until 07:00 before the return.
        self.assertEqual([visit.arrival_minutes for visit in first.visits], [1080, 1110, 1140, 1890])
        self.assertEqual((first.visits[2].rest, first.visits[2].wait_minutes), ("night", 720))
        self.assertEqual(first.total_risk, 10 + 40)
        self.assertEqual(reverse.total_risk, 20 + 90)
        self.assertEqual(first.total_distance_km, 90)
        self.assertIsNone(first.visits[0].arrival_risk)
        self.assertIsNone(first.visits[-1].arrival_risk)
        self.assertEqual(cities[1].day_risk, 10)  # Evaluation never alters source scores.

    def test_day_night_boundaries_and_zero_service(self):
        for leg, risk in ((59, 10), (60, 80)):
            with self.subTest(leg=leg):
                problem = exact_problem([city(1), city(2)], [[0, leg], [leg, 0]], departure=18 * 60)
                evaluation = schedule_tour(problem, [0, 1, 0])
                self.assertEqual(evaluation.visits[1].arrival_minutes, 18 * 60 + leg)
                self.assertEqual(evaluation.visits[1].arrival_risk, risk)
        # From exactly 07:00 any leg may start; 1440 km arrives at the next 07:00.
        for leg, risk, wait in ((1440, 10, 0), (1439, 80, 1)):
            with self.subTest(leg=leg):
                problem = exact_problem([city(1), city(2)], [[0, leg], [leg, 0]], departure=7 * 60)
                evaluation = schedule_tour(problem, [0, 1, 0])
                self.assertEqual(evaluation.visits[0].wait_minutes, 0)
                self.assertEqual(evaluation.visits[1].arrival_minutes, 7 * 60 + leg)
                self.assertEqual(evaluation.visits[1].arrival_risk, risk)
                self.assertEqual(evaluation.visits[1].wait_minutes, wait)

    def test_no_departure_at_night_or_through_a_night(self):
        problem = exact_problem([city(1), city(2)], [[0, 30], [30, 0]], departure=5 * 60)
        evaluation = schedule_tour(problem, [0, 1, 0])
        self.assertEqual((evaluation.visits[0].rest, evaluation.visits[0].wait_minutes), ("night", 120))
        self.assertEqual(evaluation.visits[1].arrival_minutes, 7 * 60 + 30)
        self.assertEqual(evaluation.visits[1].arrival_risk, 10)
        for leg, rest, arrival in ((780, "long leg", 1440 + 20 * 60), (779, None, 1440 + 7 * 60 - 1)):
            with self.subTest(leg=leg):
                problem = exact_problem([city(1), city(2)], [[0, leg], [leg, 0]], departure=18 * 60)
                evaluation = schedule_tour(problem, [0, 1, 0])
                self.assertEqual(evaluation.visits[0].rest, rest)
                self.assertEqual(evaluation.visits[1].arrival_minutes, arrival)
                self.assertEqual(evaluation.visits[1].arrival_risk, 80)
                assert_no_night_driving(self, evaluation)

    def test_midnight_and_multi_day_travel(self):
        problem = exact_problem([city(1), city(2)], [[0, 3000], [3000, 0]], departure=23 * 60 + 30)
        evaluation = evaluate_tour(problem, [0, 1, 0])
        self.assertEqual([visit.rest for visit in evaluation.visits], ["night", "long leg", None])
        self.assertEqual(format_arrival(evaluation.visits[1].arrival_minutes), "D+3 09:00:00")
        self.assertEqual(format_arrival(evaluation.visits[-1].arrival_minutes), "D+6 09:00:00")
        self.assertEqual(evaluation.total_risk, 10)
        self.assertEqual(evaluation.total_wait_minutes, 450 + 1320)
        self.assertEqual(evaluation.total_time_minutes, 6 * 1440 + 9 * 60 - (23 * 60 + 30))
        self.assertEqual(format_arrival(1440), "D+1 00:00:00")

    def test_optional_rest_trades_time_for_risk(self):
        problem = exact_problem([city(1), city(2)], [[0, 120], [120, 0]], departure=18 * 60, alpha=0)
        rested = evaluate_tour(replace(problem, beta=0.5), [0, 1, 0])
        self.assertEqual((rested.visits[0].rest, rested.visits[0].wait_minutes), ("chosen", 780))
        self.assertEqual(format_arrival(rested.visits[1].arrival_minutes), "D+1 09:00:00")
        self.assertEqual(rested.total_risk, 10)
        hurried = evaluate_tour(replace(problem, beta=1.0), [0, 1, 0])
        self.assertIsNone(hurried.visits[0].rest)
        self.assertEqual(hurried.visits[1].arrival_risk, 80)
        self.assertEqual(hurried.visits[1].rest, "night")
        self.assertEqual(hurried.total_time_minutes, 120 + 660 + 120)
        self.assertLess(hurried.total_time_minutes, rested.total_time_minutes)

    def test_rest_schedule_is_optimal_for_each_tour(self):
        master = load_cities()
        selected = [resolve_city(master, name) for name in
                    ("Kuala Lumpur", "Ipoh", "Johor Bahru", "Kuantan", "Kota Bharu")]
        for departure, alpha, beta in itertools.product((8 * 60, 15 * 60, 18 * 60 + 30), (0.0, 0.4), (0.05, 0.2)):
            problem = make_problem(selected, 1735161, departure, alpha, beta)
            stops = [index for index in range(len(selected)) if index != problem.depot]
            for order in itertools.permutations(stops):
                with self.subTest(departure=departure, alpha=alpha, beta=beta, order=order):
                    tour = (problem.depot, *order, problem.depot)
                    best = min(
                        schedule_tour(problem, tour, rests).cost
                        for size in range(len(stops) + 1)
                        for rests in itertools.combinations(range(len(stops)), size)
                    )
                    self.assertAlmostEqual(evaluate_tour(problem, tour).cost, best, places=12)

    def test_weighted_objective_and_fixed_scales(self):
        cities = [city(1), city(2), city(3)]
        matrix = [[0, 10, 20], [10, 0, 15], [20, 15, 0]]
        for alpha, beta in ((0.0, 0.0), (0.3, 0.2), (1.0, 0.0), (0.0, 1.0)):
            with self.subTest(alpha=alpha, beta=beta):
                problem = exact_problem(cities, matrix, departure=8 * 60, alpha=alpha, beta=beta)
                evaluation = evaluate_tour(problem, [0, 1, 2, 0])
                self.assertEqual(problem.distance_divisor_km, 60)
                self.assertEqual(problem.risk_divisor, 200)
                self.assertEqual(problem.time_divisor_minutes, 3 * (20 + 1440))
                self.assertEqual(evaluation.rest_stops, ())
                self.assertAlmostEqual(evaluation.distance_scaled, 45 / 60)
                self.assertAlmostEqual(evaluation.risk_scaled, 20 / 200)
                self.assertAlmostEqual(evaluation.time_scaled, 45 / 4380)
                self.assertAlmostEqual(evaluation.cost, alpha * 45 / 60 + beta * 45 / 4380
                                       + (1 - alpha - beta) * 20 / 200)

    def test_all_day_all_night_and_equal_scores(self):
        cities = [city(1), city(2), city(3)]
        # Legs over 12 h always arrive at night, even after resting until 07:00.
        for leg, expected in ((1, 20), (800, 160)):
            problem = exact_problem(cities, [[0, leg, leg], [leg, 0, leg], [leg, leg, 0]], departure=8 * 60)
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
        for rests in ([2], [3], [-1], [True]):
            with self.subTest(rests=rests), self.assertRaisesRegex(ValueError, "rest"):
                schedule_tour(problem, [0, 1, 2, 0], rests)

    def test_reject_invalid_instance_parameters(self):
        cities = [city(1), city(2)]
        for alpha in (-0.1, 1.1, math.nan, math.inf):
            with self.subTest(alpha=alpha), self.assertRaisesRegex(ValueError, "alpha"):
                make_problem(cities, 1, alpha=alpha, beta=0.0)
        for alpha, beta in ((0.4, -0.1), (0.4, math.nan), (0.4, math.inf), (0.9, 0.2)):
            with self.subTest(alpha=alpha, beta=beta), self.assertRaisesRegex(ValueError, "beta"):
                make_problem(cities, 1, alpha=alpha, beta=beta)
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
        self.assertEqual(result.generated_states, 2)  # Leave at 08:00, or rest until 07:00.
        self.assertEqual(result.expanded_states, 1)
        self.assertAlmostEqual(result.evaluation.total_distance_km, 2 * problem.distances_km[0][1])

    def test_return_distance_is_included_before_final_pruning(self):
        matrix = [[0, 1, 1, 30], [1, 0, 1, 10], [1, 1, 0, 10], [30, 10, 10, 0]]
        problem = exact_problem([city(index) for index in range(1, 5)], matrix,
                                departure=7 * 60, alpha=1.0)
        # Prefix-only final ranking would choose a 12 km prefix that closes at
        # 42 km. With beta = 0 each prefix has an equal-cost rest twin, hence W = 6.
        result = beam_search(problem, 6)
        self.assertEqual(result.evaluation.tour, (0, 1, 3, 2, 0))
        self.assertEqual(result.evaluation.total_distance_km, 22)
        self.assertAlmostEqual(result.evaluation.cost, 22 / 120)

    def test_wide_beam_matches_exhaustive_optimum(self):
        master = load_cities()
        selected = [resolve_city(master, name) for name in
                    ("Kuala Lumpur", "Ipoh", "Johor Bahru", "Kuantan", "Alor Setar", "Miri")]
        weights = ((0.0, 0.0), (0.4, 0.2), (1.0, 0.0), (0.0, 1.0), (0.5, 0.05))
        for departure, (alpha, beta) in itertools.product((6 * 60 + 30, 18 * 60, 23 * 60 + 45), weights):
            with self.subTest(departure=departure, alpha=alpha, beta=beta):
                problem = make_problem(selected, 1735161, departure, alpha, beta)
                stops = [index for index in range(len(selected)) if index != problem.depot]
                optimum = min(
                    evaluate_tour(problem, (problem.depot, *order, problem.depot)).cost
                    for order in itertools.permutations(stops)
                )
                # Wide enough to keep every (order, rest choice) prefix.
                result = beam_search(problem, math.factorial(len(stops)) * 2 ** len(stops))
                self.assertAlmostEqual(result.evaluation.cost, optimum, places=12)

    def test_no_state_merging_when_visited_set_and_current_city_match(self):
        # An unpruned four-stop tree generates 4 + 12 + 24 + 24 states; coincident
        # cities keep the clock at 07:00, so no rest branches appear.
        # Deduplicating by (visited, current) would remove distinct prefixes.
        problem = make_problem([city(index) for index in range(1, 6)], 1, departure_minutes=7 * 60)
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
        assert_no_night_driving(self, evaluation)
        self.assertLessEqual(result.peak_beam_size, 10)
        self.assertGreaterEqual(evaluation.cost, 0)
        self.assertLessEqual(evaluation.cost, 1)
        payload = result_as_dict(problem, result)
        self.assertEqual(len(payload["instance"]["selected_geonameids"]), 43)
        self.assertIsNone(payload["route"][-1]["arrival_risk"])
        self.assertEqual(payload["objective"]["cost"], evaluation.cost)


if __name__ == "__main__":
    unittest.main()
