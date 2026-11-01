"""Safety-aware day/night TSP solved by 2-opt local search over complete tours.

Run ``python3 two_opt.py --help`` for command-line options. The data loader,
problem instance, scaling and evaluate_tour() come from beam_search.py so both
approaches are scored by exactly the same model and objective.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from beam_search import (
    DEFAULT_DATA, BeamSearchResult, RoutingProblem, TourEvaluation, evaluate_tour,
    format_arrival, format_duration, is_day, load_cities, make_problem, parse_departure,
    resolve_city, select_cities,
)
from beam_search import result_as_dict as _shared_result_as_dict


# Scaled costs lie in [0, 1]. A move must beat this margin, so rounding noise
# cannot cycle between equal-cost tours and every accepted move strictly improves.
IMPROVEMENT_TOLERANCE = 1e-12
STRATEGIES = ("best", "first")
INITIAL_TOURS = ("nearest-neighbor", "id-order")


def nearest_neighbor_tour(problem: RoutingProblem) -> tuple[int, ...]:
    """Distance-only greedy start; equal distances pick the lowest GeoNameID."""
    route = [problem.depot]
    remaining = [index for index in range(len(problem.cities)) if index != problem.depot]
    while remaining:
        row = problem.distances_km[route[-1]]
        following = min(remaining, key=row.__getitem__)
        remaining.remove(following)
        route.append(following)
    route.append(problem.depot)
    return tuple(route)


def id_order_tour(problem: RoutingProblem) -> tuple[int, ...]:
    """Uninformed start: stops in ascending GeoNameID order."""
    stops = (index for index in range(len(problem.cities)) if index != problem.depot)
    return (problem.depot, *stops, problem.depot)


def reverse_segment(route: Sequence[int], first: int, last: int) -> tuple[int, ...]:
    """Copy of route with tour positions first..last (inclusive) reversed."""
    return (*route[:first], *reversed(route[first:last + 1]), *route[last + 1:])


@dataclass(frozen=True, slots=True)
class TwoOptResult:
    evaluation: TourEvaluation
    initial_evaluation: TourEvaluation
    strategy: str
    improvements: int  # Accepted reversals.
    evaluated_moves: int  # Candidate reversals costed, across all scans.
    runtime_seconds: float  # Search + final evaluation, excluding CSV/matrix setup.


def two_opt(
    problem: RoutingProblem, strategy: str = "best", initial_tour: Sequence[int] | None = None,
) -> TwoOptResult:
    """Reverse stop segments until no single reversal lowers the shared cost.

    "best" applies the cheapest reversal of a full scan; "first" applies the
    first improving one and rescans. Scans run in ascending (first, last) order,
    so ties resolve deterministically to the earliest move. Every candidate goes
    through evaluate_tour(): a reversal can shift arrivals and rests beyond its
    segment, so there is no constant-time edge delta as in distance-only 2-opt.
    Reversing all stops is a real candidate because it keeps the distance but
    changes every arrival time. The result is a local optimum with no global
    optimality guarantee.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"strategy must be one of {', '.join(STRATEGIES)}")
    started = time.perf_counter()
    start = nearest_neighbor_tour(problem) if initial_tour is None else initial_tour
    initial_evaluation = evaluate_tour(problem, start)  # Also rejects invalid tours.
    current = initial_evaluation
    stop_end = len(current.tour) - 1  # The closing depot's position; the depots never move.
    improvements = evaluated = 0

    while True:
        best = None
        best_cost = current.cost - IMPROVEMENT_TOLERANCE
        for first in range(1, stop_end - 1):
            for last in range(first + 1, stop_end):
                candidate = evaluate_tour(problem, reverse_segment(current.tour, first, last))
                evaluated += 1
                if candidate.cost < best_cost:
                    best, best_cost = candidate, candidate.cost
                    if strategy == "first":
                        break
            if best is not None and strategy == "first":
                break
        if best is None:
            break
        current = best
        improvements += 1

    return TwoOptResult(
        evaluation=current, initial_evaluation=initial_evaluation, strategy=strategy,
        improvements=improvements, evaluated_moves=evaluated,
        runtime_seconds=time.perf_counter() - started,
    )


def result_as_dict(problem: RoutingProblem, result: TwoOptResult) -> dict:
    """Export the instance, objective, route and search statistics for experiments."""
    # The instance, objective and route sections come from the Beam Search
    # exporter, so runs of both algorithms always record the same metadata.
    payload = _shared_result_as_dict(
        problem, BeamSearchResult(result.evaluation, 0, 0, 0, 0, result.runtime_seconds))
    initial = result.initial_evaluation
    payload["algorithm"] = "Safety-Aware 2-opt"
    payload["search"] = {
        "strategy": result.strategy, "improvements": result.improvements,
        "evaluated_moves": result.evaluated_moves, "runtime_seconds": result.runtime_seconds,
        "initial_route_geonameids": [problem.cities[index].geonameid for index in initial.tour],
        "initial_total_distance_km": initial.total_distance_km,
        "initial_total_risk": initial.total_risk,
        "initial_total_time_minutes": initial.total_time_minutes,
        "initial_cost": initial.cost,
        "stopping_rule": f"no reversal improves cost by more than {IMPROVEMENT_TOLERANCE:g}",
        "tie_breaking": "earliest (first, last) stop positions in scan order",
    }
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="master CSV (default: bundled cleaned data)")
    parser.add_argument("--depot", default="1735161", help="depot name or GeoNameID (default: Kuala Lumpur)")
    parser.add_argument("--cities", nargs="+", help="selected city names/IDs; depot is included automatically (default: all)")
    parser.add_argument("--departure", type=parse_departure, default=8 * 60.0, help="local HH:MM (default: 08:00)")
    parser.add_argument("--alpha", type=float, default=0.4, help="distance weight in [0, 1] (default: 0.4)")
    parser.add_argument("--beta", type=float, default=0.2,
                        help="elapsed-time weight; risk gets 1 - alpha - beta (default: 0.2)")
    parser.add_argument("--strategy", choices=STRATEGIES, default="best", help="improvement rule (default: best)")
    parser.add_argument("--initial", choices=INITIAL_TOURS, default="nearest-neighbor",
                        help="starting tour (default: nearest-neighbor)")
    parser.add_argument("--output", type=Path, help="also save route and reproducibility metadata as JSON")
    args = parser.parse_args(argv)
    try:
        cities = load_cities(args.data)
        depot = resolve_city(cities, args.depot)
        problem = make_problem(select_cities(cities, depot, args.cities), depot.geonameid, args.departure,
                               args.alpha, args.beta)
        start = None if args.initial == "nearest-neighbor" else id_order_tour(problem)
        result = two_opt(problem, args.strategy, start)
        if args.output is not None:
            payload = result_as_dict(problem, result)
            payload["dataset"] = {
                "path": str(args.data.resolve()),
                "sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
            }
            args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (ValueError, OSError, csv.Error) as exc:
        parser.error(str(exc))

    evaluation = result.evaluation
    print(f"Safety-Aware 2-opt | cities={len(problem.cities)} | strategy={result.strategy} | start={args.initial}")
    print(f"Depot: {depot.name} ({depot.geonameid}) | departure: {format_arrival(problem.departure_minutes)}")
    print(f"Cost = {problem.alpha:g} * distance_scaled + {problem.beta:g} * time_scaled"
          f" + {problem.risk_weight:g} * risk_scaled")
    print(f"Distance: {evaluation.total_distance_km:.3f} km | scaled: {evaluation.distance_scaled:.6f}")
    print(f"Trip time: {format_duration(evaluation.total_time_minutes)} h, including"
          f" {format_duration(evaluation.total_wait_minutes)} h resting | scaled: {evaluation.time_scaled:.6f}")
    print(f"Arrival risk: {evaluation.total_risk:.2f} | scaled: {evaluation.risk_scaled:.6f}")
    print(f"Combined cost: {evaluation.cost:.6f} (initial tour: {result.initial_evaluation.cost:.6f})")
    print(f"Scaling divisors: distance={problem.distance_divisor_km:.6f} km; risk={problem.risk_divisor:g};"
          f" time={problem.time_divisor_minutes:.3f} min")
    print(f"Search: {result.improvements} improvements, {result.evaluated_moves} moves evaluated,"
          f" {result.runtime_seconds:.6f} s")
    print(f"\n{'Stop':>4}  {'City (GeoNameID)':<36} {'Local arrival':<16} {'Period':<5} {'Leg km':>10} {'Risk':>8}"
          f"  Rest before leaving")
    for index, visit in enumerate(evaluation.visits):
        label = f"{visit.city.name} ({visit.city.geonameid})"
        risk = "-" if visit.arrival_risk is None else f"{visit.arrival_risk:.2f}"
        period = "day" if is_day(visit.arrival_minutes) else "night"
        rest = "-" if visit.rest is None else f"{format_duration(visit.wait_minutes)} h ({visit.rest})"
        print(f"{index:>4}  {label:<36} {format_arrival(visit.arrival_minutes):<16} {period:<5}"
              f" {visit.leg_distance_km:>10.3f} {risk:>8}  {rest}")
    if args.output is not None:
        print(f"\nSaved JSON: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
