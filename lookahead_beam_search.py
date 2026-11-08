"""Safety-Aware Beam Search with greedy-completion lookahead.

Plain beam search (``beam_search.py``) ranks each partial route by the cost it
has accumulated so far, so it cannot see that a cheap prefix may push risky
cities into the night later. This variant ranks every candidate prefix by the
cost of the closed tour obtained by *finishing it greedily*: from the prefix's
last city and current clock, repeatedly move to the unvisited city with the
cheapest extension (next city, leaving now or after an overnight rest, under
the weighted distance/time/risk cost), then return to the depot. This is the "filtered" / global-evaluation
idea from Ow & Morton (1989) and Valente & Alves (2004), adapted to our model.

Everything except the ranking rule is shared with ``beam_search.py``: the same
problem instance, scaling, state record, tie-breaking and ``evaluate_tour()``.

Run ``python3 lookahead_beam_search.py --help`` for command-line options.
"""

from __future__ import annotations

import argparse
import csv
import heapq
import itertools
import time
from typing import Iterator, Sequence

from beam_search import (
    DEFAULT_DATA, BeamSearchResult, RoutingProblem, _State, _closed_totals, _extensions,
    _initial_state, evaluate_tour, format_arrival, format_duration, is_day, load_cities,
    make_problem, parse_departure, resolve_city, select_cities,
)


def greedy_completion(
    problem: RoutingProblem, state: _State | None = None,
) -> tuple[float, float, tuple[int, ...]]:
    """Finish a prefix greedily; return (closed-tour cost, elapsed minutes, appended cities).

    At each step take the extension (next city, leaving now or after an
    overnight rest) with the smallest weighted cost
    ``alpha * D / D_div + beta * T / T_div + (1 - alpha - beta) * R / R_div``
    of the extended prefix, using the true clock on this greedy path. Ties
    prefer less elapsed time, then the lowest city index, then leaving now.
    The return leg adds distance and time, including any mandatory rest, but
    no arrival risk. ``state=None`` starts at the depot.
    """
    if state is None:
        state = _initial_state(problem)
    full = (1 << len(problem.cities)) - 1
    order: list[int] = []
    while state.visited != full:
        best: tuple[float, float] | None = None
        for child in _extensions(problem, state):
            key = (problem.cost(child.distance_km, child.risk, child.elapsed_minutes),
                   child.elapsed_minutes)
            if best is None or key < best:
                best, chosen = key, child
        state = chosen
        order.append(state.current)
    distance, elapsed = _closed_totals(problem, state)
    return problem.cost(distance, state.risk, elapsed), elapsed, tuple(order)


def lookahead_beam_search(problem: RoutingProblem, beam_width: int = 20) -> BeamSearchResult:
    """Keep the globally best W partial tours per depth, ranked by greedy completion.

    Identical to ``beam_search()`` except for the ranking key. At the last
    depth the greedy completion is just the return leg, so the final beam is
    ordered by exact closed-tour cost (for the beam's own rest choices), as in
    the plain version. The winner is re-evaluated with its cheapest rests.
    """
    if type(beam_width) is not int or beam_width < 1:
        raise ValueError("beam_width must be a positive integer")
    started = time.perf_counter()
    size = len(problem.cities)
    beam = [_initial_state(problem)]
    serial = itertools.count()
    expanded = generated = 0
    peak = 1

    def candidates(frontier: list[_State]) -> Iterator[tuple[float, float, int, _State]]:
        nonlocal generated
        for state in frontier:
            for child in _extensions(problem, state):
                rank, elapsed, _ = greedy_completion(problem, child)
                generated += 1
                yield rank, elapsed, next(serial), child

    for _depth in range(1, size):
        expanded += len(beam)
        kept = heapq.nsmallest(beam_width, candidates(beam))
        beam = [entry[3] for entry in kept]
        peak = max(peak, len(beam))

    route: list[int] = []
    node: _State | None = beam[0]
    while node is not None:
        route.append(node.current)
        node = node.parent
    route.reverse()
    route.append(problem.depot)
    evaluation = evaluate_tour(problem, route)
    return BeamSearchResult(
        evaluation=evaluation, beam_width=beam_width, expanded_states=expanded,
        generated_states=generated, peak_beam_size=peak,
        runtime_seconds=time.perf_counter() - started,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", default=DEFAULT_DATA, help="master CSV (default: bundled cleaned data)")
    parser.add_argument("--depot", default="1735161", help="depot name or GeoNameID (default: Kuala Lumpur)")
    parser.add_argument("--cities", nargs="+", help="selected city names/IDs; depot is included automatically")
    parser.add_argument("--departure", type=parse_departure, default=8 * 60.0, help="local HH:MM (default: 08:00)")
    parser.add_argument("--alpha", type=float, default=0.4, help="distance weight in [0, 1] (default: 0.4)")
    parser.add_argument("--beta", type=float, default=0.2,
                        help="elapsed-time weight; risk gets 1 - alpha - beta (default: 0.2)")
    parser.add_argument("--beam-width", type=int, default=20, help="retained states per depth (default: 20)")
    args = parser.parse_args(argv)
    try:
        cities = load_cities(args.data)
        depot = resolve_city(cities, args.depot)
        problem = make_problem(select_cities(cities, depot, args.cities), depot.geonameid, args.departure,
                               args.alpha, args.beta)
        result = lookahead_beam_search(problem, args.beam_width)
    except (ValueError, OSError, csv.Error) as exc:
        parser.error(str(exc))
    evaluation = result.evaluation
    print(f"Lookahead Beam Search | cities={len(problem.cities)} | beam width={result.beam_width}")
    print(f"Distance: {evaluation.total_distance_km:.3f} km | time: {format_duration(evaluation.total_time_minutes)} h"
          f" | risk: {evaluation.total_risk:.2f} | cost: {evaluation.cost:.6f}")
    print(f"Search: {result.expanded_states} expanded, {result.generated_states} generated, {result.runtime_seconds:.6f} s")
    for index, visit in enumerate(evaluation.visits):
        period = "day" if is_day(visit.arrival_minutes) else "night"
        line = f"{index:>4}  {visit.city.name:<24} {format_arrival(visit.arrival_minutes):<16} {period}"
        if visit.rest is not None:
            line = f"{line}  rest {format_duration(visit.wait_minutes)} h ({visit.rest})"
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
