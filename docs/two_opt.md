# Safety-Aware 2-opt implementation

`two_opt.py` implements the second of the team's two planned approaches. It uses only the Python standard library. The design choices below are project implementation decisions, not additional assignment requirements. The instance, scaling, objective, rest rules and full-tour evaluation come from `beam_search.py`, so both approaches score routes by the same rules; see the [Beam Search notes](beam_search.md) for the objective, time and rest model.

## Handover

**Status on 2026-11-06:** the 2-opt handover is in place, and the comparison with Beam Search has been run. `experiments/compare_two_opt.py` writes `experiments/results/comparison.json`. `python3 -m unittest discover -s tests -v` passes 57 tests: 26 Beam Search, 23 2-opt, and 8 checks on the comparison script. The command-line defaults stay `best` and `nearest-neighbor`.

**What was added or changed**

| File | Change | What it does |
| --- | --- | --- |
| `two_opt.py` | New | Runs 2-opt on the current overnight-rest model, with the same instance options and JSON metadata as Beam Search. This replaces "2-opt not implemented". |
| `tests/test_two_opt.py` | New | Adds 23 tests for move acceptance, rest handling, local optimality, determinism, invalid input, and agreement with the shared evaluator. |
| `docs/two_opt.md` | New | Records the design, pseudocode, complexity, verification and this handover. |
| `README.md`, `AGENTS.md`, `docs/beam_search.md` | Updated | Replace the "2-opt is future work" wording and record the new status, run instructions and test counts. |
| `beam_search.py` | Docstring only | Says 2-opt now uses the shared model. Search and evaluator logic did not change. |
| `.gitignore` | New | Keeps Python bytecode and virtual environments out of commits. |
| `experiments/compare_two_opt.py` | New | Runs 2-opt and Beam Search on the same instance and writes the JSON record. |
| `experiments/results/comparison.json` | New | The experiment record: every trial, the summaries, the timing, and the memory peaks. |
| `tests/test_compare_two_opt.py` | New | Checks the comparison script. It does not re-run the full study. |

**What this round did**

1. Compared `two_opt()` and `beam_search()` on one shared `make_problem()` call per instance. The record is [the experiment section](#experiments).
2. Measured the gap to the exhaustive optimum on 9-city instances, and on the 6-city East Malaysia subset.
3. Kept `best` and `nearest-neighbor`. On the 200-trial study that setting had the lowest mean gap.
4. Did not add another starting tour. After 2-opt, the distance-only nearest-neighbor start was already within 0.08% of optimal on average.
5. Measured memory with `tracemalloc`, separately from the `O(n^4)` bound.
6. Did not change the shared evaluator. A 43-city run takes about 8 seconds here, which is fast enough for the study.
7. The tables below are the presentation numbers. The pseudocode and complexity further down are unchanged.

**Still open**

The pseudocode and complexity below are ready for the presentation. The numbers have to come from the experiment section. Anyone presenting has to be able to explain the losses, especially the time-only 43-city case.

**Known limits**

- The final tour depends on the start and strategy, and it is only a local optimum for single reversals.
- `two_opt.py` repeats the Beam Search console output code instead of sharing it. This kept `beam_search.py` unchanged. The JSON sections are shared, so they cannot drift apart.

## Experiments

Run from the repository root. The full study takes about half an hour, because each 9-city optimum tries all `8! = 40,320` stop orders.

```bash
python3 experiments/compare_two_opt.py
python3 experiments/compare_two_opt.py --quick   # one trial, skips the 37-city and 43-city runs
```

Both algorithms in a row receive the same `make_problem()` result. A cost from one subset, or one weight pair, is not comparable with a cost from another, because the scaling divisors change. Raw kilometres, risk, and minutes are stored so those rows can still be read. The optimum is every stop order scored by `evaluate_tour()`. Gap is `(cost - optimum) / optimum`. A search that beat the optimum would have stopped the script.

The run is Python 3.14.3 on macOS arm64. Dataset SHA-256 is `47397b35b60d0e5a9d266d121afa65a47b5831c9c2a28a89955ba6df75db077f`. Seeds and pools are in the JSON. Runtimes are this machine.

The 19-city pool is every Peninsular master city with at least 15 Numbeo contributors. In this CSV, East Malaysia is `admin1_code` 11 (Bintulu, Kuching, Miri, Sibu), 15 (Labuan), and 16 (Kota Kinabalu). The Klang Valley subset is `admin1_code` 12, 14, and 17: the Selangor group, Kuala Lumpur, and Putrajaya, 15 cities. The Peninsular subset is the other 37 cities. The all-43 subset includes cross-sea Haversine legs and has to be described that way.

### Gap on 9-city instances

200 trials, seed 201, `alpha=0.4`, `beta=0.2`. Each trial draws 9 cities from the 19-city pool. The first drawn city is the depot. The departure is a random choice of 06:00, 10:00, 14:00, or 18:00. This run drew 06:00 forty-eight times, 10:00 fifty-two times, 14:00 fifty-four times, and 18:00 forty-six times.

| Method | Mean gap | Median gap | Max gap | Optimal | Mean runtime |
| --- | --- | --- | --- | --- | --- |
| 2-opt `best`, nearest-neighbor | 0.08% | 0.00% | 2.11% | 165/200 | 0.007 s |
| 2-opt `best`, id-order | 0.21% | 0.00% | 5.16% | 148/200 | 0.014 s |
| 2-opt `first`, nearest-neighbor | 0.16% | 0.00% | 3.22% | 149/200 | 0.005 s |
| 2-opt `first`, id-order | 0.34% | 0.00% | 5.13% | 135/200 | 0.008 s |
| Beam width 1 | 6.07% | 4.47% | 26.27% | 4/200 | under 0.001 s |
| Beam width 20 | 3.29% | 1.53% | 21.04% | 30/200 | 0.003 s |
| Beam width 100 | 2.30% | 0.94% | 19.41% | 48/200 | 0.014 s |
| Nearest-neighbor baseline | 3.22% mean | | | | |

`best` + nearest-neighbor was tied for the cheapest 2-opt cost on 174 of 200 trials. A tie counts for every setting that matches that cost. Against beam width 100 it was cheaper on 141 trials, tied on 55, and more expensive on 4. Against width 20 the split was 162 / 37 / 1. Against width 1 it was 196 / 4 / 0. Beam width 1 was never strictly cheaper.

The four losses are small. Trial 56 (Malacca depot, 06:00) differs only past the fifth decimal, a 0.002% gap against an optimal beam tour. Trial 86 (Petaling Jaya, 14:00) is 0.11% above optimal while the beam tour is optimal. Trial 43 (Petaling Jaya, 10:00) is 0.74% above optimal against the beam's 0.36%. Trial 92 (Cyberjaya, 14:00) is the largest: 1.25% against the beam's 0.92%.

A separate 40-trial study, seed 202, uses 08:00 only, because 08:00 is the command-line default and was not in the four clocks above. `best` + nearest-neighbor mean gap is 0.05% (34/40 optimal, max 0.88%). Beam width 100 is 2.56% (19/40 optimal). Head to head: 2-opt cheaper on 20, tie on 19, beam cheaper on 1. That one loss is trial 32, where the beam tour is optimal and 2-opt is 0.60% above it.

### Other weights, still on 9 cities

20 city samples, seed 203. Departures cycle through 06:00, 08:00, 10:00, 14:00, and 18:00, four times each. Each sample is solved at five weight pairs, and each pair has its own optimum. The 2-opt column is `best` + nearest-neighbor.

| Weights | 2-opt mean gap | 2-opt optimal | Beam 100 mean gap | Beam 100 optimal | Cheaper / tie / beam cheaper |
| --- | --- | --- | --- | --- | --- |
| 0.4, 0.2 (default) | 0.01% | 17/20 | 2.48% | 7/20 | 12 / 7 / 1 |
| distance only (1, 0) | 0.01% | 19/20 | 6.66% | 9/20 | 11 / 9 / 0 |
| time only (0, 1) | 0.18% | 17/20 | 3.75% | 11/20 | 9 / 10 / 1 |
| risk only (0, 0) | 0.00% | 20/20 | 0.00% | 20/20 | 0 / 20 / 0 |
| mixed (0.5, 0.05) | 0.00% | 19/20 | 3.01% | 5/20 | 15 / 5 / 0 |

Risk-only ties on every sample. With the whole objective on risk, optional rests can move arrivals into the day, so different orders often share the same best risk. Distance-only is where 2-opt is strongest: it reached the optimum on 19 of 20 samples. Beam width 100's mean gap there is 6.66%, and beam width 1's is 6.79%. A wider beam is not guaranteed to be better. The time-only row is the soft spot: beam width 100 was cheaper on 1 of 20 samples.

### Larger fixed subsets

No exhaustive optimum once there are more than 9 cities. East Malaysia has 6 cities, so that subset does have an optimum, and both algorithms reach it at the default weights (cost 0.242559 at 08:00 and 0.246702 at 18:00, depot Kuching).

Default weights, `best` + nearest-neighbor against beam width 100:

| Subset | Depot | Depart | 2-opt cost | Beam cost | 2-opt km, risk, minutes | Beam km, risk, minutes |
| --- | --- | --- | --- | --- | --- | --- |
| Klang Valley, 15 | Kuala Lumpur | 08:00 | 0.199921 | 0.216569 | 155.4 km, 416.9, 155 min | 187.4 km, 416.9, 187 min |
| Klang Valley, 15 | Kuala Lumpur | 18:00 | 0.206385 | 0.223346 | 155.4 km, 416.9, 879 min | 188.0 km, 416.9, 911 min |
| Peninsular, 37 | Kuala Lumpur | 08:00 | 0.132959 | 0.153870 | 1688 km, 882.6, 3154 min | 2667 km, 897.6, 4591 min |
| Peninsular, 37 | Kuala Lumpur | 18:00 | 0.133832 | 0.157711 | 1697 km, 891.5, 3052 min | 2660 km, 913.0, 5474 min |
| Peninsular, 37 | Johor Bahru | 08:00 | 0.133380 | 0.148415 | 1666 km, 888.4, 3203 min | 2324 km, 898.4, 4556 min |
| Peninsular, 37 | Johor Bahru | 18:00 | 0.133145 | 0.147540 | 1666 km, 888.4, 3111 min | 2308 km, 897.2, 4368 min |
| All 43, cross-sea | Kuala Lumpur | 08:00 | 0.132203 | 0.148046 | 4563 km, 1020.2, 7464 min | 6651 km, 1048.9, 8868 min |
| All 43, cross-sea | Kuala Lumpur | 18:00 | 0.133426 | 0.145227 | 4563 km, 1020.2, 8304 min | 6027 km, 1020.2, 11082 min |

On distance-only, the clock does not matter, so 08:00 and 18:00 produce the same tour. All 43 cities: 2-opt 4378 km against beam width 100 at 5412 km. Peninsular: 1666 km against 2127 km.

The loss to report: time-only, all 43 cities, departure 08:00. Beam width 100 costs 0.045841 (5169 km, risk 1066.2, 6299 min). 2-opt and beam width 1 both cost 0.053312 (4832 km, risk 1079.6, 7325 min). The wider beam found a longer route that finishes sooner, and time is the whole objective. At 18:00 on the same cities the result flips: 2-opt 0.048945 (6725 min) beats beam width 100 at 0.059425 (8165 min). Risk-only ties on the large subsets as well.

### Runtime and memory

Median of 3 runs, default weights, departure 08:00. The problem is built before the clock starts. 2-opt times include nearest-neighbor construction, matching the command line.

| Subset | Cities | 2-opt `best`, nearest-neighbor | 2-opt `first`, nearest-neighbor | Beam width 1 | Beam width 100 |
| --- | --- | --- | --- | --- | --- |
| One 9-city sample | 9 | 0.005 s | 0.004 s | under 0.001 s | 0.014 s |
| Klang Valley | 15 | 0.140 s | 0.120 s | under 0.001 s | 0.050 s |
| East Malaysia | 6 | 0.001 s | 0.001 s | under 0.001 s | 0.004 s |
| Peninsular | 37 | 2.60 s | 3.12 s | 0.005 s | 0.37 s |
| All 43 | 43 | 7.88 s | 4.84 s | 0.005 s | 0.47 s |

The three 43-city samples for `best` + nearest-neighbor were 9.80 s, 7.83 s, and 7.88 s. Quote the median. On this machine that setting is about 17 times the beam-width-100 time on all 43 cities, and about 7 times on the Peninsular subset.

`tracemalloc` peak during the search call, median of 3, departure 08:00, after the distance matrix exists:

| Subset | 2-opt `best`, nearest-neighbor | Beam width 100 |
| --- | --- | --- |
| 9-city sample | 4,840 bytes | 101,472 bytes |
| Klang Valley | 8,920 bytes | 125,072 bytes |
| East Malaysia | 3,768 bytes | 70,400 bytes |
| Peninsular | 25,176 bytes | 213,472 bytes |
| All 43 | 29,832 bytes | 198,096 bytes |

These are Python allocations inside that call. They are not the process's total memory, and they are not the `O(n^4)` time bound. 2-opt holds one tour. Beam Search holds up to `W` partial tours. That is why the beam peak is larger.

### What was decided

`best` and `nearest-neighbor` stay the defaults. Their mean gap, 0.08%, is the lowest of the four 2-opt settings. The next setting, `first` + nearest-neighbor, is 0.16%. The script recommends a change only when another setting is better by more than 0.5 percentage points, so this result keeps the current default. The 08:00 study agrees. `id-order` is the weaker start.

No risk-aware or multi-start tour was added. A Beam Search tour can already be passed as `initial_tour`, and a test checks that 2-opt does not make it worse. Using that as the only reported start would stop the two approaches from being independent.

The shared evaluator was not changed.

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

These come from single runs on 2026-11-01, using all 43 cities, Kuala Lumpur as depot, and `alpha=0.4`, `beta=0.2`. The all-43 default-weight costs match the later study (`0.132203` and `0.133426` for `best` + nearest-neighbor, `0.148046` and `0.145227` for beam width 100). The runtimes in this table are from that older machine. Use the [experiment runtimes](#runtime-and-memory) instead.

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

They do not assert that 2-opt reaches the optimum. The comparison is the experiment section above, not these tests. `tests/test_compare_two_opt.py` checks the comparison script's gap rule, sampling, and summaries. It does not re-run the 200-trial study.
