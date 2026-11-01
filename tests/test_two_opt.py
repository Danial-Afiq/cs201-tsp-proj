"""2-opt search checks; run: python3 -m unittest discover -s tests -v."""

import contextlib
import io
import itertools
import json
import math
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from beam_search import beam_search, evaluate_tour, load_cities, make_problem, resolve_city
from beam_search import result_as_dict as beam_result_as_dict
from test_beam_search import assert_no_night_driving, city, exact_problem
from two_opt import (
    IMPROVEMENT_TOLERANCE, id_order_tour, main, nearest_neighbor_tour, result_as_dict,
    reverse_segment, two_opt,
)


KUALA_LUMPUR = 1735161
# Kuching adds cross-sea legs, so long-leg rests and night arrivals are exercised too.
CITY_SUBSET = ("Kuala Lumpur", "Ipoh", "Johor Bahru", "Kuantan", "Alor Setar", "Malacca", "Kuching")
DEPARTURES = (6 * 60 + 30, 18 * 60, 23 * 60 + 45)
WEIGHTS = ((0.0, 0.0), (0.4, 0.2), (1.0, 0.0), (0.0, 1.0), (0.5, 0.05))


def real_problem(departure=18 * 60, alpha=0.4, beta=0.2, names=CITY_SUBSET):
    master = load_cities()
    return make_problem([resolve_city(master, name) for name in names], KUALA_LUMPUR, departure, alpha, beta)


def reversals(route):
    """Independently enumerate every segment reversal of a closed tour's stops."""
    for first, last in itertools.combinations(range(1, len(route) - 1), 2):
        yield (*route[:first], *route[first:last + 1][::-1], *route[last + 1:])


def reference_search(problem, strategy, start):
    """Plain restatement of each improvement rule, to check tour and move count."""
    current, improvements = evaluate_tour(problem, start), 0
    while True:
        neighbours = [evaluate_tour(problem, route) for route in reversals(current.tour)]
        improving = [item for item in neighbours if item.cost < current.cost - IMPROVEMENT_TOLERANCE]
        if not improving:
            return current.tour, improvements
        current = improving[0] if strategy == "first" else min(improving, key=lambda item: item.cost)
        improvements += 1


class InitialTourTests(unittest.TestCase):
    def test_nearest_neighbor_follows_shortest_legs_and_breaks_ties_by_id(self):
        matrix = [[0, 9, 2, 5], [9, 0, 4, 1], [2, 4, 0, 3], [5, 1, 3, 0]]
        problem = exact_problem([city(index) for index in (1, 2, 3, 4)], matrix)
        self.assertEqual(nearest_neighbor_tour(problem), (0, 2, 3, 1, 0))
        ties = make_problem([city(index) for index in (3, 1, 2)], 2)
        self.assertEqual(nearest_neighbor_tour(ties), (1, 0, 2, 1))

    def test_starts_are_valid_tours_from_a_non_first_depot(self):
        problem = make_problem(load_cities(), KUALA_LUMPUR)
        self.assertNotEqual(problem.depot, 0)
        for tour in (nearest_neighbor_tour(problem), id_order_tour(problem)):
            self.assertEqual(evaluate_tour(problem, tour).tour, tour)
            self.assertEqual(tour[0], problem.depot)


class ReverseSegmentTests(unittest.TestCase):
    def test_reverses_inclusive_positions_and_keeps_the_depots(self):
        route = (0, 1, 2, 3, 4, 0)
        self.assertEqual(reverse_segment(route, 1, 2), (0, 2, 1, 3, 4, 0))
        self.assertEqual(reverse_segment(route, 2, 4), (0, 1, 4, 3, 2, 0))
        self.assertEqual(reverse_segment(route, 1, 4), (0, 4, 3, 2, 1, 0))
        self.assertEqual(route, (0, 1, 2, 3, 4, 0))


class MoveAcceptanceTests(unittest.TestCase):
    def test_two_city_instance_has_no_moves(self):
        problem = make_problem([city(1), city(2, longitude=1)], 1)
        result = two_opt(problem)
        self.assertEqual(result.evaluation.tour, (0, 1, 0))
        self.assertEqual((result.improvements, result.evaluated_moves), (0, 0))

    def test_distance_only_weights_uncross_a_square(self):
        side, diagonal = 1, math.sqrt(2)
        matrix = [[0, side, diagonal, side], [side, 0, side, diagonal],
                  [diagonal, side, 0, side], [side, diagonal, side, 0]]
        problem = exact_problem([city(index) for index in (1, 2, 3, 4)], matrix, alpha=1.0)
        result = two_opt(problem, initial_tour=(0, 2, 1, 3, 0))
        self.assertAlmostEqual(result.initial_evaluation.total_distance_km, 2 + 2 * diagonal)
        self.assertEqual(result.evaluation.tour, (0, 1, 2, 3, 0))
        self.assertEqual(result.evaluation.total_distance_km, 4)

    def test_reversing_all_stops_is_used_despite_equal_distance(self):
        # Distance-only 2-opt treats this as a no-op because the same edges remain.
        # Forwards, 18:30 + 2 km ends with the long leg as the unscored return.
        # Backwards, that leg is scored, so the driver rests at the depot to arrive by day.
        matrix = [[0, 1, 600], [1, 0, 1], [600, 1, 0]]
        problem = exact_problem([city(1), city(2), city(3)], matrix, departure=18 * 60 + 30, alpha=0.3, beta=0.2)
        result = two_opt(problem, initial_tour=(0, 2, 1, 0))
        start, final = result.initial_evaluation, result.evaluation
        self.assertEqual(final.tour, (0, 1, 2, 0))
        self.assertEqual(final.total_distance_km, start.total_distance_km)
        self.assertEqual(result.improvements, 1)
        self.assertEqual(start.rest_stops, (0,))
        self.assertEqual(final.rest_stops, ())
        self.assertEqual((start.total_time_minutes, final.total_time_minutes), (1352, 602))

    def test_move_is_accepted_for_a_change_beyond_the_reversed_segment(self):
        # Only stop 3 has period-dependent risk, and reversing positions 1..2 leaves
        # it in place. The shorter prefix still moves its arrival from 19:05 to
        # 18:25, which also removes the night rest before the return.
        cities = [city(1), city(2, day_risk=25, night_risk=25),
                  city(3, day_risk=25, night_risk=25), city(4, day_risk=10, night_risk=80)]
        matrix = [[0, 40, 10, 15], [40, 0, 5, 10], [10, 5, 0, 20], [15, 10, 20, 0]]
        # Time dominates, so the start does not take an optional rest to dodge the night.
        problem = exact_problem(cities, matrix, alpha=0.0, beta=0.99)
        result = two_opt(problem, initial_tour=(0, 1, 2, 3, 0))
        start, final = result.initial_evaluation, result.evaluation
        self.assertEqual(final.tour, (0, 2, 1, 3, 0))
        self.assertEqual(result.improvements, 1)
        self.assertEqual((start.visits[3].city, final.visits[3].city), (cities[3], cities[3]))
        self.assertEqual(start.visits[3].arrival_minutes, 18 * 60 + 65)
        self.assertEqual(final.visits[3].arrival_minutes, 18 * 60 + 25)
        self.assertEqual((start.total_risk, final.total_risk), (25 + 25 + 80, 25 + 25 + 10))
        self.assertEqual((start.visits[3].rest, final.visits[3].rest), ("night", None))

    def test_candidates_are_scored_with_their_own_cheapest_rests(self):
        # Rest choices are per tour: the swap only helps once rests become too dear.
        cities = [city(1), city(2), city(3, day_risk=0, night_risk=100)]
        matrix = [[0, 120, 120], [120, 0, 120], [120, 120, 0]]
        start = (0, 2, 1, 0)
        problem = exact_problem(cities, matrix, departure=17 * 60, alpha=0.0, beta=0.5)
        patient = two_opt(problem, initial_tour=start)
        self.assertEqual(patient.evaluation.tour, start)
        self.assertEqual(patient.improvements, 0)
        self.assertEqual(patient.evaluation.rest_stops, (0,))
        self.assertEqual(patient.evaluation.total_risk, 10)
        hurried = two_opt(replace(problem, beta=0.95), initial_tour=start)
        self.assertEqual(hurried.evaluation.tour, (0, 1, 2, 0))
        self.assertEqual(hurried.improvements, 1)
        self.assertEqual(hurried.evaluation.total_risk, 80)
        self.assertEqual(hurried.evaluation.total_time_minutes, 1080)

    def test_accepts_a_longer_route_only_when_the_weights_allow_it(self):
        # The 80 km start reaches its last stop at 19:10 in either direction, so it
        # needs a night's rest. The 150 km alternative is there by 18:50 and returns
        # without one, trading 70 km for about 12 hours.
        cities = [city(1), city(2, day_risk=50, night_risk=50),
                  city(3, day_risk=50, night_risk=50), city(4, day_risk=0, night_risk=100)]
        matrix = [[0, 10, 100, 10], [10, 0, 50, 30], [100, 50, 0, 10], [10, 30, 10, 0]]
        problem = exact_problem(cities, matrix)
        start = (0, 1, 2, 3, 0)
        distance_only = two_opt(replace(problem, alpha=1.0, beta=0.0), initial_tour=start).evaluation
        self.assertEqual(distance_only.tour, start)
        self.assertEqual(distance_only.total_distance_km, 80)
        weighted = two_opt(replace(problem, alpha=0.0, beta=0.5), initial_tour=start).evaluation
        self.assertEqual(weighted.tour, (0, 1, 3, 2, 0))
        self.assertEqual(weighted.total_distance_km, 150)
        self.assertEqual(weighted.total_wait_minutes, 0)
        self.assertEqual(weighted.total_risk, 100)


class SearchPropertyTests(unittest.TestCase):
    def test_result_is_a_local_optimum_never_worse_than_its_start(self):
        for strategy, starter, departure, (alpha, beta) in itertools.product(
            ("best", "first"), (nearest_neighbor_tour, id_order_tour), DEPARTURES, WEIGHTS,
        ):
            with self.subTest(strategy=strategy, starter=starter.__name__, departure=departure,
                              alpha=alpha, beta=beta):
                problem = real_problem(departure, alpha, beta)
                result = two_opt(problem, strategy, starter(problem))
                self.assertLessEqual(result.evaluation.cost, result.initial_evaluation.cost)
                for neighbour in reversals(result.evaluation.tour):
                    self.assertGreaterEqual(evaluate_tour(problem, neighbour).cost,
                                            result.evaluation.cost - IMPROVEMENT_TOLERANCE)

    def test_strategies_match_a_plain_reference_search(self):
        for strategy, departure, (alpha, beta) in itertools.product(("best", "first"), DEPARTURES, WEIGHTS):
            with self.subTest(strategy=strategy, departure=departure, alpha=alpha, beta=beta):
                problem = real_problem(departure, alpha, beta)
                start = id_order_tour(problem)
                result = two_opt(problem, strategy, start)
                self.assertEqual((result.evaluation.tour, result.improvements),
                                 reference_search(problem, strategy, start))

    def test_never_beats_the_exhaustive_optimum(self):
        for departure, (alpha, beta) in itertools.product(DEPARTURES, WEIGHTS):
            with self.subTest(departure=departure, alpha=alpha, beta=beta):
                problem = real_problem(departure, alpha, beta)
                stops = [index for index in range(len(problem.cities)) if index != problem.depot]
                optimum = min(
                    evaluate_tour(problem, (problem.depot, *order, problem.depot)).cost
                    for order in itertools.permutations(stops)
                )
                self.assertGreaterEqual(two_opt(problem).evaluation.cost, optimum - IMPROVEMENT_TOLERANCE)

    def test_deterministic_regardless_of_input_city_order(self):
        cities = [city(index, longitude=index * index % 7) for index in (5, 3, 1, 4, 2, 6)]
        first = two_opt(make_problem(cities, 1))
        second = two_opt(make_problem(list(reversed(cities)), 1))
        self.assertEqual(first.evaluation, second.evaluation)
        self.assertEqual(first.evaluated_moves, second.evaluated_moves)

    def test_equal_cost_tours_stop_without_cycling(self):
        problem = make_problem([city(index) for index in range(1, 6)], 1)
        result = two_opt(problem)
        self.assertEqual(result.improvements, 0)
        self.assertEqual(result.evaluation, result.initial_evaluation)
        self.assertEqual(result.evaluated_moves, 3 + 2 + 1)

    def test_equal_day_night_scores_and_all_night_arrivals(self):
        # Equal scores leave only distance and time to optimise.
        equal = [city(index, longitude=index, day_risk=25, night_risk=25) for index in range(1, 6)]
        result = two_opt(make_problem(equal, 1, departure_minutes=20 * 60))
        self.assertEqual(result.evaluation.total_risk, 25 * 4)
        # Every 800 km leg is over 12 h, so all arrivals are at night whatever the order.
        cities = [city(index) for index in range(1, 5)]
        matrix = [[0 if row == column else 800 for column in range(4)] for row in range(4)]
        result = two_opt(exact_problem(cities, matrix, departure=8 * 60))
        self.assertEqual(result.evaluation.total_risk, 80 * 3)
        self.assertEqual(result.improvements, 0)

    def test_reject_invalid_strategy_and_initial_tours(self):
        problem = make_problem([city(1), city(2), city(3)], 1)
        for strategy in ("random", "", None):
            with self.subTest(strategy=strategy), self.assertRaisesRegex(ValueError, "strategy"):
                two_opt(problem, strategy)
        for route in ([], [0, 1, 0], [0, 1, 1, 0], [1, 0, 2, 1], [0, 1, 3, 0], [0, True, 2, 0]):
            with self.subTest(route=route), self.assertRaisesRegex(ValueError, "tour must"):
                two_opt(problem, initial_tour=route)

    def test_does_not_alter_the_initial_tour_or_source_data(self):
        problem = real_problem()
        start = list(id_order_tour(problem))
        original_start, original_cities = list(start), tuple(asdict(item) for item in problem.cities)
        result = two_opt(problem, initial_tour=start)
        self.assertEqual(start, original_start)
        self.assertEqual(result.initial_evaluation.tour, tuple(original_start))
        self.assertEqual(tuple(asdict(item) for item in problem.cities), original_cities)


class SharedInstanceTests(unittest.TestCase):
    def test_both_algorithms_are_scored_identically_on_one_instance(self):
        problem = real_problem()
        for evaluation in (two_opt(problem).evaluation, beam_search(problem, 50).evaluation):
            self.assertEqual(evaluate_tour(problem, evaluation.tour), evaluation)

    def test_starting_from_a_beam_tour_never_worsens_it(self):
        for departure, (alpha, beta) in itertools.product(DEPARTURES, WEIGHTS):
            with self.subTest(departure=departure, alpha=alpha, beta=beta):
                problem = real_problem(departure, alpha, beta)
                beam = beam_search(problem, 5).evaluation
                result = two_opt(problem, initial_tour=beam.tour)
                self.assertEqual(result.initial_evaluation, beam)
                self.assertLessEqual(result.evaluation.cost, beam.cost)

    def test_export_shares_its_instance_objective_and_route_sections_with_beam_search(self):
        problem = real_problem()
        tour = beam_search(problem, 5).evaluation.tour
        mine = result_as_dict(problem, two_opt(problem, initial_tour=tour))
        beam = beam_result_as_dict(problem, beam_search(problem, 5))
        self.assertEqual(mine["algorithm"], "Safety-Aware 2-opt")
        self.assertEqual(mine["instance"], beam["instance"])
        self.assertEqual(mine["implementation_version"], beam["implementation_version"])
        self.assertEqual(set(mine["objective"]), set(beam["objective"]))
        self.assertEqual(set(mine["route"][0]), set(beam["route"][0]))
        self.assertNotIn("beam_width", mine["search"])

    def test_full_master_produces_valid_tour_and_export(self):
        problem = make_problem(load_cities(), KUALA_LUMPUR, departure_minutes=18 * 60)
        result = two_opt(problem)
        self.assertEqual(evaluate_tour(problem, result.evaluation.tour), result.evaluation)
        self.assertEqual(len(result.evaluation.tour), 44)
        assert_no_night_driving(self, result.evaluation)
        self.assertLessEqual(result.evaluation.cost, result.initial_evaluation.cost)
        self.assertGreaterEqual(result.evaluation.cost, 0)
        self.assertLessEqual(result.evaluation.cost, 1)
        payload = result_as_dict(problem, result)
        self.assertEqual(len(payload["instance"]["selected_geonameids"]), 43)
        self.assertIsNone(payload["route"][-1]["arrival_risk"])
        self.assertEqual(payload["objective"]["cost"], result.evaluation.cost)
        self.assertEqual(payload["search"]["initial_cost"], result.initial_evaluation.cost)

    def test_command_line_writes_reproducible_json(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "result.json"
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                code = main(["--depot", "Kuala Lumpur", "--cities", "Ipoh", "Kuantan", "Malacca",
                             "--departure", "18:00", "--alpha", "0.3", "--beta", "0.3",
                             "--strategy", "first", "--initial", "id-order", "--output", str(output)])
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertIn("Safety-Aware 2-opt", printed.getvalue())
        self.assertEqual(payload["search"]["strategy"], "first")
        ids = payload["search"]["initial_route_geonameids"]  # --initial id-order was honoured.
        self.assertEqual(ids[1:-1], sorted(ids[1:-1]))
        self.assertEqual((ids[0], ids[-1]), (KUALA_LUMPUR, KUALA_LUMPUR))
        self.assertEqual(payload["objective"]["beta"], 0.3)
        self.assertEqual(len(payload["dataset"]["sha256"]), 64)
        self.assertEqual(len(payload["route"]), 5)

    def test_command_line_rejects_invalid_input(self):
        for arguments in (["--alpha", "0.9", "--beta", "0.2"], ["--depot", "missing city"],
                          ["--strategy", "random"], ["--initial", "random"], ["--departure", "24:00"]):
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    main(arguments)
                self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
