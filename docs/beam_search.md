# Safety-Aware Beam Search implementation

`beam_search.py` implements one of the team's two planned approaches. It uses only the Python standard library. The algorithm, rest policy and scaling below are project implementation decisions, not additional assignment requirements. The shared `load_cities()`, `make_problem()`, `evaluate_tour()` and `schedule_tour()` functions can be reused for 2-opt so comparisons use the same rules.

## Objective and time

For one instance, select `n >= 2` cities, including a depot. A valid tour starts at that depot, visits every other selected city exactly once, and returns to the depot.

```text
D = sum of Haversine distances over all n legs, including return
T = minutes from departure to the final depot arrival, including rests
R = sum of arrival risks at the n - 1 non-depot stops
d_max = maximum pairwise distance among the selected cities
D_scaled = D / (n * d_max)
T_scaled = T / (n * (d_max_minutes + 1440))
R_scaled = R / (100 * (n - 1))
cost = alpha * D_scaled + beta * T_scaled + (1 - alpha - beta) * R_scaled
```

Each leg is at most `d_max` (driving time `d_max_minutes`), each of the `n` departures waits less than a day, and each risk is between 0 and 100. Thus all three components are bounded by 0 and 1 for complete tours. If all coordinates coincide, use a distance divisor of 1 km; distance and scaled distance are both zero. Scaling bounds depend only on the selected instance and stay fixed throughout the search. Prefixes also use these full-instance divisors. No beam-specific min/max normalisation is performed. Across different subsets the scales differ, so compare algorithms on identical instances and report raw totals alongside cost.

At each arrival, calculate:

```text
local_clock = segment_start + minutes driven since segment_start
day if 420 <= local_clock mod 1440 < 1140, otherwise night
arrival_risk = destination.day_risk or destination.night_risk
```

A segment starts at the departure time, or at 07:00 after a rest. At 60 km/h, a kilometre takes one minute. Time is kept as an unrounded float; displayed seconds are truncated. Day counting and modulo handle midnight and multiple days. Service time is zero. The initial and final depot have no scored arrival risk, but return distance and return time are included. Crime Index is not used in the objective.

### Rests

Every rest lasts until the next 07:00, at the current stop. Before each leg:

| Situation at the stop | Options |
| --- | --- |
| Night (19:00 to 07:00) | Mandatory rest (`night`). |
| Day, but the leg would still be underway at the next 07:00 | Mandatory rest (`long leg`). From exactly 07:00 any leg may start. |
| Day, leg is not the return | Leave now, or take an optional rest (`chosen`). |
| Day, leg is the return | Leave now. The return has no arrival risk, so resting only adds time. |

These rules mean the driver never drives through a whole night. Earlier, under the no-waiting rule, long evening legs crossed the night and arrived after dawn, so they avoided night risk without any penalty. Driving into the evening and arriving before 07:00 is still allowed and is charged night risk. Legs longer than 720 km (12 hours) cannot avoid a night arrival; in this dataset they are cross-sea Haversine legs.

`beta` makes optional rests cost something. With `beta = 0`, resting would be free, avoidable night arrivals would disappear, and total risk would be nearly the same for every route order.

### Rest schedule for a fixed tour

`schedule_tour(problem, tour, rest_stops)` evaluates a tour with the optional rests listed by tour position. `evaluate_tour(problem, tour)` chooses those rests to minimise cost with dynamic programming. Every rest ends at 07:00, so the cheapest continuation after resting at position `k` does not depend on the day. Compute it once per position, from the end of the tour backwards:

```text
best_after_rest[k] = minimum over the next rest position j > k (or none) of
    risk and time cost of driving from k at 07:00 to j, + rest at j, + best_after_rest[j]
```

Each scan stops at the first mandatory rest. This costs `O(n^2)` time and `O(n)` space per tour. Ties prefer driving on. Distance does not depend on rests, so only time and risk enter this choice.

## State and data structures

| Structure | Purpose |
| --- | --- |
| Immutable city records | Keep IDs, source metadata, coordinates, and safety/risk values together. |
| Symmetric distance matrix | Reuse geographical distances in search and full-tour evaluation. |
| Integer visited bit mask | Check membership and add a city without copying a Python set. |
| State with current city, accumulated distance/risk/elapsed time, segment start, minutes driven since, and parent | Extend prefixes and reconstruct the winning route. The local clock is segment start plus minutes driven, summed in the same order as in the evaluator, so both classify boundary arrivals identically. |
| Beam list and bounded heap via `heapq.nsmallest` | Retain up to `W` candidates across all parents at each depth. |
| Generation counter | Resolve equal costs deterministically without comparing state objects. |
| Per-position arrays in `evaluate_tour()` | Store the best cost and next rest after resting at each tour position. |

City indices are assigned by ascending GeoNameID. Every parent expands unvisited cities in that order; for each city, leaving now is generated before resting. Equal costs prefer less elapsed time, then generation order. There is no randomness. Runtime measurements can vary, while route selection is reproducible for the same inputs.

Do not merge states solely because `(visited_mask, current_city)` matches. Different clocks give different arrival times, so the remaining stops can incur different risks and need different rests. The implementation preserves these alternatives within the beam-width limit.

## Search and ranking

At each depth, generate every one-city extension of every retained prefix, once for each allowed departure option (leave now or rest until 07:00). Select the globally cheapest `W` candidates, rather than keeping `W` children separately for each parent. Before the last depth, the ranking is the accumulated prefix cost; no future-risk or remaining-distance estimate is added. At the last depth, add the return leg's distance and time, including any mandatory rest before it, **before selecting the final beam**. This ensures final ranking uses closed-tour cost.

```text
beam = [state at depot, zero totals, segment starting at the departure time]
for depth = 1 to n - 1:
    candidates = a stream
    for state in beam:
        for next city not in state.visited:
            for wait in allowed waits before the leg (0, and/or the time until 07:00):
                restart the segment at 07:00 if wait > 0
                arrival clock = segment start + driven minutes + leg minutes
                risk = state.risk + destination risk selected from the arrival clock
                elapsed = state.elapsed + wait + leg minutes
                child = state(next, updated mask, distance, risk, elapsed, segment, parent=state)
                if depth == n - 1:
                    add the return distance, and its time including any mandatory rest
                yield (weighted_cost, elapsed, generation_number, child)
    beam = up to W cheapest candidates
reconstruct beam[0] by following parent pointers
append depot and evaluate the closed tour with evaluate_tour(), which picks its cheapest rests
```

The final evaluation can only match or improve on the rest choices the beam made for that tour. This is a heuristic. A prefix with an expensive early arrival can later produce a better route, yet be pruned. When `beta = 0`, each rest branch can cost the same as leaving now and use up beam slots. Finite beam width does not guarantee an optimum. The search has exactly `n - 1` extension levels and needs no separate stopping threshold.

## Complexity

Let `n` be the selected city count and `W` the beam width. Under the usual unit-cost assumptions for arithmetic and bit masks:

- Building the distance matrix costs `O(n^2)` time and space.
- At most `W` parents are expanded per depth. Each generates at most two children per unvisited city, giving at most `O(W * n^2)` candidates across all depths.
- Selecting up to `W` candidates with a bounded heap costs `O(log(W + 1))` per candidate in the worst case. With the final `O(n^2)` rest-schedule evaluation, total time is `O(n^2 + W * n^2 * log(W + 1))`.
- Candidate generation is streamed, so all children are not stored together. Retained parent chains contain at most `O(W * n)` state objects, giving auxiliary storage of `O(n^2 + W * n)` objects/numeric slots, including the matrix.
- `evaluate_tour()` costs `O(n^2)` time and `O(n)` space. A 2-opt implementation that re-evaluates full tours pays this per move.

Python integers are arbitrary precision: a visited mask contains `n` bits. For very large instances, bit operations take more than constant time, and mask storage contributes `O(W * n^2)` bits across the parent chains. The unit-cost analysis is appropriate for the current 43-location dataset. The bounds are upper bounds; a wide beam may have fewer candidates than `W`. An unpruned beam enumerates every (order, rest choice) combination, up to `(n - 1)! * 2^(n - 1)` leaves, so such widths are only suitable for tiny reference instances. Runtime in the result measures search plus final evaluation, excluding CSV loading and matrix construction; memory is not measured by the runner.

## Usage and verification

From the repository root, using Python 3.10 or newer:

```bash
python3 beam_search.py --depot "Kuala Lumpur" \
  --cities "Ipoh" "Johor Bahru" "Kuantan" "Malacca" \
  --departure 18:00 --alpha 0.4 --beta 0.2 --beam-width 100 --output result.json
python3 -m unittest discover -s tests -v
```

Names and GeoNameIDs are accepted; the depot is automatically included. Without `--cities`, all 43 master records are selected. For realistic delivery experiments, choose and justify a regional subset rather than interpreting cross-sea Haversine legs as driving routes. A JSON output records the dataset SHA-256, selected IDs, model constants and rest policy, weights and scaling divisors, search parameters, implementation version, every arrival with its rest, raw/scaled totals, and search statistics.

The 26 automated tests pass. They cover CSV validation and leading-zero administrative codes, Haversine checks, exact 07:00/19:00 boundaries, mandatory night and long-leg rests, optional rests that trade time for risk, return-depot handling, route-order effects, midnight/multi-day travel, coincident coordinates, objective endpoints with all three weights, valid tours and rest positions, deterministic ties, invalid inputs, and low beam widths. For every order of a five-city subset, under 12 departure/weight combinations, the evaluator's rest schedule matches brute force over all rest subsets. An unpruned beam matches the exhaustive optimal cost on a six-city subset for 15 departure/weight combinations. A 43-city smoke check produces a valid closed tour that never drives through a night. These checks do not establish the quality of a narrow beam or replace the required comparative experiments with 2-opt.
