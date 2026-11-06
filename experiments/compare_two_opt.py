"""Compare Safety-Aware 2-opt and Safety-Aware Beam Search on the same trips.

Both searches receive the same make_problem() result, so they share the
distance matrix, the departure time, the weights, and the scaling divisors.
A cost from one subset cannot be compared with a cost from another subset.

Run the full study from the repository root (it takes roughly half an hour):

    python3 experiments/compare_two_opt.py

Run a one-minute check that the script still works:

    python3 experiments/compare_two_opt.py --quick

The full study writes experiments/results/comparison.json.
Nothing in this file changes the search code.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import platform
import random
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

# The script lives in experiments/, so the repository root has to be on the
# path before we can import beam_search.py and two_opt.py.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from beam_search import (  # noqa: E402
    DEFAULT_DATA, beam_search, evaluate_tour, load_cities, make_problem, parse_departure,
)
from two_opt import (  # noqa: E402
    IMPROVEMENT_TOLERANCE, id_order_tour, nearest_neighbor_tour, two_opt,
)


# In this CSV, these admin1 codes are East Malaysia:
# 11 Sarawak (Bintulu, Kuching, Miri, Sibu), 15 Labuan, 16 Kota Kinabalu.
# The numbers do not match every public list of Malaysia state codes.
EAST_MALAYSIA_ADMIN1 = {"11", "15", "16"}
EAST_MALAYSIA_NAMES = {"Bintulu", "Kuching", "Miri", "Sibu", "Labuan", "Kota Kinabalu"}

# 12 is the Selangor group in this file, 14 is Kuala Lumpur, 17 is Putrajaya.
KLANG_VALLEY_ADMIN1 = {"12", "14", "17"}
KLANG_VALLEY_NAMES = {
    "Bangi", "Cyberjaya", "Kajang", "Klang", "Kota Damansara", "Petaling Jaya",
    "Puchong", "Putra Heights", "Rawang", "Shah Alam", "Subang Jaya",
    "Ampang", "Kepong", "Kuala Lumpur", "Putrajaya",
}

# Morning, midday, afternoon, and evening. 08:00 is the command-line default,
# so the gap study measures it on its own.
GAP_DEPARTURES = ("06:00", "10:00", "14:00", "18:00")
ALL_DEPARTURES = ("06:00", "08:00", "10:00", "14:00", "18:00")
LARGE_DEPARTURES = ("08:00", "18:00")

# (alpha, beta, short name). Risk gets whatever weight is left.
WEIGHTS = (
    (0.4, 0.2, "default"),
    (1.0, 0.0, "distance-only"),
    (0.0, 0.0, "risk-only"),
    (0.0, 1.0, "time-only"),
)
SENSITIVITY_WEIGHTS = (
    (0.4, 0.2, "default"),
    (1.0, 0.0, "distance-only"),
    (0.0, 1.0, "time-only"),
    (0.0, 0.0, "risk-only"),
    (0.5, 0.05, "mixed"),
)

STRATEGIES = ("best", "first")
STARTS = ("nearest-neighbor", "id-order")
BEAM_WIDTHS = (1, 20, 100)
CURRENT_DEFAULT = "best, nearest-neighbor"

# Switch the built-in default only if another setting's average gap is better
# by more than half a percentage point. A smaller difference stays on the
# current default so one noisy study does not churn the command line.
DEFAULT_SWITCH_MARGIN = 0.005


def setting_name(strategy, start):
    """Label used in tables, such as 'best, nearest-neighbor'."""
    return f"{strategy}, {start}"


def find_city(cities, name):
    """Return the one city with this exact master-file name."""
    matches = [city for city in cities if city.name == name]
    if len(matches) != 1:
        raise ValueError(f"expected one city named {name!r}, found {len(matches)}")
    return matches[0]


def peninsular_cities(cities):
    """Every master city that is not in Sabah, Sarawak, or Labuan."""
    return [city for city in cities if city.admin1_code not in EAST_MALAYSIA_ADMIN1]


def contributor_pool(cities, minimum=15):
    """Peninsular cities with at least `minimum` Numbeo contributors.

    The list stays in master-file order so the same seed draws the same cities.
    """
    return [city for city in peninsular_cities(cities) if city.numbeo_contributors >= minimum]


def east_malaysia_cities(cities):
    return [city for city in cities if city.admin1_code in EAST_MALAYSIA_ADMIN1]


def klang_valley_cities(cities):
    return [city for city in cities if city.admin1_code in KLANG_VALLEY_ADMIN1]


def check_city_groups(cities):
    """Stop immediately if a region label no longer matches the master file."""
    if len(cities) != 43:
        raise ValueError(f"expected 43 master cities, found {len(cities)}")
    east_names = {city.name for city in east_malaysia_cities(cities)}
    klang_names = {city.name for city in klang_valley_cities(cities)}
    if east_names != EAST_MALAYSIA_NAMES:
        raise ValueError(f"East Malaysia names changed: {sorted(east_names)}")
    if klang_names != KLANG_VALLEY_NAMES:
        raise ValueError(f"Klang Valley names changed: {sorted(klang_names)}")
    if len(peninsular_cities(cities)) != 37:
        raise ValueError("expected 37 Peninsular cities")
    if len(contributor_pool(cities)) != 19:
        raise ValueError("expected 19 Peninsular cities with at least 15 contributors")


def city_brief(cities):
    """Small JSON-friendly description of a city group."""
    return [
        {
            "geonameid": city.geonameid,
            "name": city.name,
            "admin1_code": city.admin1_code,
            "numbeo_contributors": city.numbeo_contributors,
        }
        for city in cities
    ]


def gap_to_optimum(cost, optimum):
    """Relative gap, (cost - optimum) / optimum. Lower is better.

    A negative gap means a search beat the exhaustive optimum. That is a bug,
    so this raises instead of quietly clipping the number.
    """
    if optimum == 0:
        if cost > IMPROVEMENT_TOLERANCE:
            raise RuntimeError(f"optimum is 0 but a search scored {cost}")
        return 0.0
    gap = (cost - optimum) / optimum
    if gap < -1e-9:
        raise RuntimeError(f"search cost {cost} beat the exhaustive optimum {optimum}")
    if gap < 0:
        return 0.0
    return gap


def costs_are_equal(left, right):
    return abs(left - right) <= IMPROVEMENT_TOLERANCE


def outcome(two_opt_cost, beam_cost):
    """Who found the cheaper tour on one instance."""
    if two_opt_cost < beam_cost - IMPROVEMENT_TOLERANCE:
        return "two_opt_cheaper"
    if beam_cost < two_opt_cost - IMPROVEMENT_TOLERANCE:
        return "beam_cheaper"
    return "tie"


def exhaustive_optimum(problem):
    """Cheapest tour over every stop order. Each order gets its own best rests.

    Nine cities means 8! = 40,320 orders. This refuses anything larger so a
    changed setting cannot start a factorial that will not finish.
    """
    stops = [index for index in range(len(problem.cities)) if index != problem.depot]
    if len(stops) > 8:
        raise ValueError(f"{len(stops)} stops is too many for exhaustive search")
    best_cost = None
    for order in itertools.permutations(stops):
        tour = (problem.depot, *order, problem.depot)
        cost = evaluate_tour(problem, tour).cost
        if best_cost is None or cost < best_cost:
            best_cost = cost
    return best_cost


def score_fields(evaluation):
    """Raw totals and scaled totals. Raw totals stay meaningful across subsets."""
    return {
        "cost": evaluation.cost,
        "distance_km": evaluation.total_distance_km,
        "risk": evaluation.total_risk,
        "time_minutes": evaluation.total_time_minutes,
        "wait_minutes": evaluation.total_wait_minutes,
        "distance_scaled": evaluation.distance_scaled,
        "risk_scaled": evaluation.risk_scaled,
        "time_scaled": evaluation.time_scaled,
    }


def route_ids(problem, evaluation):
    return [problem.cities[index].geonameid for index in evaluation.tour]


def route_names(problem, evaluation):
    return [problem.cities[index].name for index in evaluation.tour]


def draw_instances(pool, trial_count, seed, departure_names, city_count, balance_departures=False):
    """Sample city sets with random.Random(seed).

    The gap study calls sample() and then choice(), in that order. The weight
    study sets balance_departures=True and does not call choice(), so every
    clock time appears the same number of times. Extra random calls would
    draw a different set of cities.
    """
    generator = random.Random(seed)
    departure_minutes = [parse_departure(name) for name in departure_names]
    drawn = []
    for trial_number in range(trial_count):
        chosen = generator.sample(pool, city_count)
        if balance_departures:
            minutes = departure_minutes[trial_number % len(departure_minutes)]
        else:
            minutes = generator.choice(departure_minutes)
        departure_name = departure_names[departure_minutes.index(minutes)]
        drawn.append({
            "trial": trial_number,
            "cities": chosen,
            "depot_id": chosen[0].geonameid,
            "depot_name": chosen[0].name,
            "departure": departure_name,
            "departure_minutes": minutes,
        })
    return drawn


def solve_instance(cities, depot_id, departure_minutes, alpha, beta, with_optimum):
    """Run every 2-opt setting and every beam width on one shared problem."""
    problem = make_problem(cities, depot_id, departure_minutes, alpha, beta)
    optimum = exhaustive_optimum(problem) if with_optimum else None

    # Distance-only nearest neighbor, then scored with the real objective.
    # This is a baseline. It is not one of the two project algorithms.
    baseline_tour = nearest_neighbor_tour(problem)
    baseline = evaluate_tour(problem, baseline_tour)

    two_opt_runs = {}
    for strategy in STRATEGIES:
        for start in STARTS:
            # Match the command line: nearest neighbor is built inside two_opt(),
            # and id-order is built before the timer starts.
            if start == "nearest-neighbor":
                initial_tour = None
            else:
                initial_tour = id_order_tour(problem)
            result = two_opt(problem, strategy, initial_tour)
            fields = score_fields(result.evaluation)
            fields.update({
                "strategy": strategy,
                "start": start,
                "start_cost": result.initial_evaluation.cost,
                "improvements": result.improvements,
                "evaluated_moves": result.evaluated_moves,
                "runtime_seconds": result.runtime_seconds,
                "route_geonameids": route_ids(problem, result.evaluation),
                "route_names": route_names(problem, result.evaluation),
            })
            if optimum is not None:
                fields["gap"] = gap_to_optimum(result.evaluation.cost, optimum)
            if start == "nearest-neighbor" and not costs_are_equal(fields["start_cost"], baseline.cost):
                raise RuntimeError("nearest-neighbor start does not match the baseline tour")
            two_opt_runs[setting_name(strategy, start)] = fields

    beam_runs = {}
    for width in BEAM_WIDTHS:
        result = beam_search(problem, width)
        fields = score_fields(result.evaluation)
        fields.update({
            "beam_width": width,
            "expanded_states": result.expanded_states,
            "generated_states": result.generated_states,
            "peak_beam_size": result.peak_beam_size,
            "runtime_seconds": result.runtime_seconds,
            "route_geonameids": route_ids(problem, result.evaluation),
            "route_names": route_names(problem, result.evaluation),
        })
        if optimum is not None:
            fields["gap"] = gap_to_optimum(result.evaluation.cost, optimum)
        beam_runs[str(width)] = fields

    saved = {
        "geonameids": [city.geonameid for city in problem.cities],
        "names": [city.name for city in problem.cities],
        "depot_geonameid": problem.cities[problem.depot].geonameid,
        "depot_name": problem.cities[problem.depot].name,
        "departure_minutes": problem.departure_minutes,
        "alpha": alpha,
        "beta": beta,
        "risk_weight": problem.risk_weight,
        "city_count": len(problem.cities),
        "nearest_neighbor": score_fields(baseline),
        "two_opt": two_opt_runs,
        "beam": beam_runs,
    }
    if optimum is not None:
        saved["optimum"] = optimum
        saved["nearest_neighbor"]["gap"] = gap_to_optimum(baseline.cost, optimum)
    return saved


def _rounded_mean(values):
    return statistics.mean(values) if values else None


def _rounded_median(values):
    return statistics.median(values) if values else None


def summarise_gap_rows(rows, split_by_departure=True):
    """Average gaps, runtimes, and win counts for one list of solved instances.

    split_by_departure is turned off for the per-departure call. Leaving it on
    would group the same rows again and never return.
    """
    if not rows:
        return {"trials": 0, "two_opt": {}, "beam": {}, "comparisons": {}}

    two_opt_summary = {}
    for name in rows[0]["two_opt"]:
        gaps = [row["two_opt"][name]["gap"] for row in rows]
        runtimes = [row["two_opt"][name]["runtime_seconds"] for row in rows]
        optimal_hits = sum(1 for gap in gaps if gap <= 1e-9)
        two_opt_summary[name] = {
            "mean_gap": _rounded_mean(gaps),
            "median_gap": _rounded_median(gaps),
            "max_gap": max(gaps),
            "optimal_hits": optimal_hits,
            "mean_runtime_seconds": _rounded_mean(runtimes),
            "median_runtime_seconds": _rounded_median(runtimes),
        }

    beam_summary = {}
    for width in rows[0]["beam"]:
        gaps = [row["beam"][width]["gap"] for row in rows]
        runtimes = [row["beam"][width]["runtime_seconds"] for row in rows]
        optimal_hits = sum(1 for gap in gaps if gap <= 1e-9)
        beam_summary[width] = {
            "mean_gap": _rounded_mean(gaps),
            "median_gap": _rounded_median(gaps),
            "max_gap": max(gaps),
            "optimal_hits": optimal_hits,
            "mean_runtime_seconds": _rounded_mean(runtimes),
            "median_runtime_seconds": _rounded_median(runtimes),
        }

    baseline_gaps = [row["nearest_neighbor"]["gap"] for row in rows]
    comparisons = {}
    for name in rows[0]["two_opt"]:
        for width in rows[0]["beam"]:
            counts = {"two_opt_cheaper": 0, "beam_cheaper": 0, "tie": 0}
            for row in rows:
                winner = outcome(row["two_opt"][name]["cost"], row["beam"][width]["cost"])
                counts[winner] += 1
            comparisons[f"{name} vs beam {width}"] = counts

    # How often each 2-opt setting is the cheapest 2-opt result on a trial.
    # Tied settings each get the win.
    setting_wins = {name: 0 for name in rows[0]["two_opt"]}
    for row in rows:
        costs = {name: row["two_opt"][name]["cost"] for name in row["two_opt"]}
        best_cost = min(costs.values())
        for name, cost in costs.items():
            if costs_are_equal(cost, best_cost):
                setting_wins[name] += 1

    departure_summary = {}
    if split_by_departure:
        grouped = {}
        departure_names = []
        for row in rows:
            if row["departure"] not in grouped:
                departure_names.append(row["departure"])
                grouped[row["departure"]] = []
            grouped[row["departure"]].append(row)
        for departure_name in departure_names:
            departure_summary[departure_name] = summarise_gap_rows(
                grouped[departure_name], split_by_departure=False,
            )

    return {
        "trials": len(rows),
        "two_opt": two_opt_summary,
        "beam": beam_summary,
        "nearest_neighbor_baseline": {
            "mean_gap": _rounded_mean(baseline_gaps),
            "median_gap": _rounded_median(baseline_gaps),
            "max_gap": max(baseline_gaps),
        },
        "comparisons": comparisons,
        "two_opt_setting_wins": setting_wins,
        "by_departure": departure_summary,
    }


def choose_default(two_opt_summary):
    """Decide whether best + nearest-neighbor should stay the command default."""
    current = two_opt_summary[CURRENT_DEFAULT]
    best_gap = min(item["mean_gap"] for item in two_opt_summary.values())
    if current["mean_gap"] <= best_gap + DEFAULT_SWITCH_MARGIN:
        return {
            "setting": CURRENT_DEFAULT,
            "action": "keep",
            "reason": (
                "best + nearest-neighbor stays the default. Its mean gap is within "
                "0.5 percentage points of the best 2-opt setting in the 9-city study."
            ),
        }

    ranked = sorted(
        two_opt_summary.items(),
        key=lambda item: (item[1]["mean_gap"], item[1]["median_runtime_seconds"], item[0]),
    )
    chosen_name, chosen = ranked[0]
    return {
        "setting": chosen_name,
        "action": "change",
        "reason": (
            f"Change the default to {chosen_name}. Its mean gap is {chosen['mean_gap']:.2%}, "
            f"which is more than 0.5 percentage points better than {CURRENT_DEFAULT} "
            f"at {current['mean_gap']:.2%}."
        ),
    }


def public_instance(row):
    """Drop nothing important, but keep the saved row free of live city objects.

    solve_instance already returns plain numbers and lists. This copy also
    removes the per-trial route name lists from the random studies, where the
    ids are enough and the names would make the file hard to open.
    """
    saved = {
        "trial": row.get("trial"),
        "departure": row.get("departure"),
        "weight": row.get("weight"),
        "geonameids": row["geonameids"],
        "depot_geonameid": row["depot_geonameid"],
        "depot_name": row["depot_name"],
        "departure_minutes": row["departure_minutes"],
        "alpha": row["alpha"],
        "beta": row["beta"],
        "risk_weight": row["risk_weight"],
        "city_count": row["city_count"],
        "nearest_neighbor_cost": row["nearest_neighbor"]["cost"],
        "two_opt": {},
        "beam": {},
    }
    if "optimum" in row:
        saved["optimum"] = row["optimum"]
        saved["nearest_neighbor_gap"] = row["nearest_neighbor"]["gap"]
    for name, result in row["two_opt"].items():
        saved["two_opt"][name] = {
            "cost": result["cost"],
            "gap": result.get("gap"),
            "distance_km": result["distance_km"],
            "risk": result["risk"],
            "time_minutes": result["time_minutes"],
            "wait_minutes": result["wait_minutes"],
            "start_cost": result["start_cost"],
            "improvements": result["improvements"],
            "evaluated_moves": result["evaluated_moves"],
            "runtime_seconds": result["runtime_seconds"],
            "route_geonameids": result["route_geonameids"],
        }
    for width, result in row["beam"].items():
        saved["beam"][width] = {
            "cost": result["cost"],
            "gap": result.get("gap"),
            "distance_km": result["distance_km"],
            "risk": result["risk"],
            "time_minutes": result["time_minutes"],
            "wait_minutes": result["wait_minutes"],
            "expanded_states": result["expanded_states"],
            "generated_states": result["generated_states"],
            "peak_beam_size": result["peak_beam_size"],
            "runtime_seconds": result["runtime_seconds"],
            "route_geonameids": result["route_geonameids"],
        }
    return saved


def run_gap_study(pool, trial_count, seed, departure_names, label):
    """Small random instances, each with an exhaustive optimum."""
    print(f"\n{label}: {trial_count} trials, seed {seed}, departures {', '.join(departure_names)}", flush=True)
    specs = draw_instances(pool, trial_count, seed, departure_names, city_count=9)
    rows = []
    started = time.perf_counter()
    for spec in specs:
        if spec["trial"] % 10 == 0:
            print(f"  trial {spec['trial'] + 1}/{trial_count}", flush=True)
        row = solve_instance(
            spec["cities"], spec["depot_id"], spec["departure_minutes"], 0.4, 0.2, with_optimum=True,
        )
        row["trial"] = spec["trial"]
        row["departure"] = spec["departure"]
        row["weight"] = "default"
        rows.append(row)
    elapsed = time.perf_counter() - started
    summary = summarise_gap_rows(rows)
    summary["seed"] = seed
    summary["departures"] = list(departure_names)
    summary["alpha"] = 0.4
    summary["beta"] = 0.2
    summary["city_count"] = 9
    summary["wall_seconds"] = elapsed
    print(f"  finished in {elapsed / 60:.1f} min", flush=True)
    print_gap_table(summary)
    return {"summary": summary, "trials": [public_instance(row) for row in rows]}


def run_weight_study(pool, trial_count, seed):
    """Same sampled cities under five weight pairs. Each pair has its own optimum."""
    print(f"\nWeight study: {trial_count} city samples, seed {seed}, five weights", flush=True)
    specs = draw_instances(
        pool, trial_count, seed, ALL_DEPARTURES, city_count=9, balance_departures=True,
    )
    grouped = []
    started = time.perf_counter()
    for spec in specs:
        print(f"  sample {spec['trial'] + 1}/{trial_count}, departure {spec['departure']}", flush=True)
        by_weight = {"trial": spec["trial"], "departure": spec["departure"], "weights": {}}
        for alpha, beta, weight_name in SENSITIVITY_WEIGHTS:
            row = solve_instance(
                spec["cities"], spec["depot_id"], spec["departure_minutes"], alpha, beta, with_optimum=True,
            )
            row["trial"] = spec["trial"]
            row["departure"] = spec["departure"]
            row["weight"] = weight_name
            by_weight["weights"][weight_name] = public_instance(row)
        grouped.append(by_weight)
    by_weight_summary = {}
    for _alpha, _beta, weight_name in SENSITIVITY_WEIGHTS:
        weight_rows = []
        for sample in grouped:
            saved = sample["weights"][weight_name]
            # summarise_gap_rows expects the nested two_opt/beam shape with gaps.
            weight_rows.append(_summary_row_from_public(saved))
        by_weight_summary[weight_name] = summarise_gap_rows(weight_rows)
    elapsed = time.perf_counter() - started
    print(f"  finished in {elapsed / 60:.1f} min", flush=True)
    return {
        "seed": seed,
        "trials": trial_count,
        "departures": list(ALL_DEPARTURES),
        "wall_seconds": elapsed,
        "summary": by_weight_summary,
        "samples": grouped,
    }


def _summary_row_from_public(saved):
    """Turn a saved trial back into the shape summarise_gap_rows reads."""
    row = {
        "departure": saved["departure"],
        "nearest_neighbor": {"gap": saved["nearest_neighbor_gap"], "cost": saved["nearest_neighbor_cost"]},
        "two_opt": {},
        "beam": {},
    }
    for name, result in saved["two_opt"].items():
        row["two_opt"][name] = result
    for width, result in saved["beam"].items():
        row["beam"][width] = result
    return row


def run_named_instance(name, cities, depot_name, departure_name, alpha, beta, with_optimum):
    depot = find_city(cities, depot_name)
    print(f"  {name} | depot {depot_name} | {departure_name} | alpha {alpha} beta {beta}", flush=True)
    row = solve_instance(cities, depot.geonameid, parse_departure(departure_name), alpha, beta, with_optimum)
    row["label"] = name
    row["departure"] = departure_name
    row["weight"] = next(label for a, b, label in (*WEIGHTS, *SENSITIVITY_WEIGHTS) if a == alpha and b == beta)
    return row


def run_large_study(groups):
    """Bigger fixed subsets. Exhaustive search only for the 6-city East group."""
    print("\nLarge-instance study", flush=True)
    rows = []
    started = time.perf_counter()
    for group_name, cities, depot_name, departures, weights, with_optimum in groups:
        for departure_name in departures:
            for alpha, beta, weight_name in weights:
                row = run_named_instance(
                    group_name, cities, depot_name, departure_name, alpha, beta, with_optimum,
                )
                row["weight"] = weight_name
                rows.append(row)
    elapsed = time.perf_counter() - started
    print(f"  finished in {elapsed / 60:.1f} min", flush=True)
    return {"wall_seconds": elapsed, "instances": [_large_public_row(row) for row in rows]}


def _large_public_row(row):
    saved = public_instance(row)
    saved["label"] = row["label"]
    saved["names"] = row["names"]
    for name, result in row["two_opt"].items():
        saved["two_opt"][name]["route_names"] = result["route_names"]
    for width, result in row["beam"].items():
        saved["beam"][width]["route_names"] = result["route_names"]
    return saved


def median_peak_bytes(callback, repeats):
    """Peak Python allocations during callback(), median of several fresh traces."""
    peaks = []
    last_result = None
    for _ in range(repeats):
        tracemalloc.start()
        last_result = callback()
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peaks.append(peak)
    return last_result, statistics.median(peaks), peaks


def run_timing_and_memory(cases, repeats):
    """Median search time and peak memory. The problem is built before the clock.

    Memory is the tracemalloc peak of the search call only. It is not the
    O(n^4) complexity bound, and it includes the Python objects that call allocates.
    """
    print("\nTiming and memory", flush=True)
    timing_rows = []
    memory_rows = []
    for case in cases:
        cities = case["cities"]
        depot = find_city(cities, case["depot_name"])
        for departure_name in case["departures"]:
            problem = make_problem(cities, depot.geonameid, parse_departure(departure_name), 0.4, 0.2)
            print(f"  {case['name']} | {departure_name} | {len(problem.cities)} cities", flush=True)
            for strategy in STRATEGIES:
                for start in STARTS:
                    samples = []
                    for _ in range(repeats):
                        if start == "nearest-neighbor":
                            result = two_opt(problem, strategy, None)
                        else:
                            result = two_opt(problem, strategy, id_order_tour(problem))
                        samples.append(result.runtime_seconds)
                    timing_rows.append({
                        "group": case["name"],
                        "cities": len(problem.cities),
                        "departure": departure_name,
                        "method": setting_name(strategy, start),
                        "median_runtime_seconds": statistics.median(samples),
                        "runtimes_seconds": samples,
                    })
            for width in BEAM_WIDTHS:
                samples = [beam_search(problem, width).runtime_seconds for _ in range(repeats)]
                timing_rows.append({
                    "group": case["name"],
                    "cities": len(problem.cities),
                    "departure": departure_name,
                    "method": f"beam {width}",
                    "median_runtime_seconds": statistics.median(samples),
                    "runtimes_seconds": samples,
                })

        # One departure is enough for a memory snapshot. Repeating both clocks
        # mostly repeats the same allocation pattern.
        problem = make_problem(cities, depot.geonameid, parse_departure("08:00"), 0.4, 0.2)
        _result, two_opt_peak, two_opt_peaks = median_peak_bytes(
            lambda problem=problem: two_opt(problem, "best", None), repeats,
        )
        _result, beam_peak, beam_peaks = median_peak_bytes(
            lambda problem=problem: beam_search(problem, 100), repeats,
        )
        memory_rows.append({
            "group": case["name"],
            "cities": len(problem.cities),
            "departure": "08:00",
            "two_opt_best_nearest_neighbor_median_peak_bytes": two_opt_peak,
            "two_opt_peaks_bytes": two_opt_peaks,
            "beam_100_median_peak_bytes": beam_peak,
            "beam_peaks_bytes": beam_peaks,
        })
    return {"repeats": repeats, "timing": timing_rows, "memory": memory_rows}


def print_gap_table(summary):
    print(f"  {'method':<28} {'mean gap':>10} {'median':>10} {'max':>10} {'optimal':>10} {'mean s':>8}")
    for name, item in summary["two_opt"].items():
        hits = f"{item['optimal_hits']}/{summary['trials']}"
        print(f"  {name:<28} {item['mean_gap']:>10.2%} {item['median_gap']:>10.2%} "
              f"{item['max_gap']:>10.2%} {hits:>10} {item['mean_runtime_seconds']:>8.3f}")
    for width, item in summary["beam"].items():
        hits = f"{item['optimal_hits']}/{summary['trials']}"
        label = f"beam {width}"
        print(f"  {label:<28} {item['mean_gap']:>10.2%} {item['median_gap']:>10.2%} "
              f"{item['max_gap']:>10.2%} {hits:>10} {item['mean_runtime_seconds']:>8.3f}")
    baseline = summary["nearest_neighbor_baseline"]["mean_gap"]
    print(f"  nearest-neighbor baseline mean gap {baseline:.2%}")


def dataset_sha256():
    return hashlib.sha256(Path(DEFAULT_DATA).read_bytes()).hexdigest()


def save_payload(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Saved {path}", flush=True)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true",
                        help="one trial of each small study, and skip the 37-city and 43-city runs")
    parser.add_argument("--gap-trials", type=int, default=200)
    parser.add_argument("--morning-trials", type=int, default=40)
    parser.add_argument("--weight-trials", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=3, help="repeats for the timing and memory table")
    parser.add_argument("--seed", type=int, default=201, help="seed for the main 9-city study")
    parser.add_argument("--output", type=Path, default=Path("experiments/results/comparison.json"))
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    for name in ("gap_trials", "morning_trials", "weight_trials", "repeats"):
        if getattr(args, name) < 1:
            parser.error(f"{name.replace('_', '-')} must be at least 1")

    if args.quick:
        args.gap_trials = 1
        args.morning_trials = 1
        args.weight_trials = 1
        args.repeats = 1

    cities = list(load_cities())
    check_city_groups(cities)
    pool = contributor_pool(cities)
    peninsular = peninsular_cities(cities)
    east = east_malaysia_cities(cities)
    klang = klang_valley_cities(cities)

    payload = {
        "dataset_sha256": dataset_sha256(),
        "dataset_path": str(Path(DEFAULT_DATA).resolve()),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "notes": [
            "Every algorithm in one row uses one make_problem() instance.",
            "Do not compare a cost from one subset or weight pair with a cost from another. The scaling divisors change.",
            "The optimum tries every stop order and scores each order with evaluate_tour().",
            "The comparison is two_opt() against beam_search() on the shared overnight-rest model.",
            "The all-43 subset includes cross-sea Haversine legs. The Peninsular, Klang Valley, and East Malaysia subsets do not mix those regions.",
            "Search runtime excludes CSV loading and matrix construction. Memory is a separate tracemalloc peak.",
            "The single-run table in the older 2-opt handover is not this study.",
        ],
        "groups": {
            "contributor_pool_19": city_brief(pool),
            "peninsular_37": city_brief(peninsular),
            "klang_valley_15": city_brief(klang),
            "east_malaysia_6": city_brief(east),
            "all_43_count": len(cities),
        },
    }

    # Fail in seconds if a search can beat the exhaustive optimum.
    print("Sanity check: README example and East Malaysia", flush=True)
    example_cities = [find_city(cities, name) for name in
                      ("Kuala Lumpur", "Ipoh", "Johor Bahru", "Kuantan", "Malacca")]
    example = run_named_instance(
        "README example", example_cities, "Kuala Lumpur", "18:00", 0.4, 0.2, with_optimum=True,
    )
    east_check = run_named_instance(
        "East Malaysia check", east, "Kuching", "08:00", 0.4, 0.2, with_optimum=True,
    )
    payload["sanity_checks"] = [_large_public_row(example), _large_public_row(east_check)]
    save_payload(args.output, payload)

    payload["gap_study"] = run_gap_study(
        pool, args.gap_trials, args.seed, GAP_DEPARTURES,
        "Main gap study",
    )
    save_payload(args.output, payload)

    payload["morning_study"] = run_gap_study(
        pool, args.morning_trials, args.seed + 1, ("08:00",),
        "08:00 departure study",
    )
    save_payload(args.output, payload)

    payload["weight_study"] = run_weight_study(pool, args.weight_trials, args.seed + 2)
    save_payload(args.output, payload)

    large_groups = [
        ("Klang Valley", klang, "Kuala Lumpur", LARGE_DEPARTURES, WEIGHTS, False),
        ("East Malaysia", east, "Kuching", LARGE_DEPARTURES, WEIGHTS, True),
    ]
    timing_cases = [
        {"name": "Klang Valley", "cities": klang, "depot_name": "Kuala Lumpur", "departures": LARGE_DEPARTURES},
        {"name": "East Malaysia", "cities": east, "depot_name": "Kuching", "departures": LARGE_DEPARTURES},
    ]
    if not args.quick:
        # Johor Bahru varies the depot on the realistic Peninsular road set.
        # It is only run at the default weight so the grid stays finishable.
        peninsular_default = ((0.4, 0.2, "default"),)
        large_groups.extend([
            ("Peninsular", peninsular, "Kuala Lumpur", LARGE_DEPARTURES, WEIGHTS, False),
            ("Peninsular", peninsular, "Johor Bahru", LARGE_DEPARTURES, peninsular_default, False),
            ("All 43 cities", cities, "Kuala Lumpur", LARGE_DEPARTURES, WEIGHTS, False),
        ])
        timing_cases.extend([
            {"name": "Peninsular", "cities": peninsular, "depot_name": "Kuala Lumpur", "departures": LARGE_DEPARTURES},
            {"name": "All 43 cities", "cities": cities, "depot_name": "Kuala Lumpur", "departures": LARGE_DEPARTURES},
        ])
    payload["large_study"] = run_large_study(large_groups)
    save_payload(args.output, payload)

    # A fixed 9-city sample so the timing table has a small row as well as the big ones.
    sample = draw_instances(pool, 1, args.seed, ("08:00",), 9)[0]
    timing_cases.insert(0, {
        "name": "9-city sample",
        "cities": sample["cities"],
        "depot_name": sample["depot_name"],
        "departures": LARGE_DEPARTURES,
    })
    payload["timing_and_memory"] = run_timing_and_memory(timing_cases, args.repeats)
    payload["default_recommendation"] = choose_default(payload["gap_study"]["summary"]["two_opt"])
    payload["default_recommendation"]["morning_check"] = choose_default(
        payload["morning_study"]["summary"]["two_opt"],
    )
    save_payload(args.output, payload)
    print("\nDefault recommendation:", payload["default_recommendation"]["reason"], flush=True)
    print("08:00 check:", payload["default_recommendation"]["morning_check"]["reason"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
