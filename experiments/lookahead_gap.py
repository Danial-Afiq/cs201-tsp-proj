"""Optimality gap of plain vs lookahead beam search on small Peninsular instances.

Pool: Peninsular Malaysia locations (excluding Sabah ``16``, Sarawak ``11`` and
Labuan ``15``) with at least ``--min-contributors`` Numbeo contributors
(19 locations at the default of 15). Each trial samples ``--size`` cities
(including the depot, the first sampled city), a departure time from
``--departures``, and solves the instance exactly by brute force over every
stop order, each scored with its cheapest overnight rests (``evaluate_tour``). Gap is
``(heuristic_cost - optimal_cost) / optimal_cost``.

Run from the repository root:

    python3 experiments/lookahead_gap.py                       # defaults below
    python3 experiments/lookahead_gap.py --output results.json  # keep per-trial rows
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from beam_search import (  # noqa: E402
    DEFAULT_DATA, beam_search, evaluate_tour, load_cities, make_problem, parse_departure,
)
from lookahead_beam_search import lookahead_beam_search  # noqa: E402

EAST_MALAYSIA_ADMIN1 = {"11", "15", "16"}  # Sarawak, Labuan, Sabah


def peninsular_pool(min_contributors: int):
    return [city for city in load_cities()
            if city.admin1_code not in EAST_MALAYSIA_ADMIN1
            and city.numbeo_contributors >= min_contributors]


def brute_force_cost(problem) -> float:
    """Exact optimum: every order of the non-depot stops, each with its cheapest rests."""
    stops = [index for index in range(len(problem.cities)) if index != problem.depot]
    return min(evaluate_tour(problem, (problem.depot, *order, problem.depot)).cost
               for order in itertools.permutations(stops))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trials", type=int, default=200)
    parser.add_argument("--size", type=int, default=9, help="cities per instance, including the depot")
    parser.add_argument("--seed", type=int, default=201)
    parser.add_argument("--alpha", type=float, default=0.4)
    parser.add_argument("--beta", type=float, default=0.2)
    parser.add_argument("--departures", nargs="+", type=parse_departure,
                        default=[parse_departure(t) for t in ("06:00", "10:00", "14:00", "18:00")])
    parser.add_argument("--widths", nargs="+", type=int, default=[1, 20, 100])
    parser.add_argument("--min-contributors", type=int, default=15)
    parser.add_argument("--output", type=Path, help="save metadata and per-trial rows as JSON")
    args = parser.parse_args(argv)

    pool = peninsular_pool(args.min_contributors)
    rng = random.Random(args.seed)
    methods = {"plain": beam_search, "lookahead": lookahead_beam_search}
    gaps = {(name, width): [] for name in methods for width in args.widths}
    seconds = {(name, width): 0.0 for name in methods for width in args.widths}
    rows = []
    print(f"Pool: {len(pool)} Peninsular cities (>= {args.min_contributors} contributors); "
          f"{args.trials} trials of {args.size} cities; seed={args.seed}; alpha={args.alpha}; beta={args.beta}")
    for trial in range(args.trials):
        chosen = rng.sample(pool, args.size)
        departure = rng.choice(args.departures)
        problem = make_problem(chosen, chosen[0].geonameid, departure, args.alpha, args.beta)
        optimum = brute_force_cost(problem)
        row = {"trial": trial, "geonameids": [c.geonameid for c in chosen],
               "depot": chosen[0].geonameid, "departure_minutes": departure, "optimum": optimum}
        for name, search in methods.items():
            for width in args.widths:
                result = search(problem, width)
                gap = (result.evaluation.cost - optimum) / optimum if optimum else 0.0
                if gap < -1e-9:
                    raise AssertionError(f"trial {trial}: heuristic beat brute force")
                gaps[name, width].append(max(gap, 0.0))
                seconds[name, width] += result.runtime_seconds
                row[f"{name}_W{width}"] = result.evaluation.cost
        rows.append(row)

    print(f"\n{'method':<10} {'W':>4} {'mean gap':>9} {'median':>8} {'max':>8} {'optimal':>8} {'ms/run':>8}")
    summary = []
    for (name, width), values in gaps.items():
        hits = sum(value < 1e-9 for value in values)
        entry = {"method": name, "beam_width": width, "mean_gap": statistics.mean(values),
                 "median_gap": statistics.median(values), "max_gap": max(values),
                 "optimal_hits": hits, "mean_ms": 1000 * seconds[name, width] / len(values)}
        summary.append(entry)
        print(f"{name:<10} {width:>4} {entry['mean_gap']:>8.2%} {entry['median_gap']:>8.2%} "
              f"{entry['max_gap']:>8.2%} {hits:>4}/{len(values):<3} {entry['mean_ms']:>8.2f}")

    # Non-monotonicity: trials where a wider beam is worse than a narrower one.
    for name in methods:
        for narrow, wide in zip(args.widths, args.widths[1:]):
            worse = sum(row[f"{name}_W{wide}"] > row[f"{name}_W{narrow}"] + 1e-12 for row in rows)
            print(f"{name}: W={wide} worse than W={narrow} in {worse}/{len(rows)} trials")

    if args.output is not None:
        payload = {
            "dataset_sha256": hashlib.sha256(Path(DEFAULT_DATA).read_bytes()).hexdigest(),
            "pool_geonameids": [c.geonameid for c in pool],
            "parameters": {k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
            "summary": summary, "trials": rows,
        }
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"\nSaved {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
