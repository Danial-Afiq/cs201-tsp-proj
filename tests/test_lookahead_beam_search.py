"""Checks for the greedy-completion lookahead variant; run: python3 -m unittest discover -s tests -v."""

import itertools
import math
import random
import unittest

from beam_search import (
    _extensions, _initial_state, beam_search, evaluate_tour, load_cities, make_problem,
    resolve_city, schedule_tour,
)
from lookahead_beam_search import greedy_completion, lookahead_beam_search
from tests.test_beam_search import city, exact_problem


def brute_force(problem):
    stops = [index for index in range(len(problem.cities)) if index != problem.depot]
    return min(evaluate_tour(problem, (problem.depot, *order, problem.depot)).cost
               for order in itertools.permutations(stops))


class GreedyCompletionTests(unittest.TestCase):
    def test_hand_computed_completion_with_rest(self):
        # Depart 18:45; alpha=0.5, beta=0, D_div=60, R_div=200. City 2 (index 1)
        # is reached by day at 18:55 (risk 10). Driving on would reach city 3 at
        # 19:10 (night, risk 80); resting until 07:00 reaches it at 07:15 (risk
        # 10) for free, so greedy rests, then returns: 45 km, risk 20.
        cities = [city(1), city(2, day_risk=10, night_risk=80), city(3, day_risk=10, night_risk=80)]
        problem = exact_problem(cities, [[0, 10, 20], [10, 0, 15], [20, 15, 0]], departure=18 * 60 + 45)
        cost, _, order = greedy_completion(problem)
        self.assertEqual(order, (1, 2))
        self.assertAlmostEqual(cost, 0.5 * 45 / 60 + 0.5 * 20 / 200)
        self.assertAlmostEqual(cost, evaluate_tour(problem, [0, 1, 2, 0]).cost)

    def test_completion_of_full_prefix_is_return_leg_only(self):
        problem = exact_problem([city(1), city(2), city(3)], [[0, 10, 20], [10, 0, 15], [20, 15, 0]],
                                departure=8 * 60, alpha=0.4, beta=0.2)
        state = _initial_state(problem)
        for following in (1, 2):  # Leave at once each time (first extension).
            state = next(child for child in _extensions(problem, state) if child.current == following)
        cost, elapsed, order = greedy_completion(problem, state)
        tour = schedule_tour(problem, [0, 1, 2, 0])
        self.assertEqual(order, ())
        self.assertAlmostEqual(cost, tour.cost)
        self.assertAlmostEqual(elapsed, tour.total_time_minutes)


class LookaheadBeamSearchTests(unittest.TestCase):
    def test_two_city_instance(self):
        problem = make_problem([city(1), city(2, longitude=1)], 1)
        result = lookahead_beam_search(problem, 1)
        self.assertEqual(result.evaluation.tour, (0, 1, 0))
        self.assertEqual(result.generated_states, 2)  # Leave at 08:00, or rest until 07:00.

    def test_result_is_freshly_evaluated_valid_tour(self):
        master = load_cities()
        problem = make_problem(master[:20], master[0].geonameid, departure_minutes=18 * 60)
        result = lookahead_beam_search(problem, 3)
        self.assertEqual(evaluate_tour(problem, result.evaluation.tour), result.evaluation)
        self.assertEqual(len(result.evaluation.tour), 21)
        self.assertLessEqual(result.peak_beam_size, 3)

    def test_never_worse_than_greedy_completion_from_depot(self):
        # The greedy continuation of the best-ranked state is always a candidate
        # with the same rank, so the best rank never rises; at the last depth
        # rank equals the cost of the beam's own rests, and the final
        # re-evaluation can only lower it. Hence any W is at least as good as greedy.
        rng = random.Random(7)
        master = load_cities()
        for trial in range(30):
            chosen = rng.sample(master, 7)
            alpha = rng.uniform(0, 0.8)
            problem = make_problem(chosen, chosen[0].geonameid, rng.choice((360, 600, 1080)),
                                   alpha, rng.uniform(0, 1 - alpha))
            greedy, _, _ = greedy_completion(problem)
            for width in (1, 5):
                with self.subTest(trial=trial, width=width):
                    self.assertLessEqual(lookahead_beam_search(problem, width).evaluation.cost, greedy + 1e-12)

    def test_wide_beam_matches_exhaustive_optimum(self):
        master = load_cities()
        selected = [resolve_city(master, name) for name in
                    ("Kuala Lumpur", "Ipoh", "Johor Bahru", "Kuantan", "Alor Setar", "Malacca")]
        stops = len(selected) - 1
        weights = ((0.0, 0.0), (0.4, 0.2), (1.0, 0.0))
        for departure, (alpha, beta) in itertools.product((6 * 60 + 30, 18 * 60, 23 * 60 + 45), weights):
            with self.subTest(departure=departure, alpha=alpha, beta=beta):
                problem = make_problem(selected, 1735161, departure, alpha, beta)
                # Wide enough to keep every (order, rest choice) prefix.
                result = lookahead_beam_search(problem, math.factorial(stops) * 2 ** stops)
                self.assertAlmostEqual(result.evaluation.cost, brute_force(problem), places=12)

    def test_lookahead_fixes_myopic_night_arrival(self):
        # Depart 18:45. Plain W=1 takes the slightly cheaper 10 km hop to city 2
        # first; city 3 (night risk 100) can then only be reached at night or
        # after resting until 07:00. Lookahead sees this and visits city 3 at
        # 18:57 while it is still day. Every order drives 32 km.
        cities = [city(1), city(2, day_risk=10, night_risk=10), city(3, day_risk=0, night_risk=100)]
        problem = exact_problem(cities, [[0, 10, 12], [10, 0, 10], [12, 10, 0]],
                                departure=18 * 60 + 45, alpha=0.4, beta=0.2)
        plain = beam_search(problem, 1).evaluation
        self.assertEqual(plain.tour, (0, 1, 2, 0))
        self.assertEqual(plain.visits[1].rest, "chosen")
        lookahead = lookahead_beam_search(problem, 1).evaluation
        self.assertEqual(lookahead.tour, (0, 2, 1, 0))
        self.assertEqual(lookahead.visits[1].arrival_risk, 0)
        self.assertAlmostEqual(lookahead.cost, brute_force(problem))
        self.assertLess(lookahead.cost, plain.cost)

    def test_deterministic_ties(self):
        cities = [city(index) for index in (4, 2, 3, 1)]
        first = lookahead_beam_search(make_problem(cities, 1), 2)
        second = lookahead_beam_search(make_problem(list(reversed(cities)), 1), 2)
        self.assertEqual(first.evaluation, second.evaluation)
        self.assertEqual(first.evaluation.tour, (0, 1, 2, 3, 0))

    def test_reject_invalid_beam_widths(self):
        problem = make_problem([city(1), city(2)], 1)
        for width in (0, -1, 1.5, True):
            with self.subTest(width=width), self.assertRaisesRegex(ValueError, "positive integer"):
                lookahead_beam_search(problem, width)


if __name__ == "__main__":
    unittest.main()
