# Safety-Aware 2-opt implementation

`two_opt.py` implements the second of the team's two planned approaches. It uses only the Python standard library. The design choices below are project implementation decisions, not additional assignment requirements. The instance, scaling, objective, rest rules and full-tour evaluation come from `beam_search.py`, so both approaches score routes by the same rules; see the [Beam Search notes](beam_search.md) for the objective, time and rest model.

## Handover

**Status on 2026-11-01:** the algorithm, command-line runner, tests and these notes are finished and uncommitted. All 49 tests pass (26 Beam Search, 23 2-opt). No comparative experiment has been run.

**What was added or changed**

| File | Change | What it does |
| --- | --- | --- |
| `two_opt.py` | New | Runs 2-opt on the current overnight-rest model, with the same instance options and JSON metadata as Beam Search. This replaces "2-opt not implemented". |
| `tests/test_two_opt.py` | New | Adds 23 tests for move acceptance, rest handling, local optimality, determinism, invalid input, and agreement with the shared evaluator. |
| `docs/two_opt.md` | New | Records the design, pseudocode, complexity, verification and this handover. |
| `README.md`, `AGENTS.md`, `docs/beam_search.md` | Updated | Replace the "2-opt is future work" wording and record the new status, run instructions and test counts. |
| `beam_search.py` | Docstring only | Says 2-opt now uses the shared model. Search and evaluator logic did not change. |
| `.gitignore` | New | Keeps Python bytecode and virtual environments out of commits. |

**What the next person can do**

1. **Run the comparison, which is the main remaining work.** Write an experiment script that runs `two_opt()` and `beam_search()` on identical instances from one `make_problem()` call. Vary subset, region, depot, departure, `alpha`, `beta`, beam width, strategy and start. Save the JSON output as the experiment record. No such script or results folder exists yet.
2. **Measure the gap to the optimum on small instances.** Compare against `itertools.permutations` with `evaluate_tour()`, as the tests do. The tests only prove that 2-opt never beats the optimum, not how close it gets.
3. **Choose the default strategy and start from evidence.** `best` with `nearest-neighbor` is a starting choice, not a tuned one. See [Early observations](#early-observations) for why this matters.
4. **Try a risk-aware or multi-start initial tour if experiments show weak starts.** Add it next to `nearest_neighbor_tour()` and to `INITIAL_TOURS`. `two_opt()` already accepts any valid tour through `initial_tour`, so this needs no search changes. For a seeded start, record the seed.
5. **Add memory measurement.** Neither runner measures memory; `tracemalloc` is a standard-library option. Report it separately from the complexity claims.
6. **Only if experiments are too slow, speed up candidate costing.** After a reversal, the best cost after resting at any position beyond the segment does not change, because rests end at 07:00. The per-position values in `_best_rest_stops()` could therefore be reused. This changes the shared evaluator, so test that every candidate cost still equals `evaluate_tour().cost` exactly.
7. **Prepare the presentation material.** The pseudocode, complexity and trade-offs below can be used directly, but team members must be able to explain and defend them. The results must come from step 1.

**Known limits**

- The final tour depends on the start and strategy, and it is only a local optimum for single reversals.
- `two_opt.py` repeats the Beam Search console output code instead of sharing it. This kept `beam_search.py` unchanged. The JSON sections are shared, so they cannot drift apart.

## Why this is not classic 2-opt

Classic 2-opt reverses a segment and computes the change from the two replaced edges in constant time. That shortcut does not hold here, because arrival time depends on every earlier leg and on the rests taken:

1. **Changes reach past the segment.** A reversal that alters the length of a prefix shifts every later arrival, so a stop outside the segment can cross 07:00 or 19:00, change risk, or gain or lose a mandatory rest.
2. **Rests change with the tour.** Each candidate needs its own cheapest rest schedule. Keeping the current tour's rests would misprice the move, so every candidate goes through `evaluate_tour()`.
3. **Reversing every stop is a real move.** The same edges remain, so classic 2-opt treats it as a no-op. Here the distance stays the same, but arrival times, rests and risk can differ. It is the only move on a three-city instance.
4. **Lower cost can mean a longer route.** A move is accepted when the weighted objective falls, even if distance rises.

## State and data structures

| Structure | Purpose |
| --- | --- |
| Route tuple | Holds the current complete tour, with the depot fixed at both ends. Each candidate is a new `O(n)` copy, so the current tour is never partly changed. |
| `TourEvaluation` of the current tour | Holds the current cost and tour, replaced when a move is accepted. |
| Shared symmetric distance matrix | Reuses geographical distances from `make_problem()`. |

Unlike Beam Search, which holds many partial tours and builds them forward, this approach holds one complete tour at all times and repairs it.

## Search

```text
current = evaluate(starting tour)
repeat:
    best = none; threshold = current.cost - tolerance
    for first = 1 to n - 2:
        for last = first + 1 to n - 1:
            candidate = evaluate(current.tour with positions first..last reversed)
            if candidate.cost < threshold:
                best = candidate; threshold = candidate.cost
                if strategy is "first": stop scanning
    if best is none: stop
    current = best
return current
```

Positions `1..n-1` hold the stops; the depot occupies positions `0` and `n`. Here `evaluate` is `evaluate_tour()`, which validates the tour and chooses its cheapest rests.

| Choice | Decision |
| --- | --- |
| Starting tour | Distance-only nearest neighbor by default, with equal distances resolved to the lowest GeoNameID. `--initial id-order` gives an uninformed alternative, and `two_opt()` accepts any valid tour. |
| Improvement rule | `best` (default) applies the cheapest move of a full scan. `first` applies the first improving move and rescans from the start. |
| Ties | Scans run in ascending `(first, last)` order and later moves must be strictly cheaper, so the earliest move wins. There is no randomness. |
| Stopping rule | Stop when no reversal improves the cost by more than `1e-12`. |

The search terminates because every accepted move strictly lowers the cost, so no tour can repeat, and the number of tours is finite. The result is a local optimum with respect to single reversals, with no guarantee of global optimality. Nearest neighbor ignores risk and time, so a safety-weighted run begins from a tour chosen only for distance.

## Complexity

Let `n` be the selected city count and `k` the number of accepted moves.

- Building the distance matrix costs `O(n^2)` time and space. Nearest neighbor costs `O(n^2)`.
- A scan considers at most `(n - 1)(n - 2) / 2` reversals. Each costs `O(n^2)` in the worst case, because `evaluate_tour()` reschedules rests, so one scan costs `O(n^4)`. Classic distance-only 2-opt scans in `O(n^2)`; this extra factor is the price of time-dependent risk and optimal rests.
- Total time is `O(n^2 + (k + 1) * n^4)`. `k` depends on the instance and start, and no useful polynomial bound on it is claimed here.
- Auxiliary space is `O(n)` for the current and candidate tours and evaluations, or `O(n^2)` including the shared matrix.

These are worst-case bounds. Each rest-schedule scan stops at the first mandatory rest, which can make real runs cheaper. `first` has the same worst-case scan cost but can end a scan early. Reported runtime covers the search, including nearest-neighbor construction when no starting tour is supplied. It excludes CSV loading and matrix construction.

## Early observations

These come from single correctness runs on 2026-11-01, using all 43 cities, Kuala Lumpur as depot, and `alpha=0.4`, `beta=0.2`. **They are not experiments**: one instance, two departures, no repetition, and cross-sea legs included. They only show what is worth testing properly.

| Departure | 2-opt setting | Initial cost | Final cost | Accepted moves | Moves evaluated | Runtime |
| --- | --- | --- | --- | --- | --- | --- |
| 08:00 | best, nearest-neighbor | 0.13552 | 0.13220 | 11 | 10,332 | 3.85 s |
| 08:00 | best, id-order | 0.20145 | 0.13473 | 28 | 24,969 | 6.83 s |
| 08:00 | first, nearest-neighbor | 0.13552 | 0.13230 | 16 | 7,162 | 2.41 s |
| 08:00 | first, id-order | 0.20145 | 0.13251 | 100 | 11,008 | 3.25 s |
| 18:00 | best, nearest-neighbor | 0.13675 | 0.13343 | 11 | 10,332 | 3.75 s |
| 18:00 | best, id-order | 0.20267 | 0.13551 | 23 | 20,664 | 5.41 s |
| 18:00 | first, nearest-neighbor | 0.13675 | 0.13359 | 13 | 8,134 | 2.78 s |
| 18:00 | first, id-order | 0.20267 | 0.13428 | 121 | 13,421 | 3.92 s |

Beam Search with width 100 gave 0.14805 at 08:00 and 0.14523 at 18:00, in about 0.25 s. So on these two runs, 2-opt found cheaper tours but took roughly 10 to 27 times as long. The final cost also changed with both the start and the strategy.

## Usage and verification

From the repository root, using Python 3.10 or newer:

```bash
python3 two_opt.py --depot "Kuala Lumpur" \
  --cities "Ipoh" "Johor Bahru" "Kuantan" "Malacca" \
  --departure 18:00 --alpha 0.4 --beta 0.2 --strategy best --initial nearest-neighbor --output result.json
python3 -m unittest discover -s tests -v
```

City selection, defaults and shared JSON metadata match the Beam Search runner. The 2-opt JSON also records the strategy, accepted moves, evaluated moves, stopping rule, tie rule, starting route and starting totals.

The 23 tests in `tests/test_two_opt.py` pass. They check:

- starting tours and segment reversal;
- classic uncrossing when `alpha = 1`;
- the all-stops reversal, a change beyond the reversed segment, per-candidate rest schedules, and accepting a longer route;
- local optimality against an independent enumeration of reversals, for both strategies, both starts, three departures and five weightings on a seven-city subset;
- both strategies against a plain reference search, and never beating an exhaustive optimum;
- determinism, equal-cost termination, equal day/night scores, and all-night arrivals;
- invalid inputs, unchanged input tours and source data, agreement with Beam Search's evaluator and export, and a 43-city run that never drives through a night;
- the command line.

They do not assert that 2-opt reaches the optimum, and they are not comparative experiments.
