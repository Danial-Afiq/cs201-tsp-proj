# Safety-Aware Beam Search implementation

`beam_search.py` implements one of the team's two planned approaches. It uses only the Python standard library. The algorithm and scaling below are project implementation decisions, not additional assignment requirements. The shared `load_cities()`, `make_problem()`, and `evaluate_tour()` functions can be reused for 2-opt so comparisons use the same rules.

## Objective and time

For one instance, select `n >= 2` cities, including a depot. A valid tour starts at that depot, visits every other selected city exactly once, and returns to the depot.

```text
D = sum of Haversine distances over all n legs, including return
R = sum of arrival risks at the n - 1 non-depot stops
d_max = maximum pairwise distance among the selected cities
D_scaled = D / (n * d_max)
R_scaled = R / (100 * (n - 1))
cost = alpha * D_scaled + (1 - alpha) * R_scaled
```

Each leg is at most `d_max`, and each risk is between 0 and 100. Thus both components are bounded by 0 and 1 for complete tours. If all coordinates coincide, use a distance divisor of 1 km; distance and scaled distance are both zero. Scaling bounds depend only on the selected instance and stay fixed throughout the search. Prefixes also use these full-instance divisors. No beam-specific min/max normalisation is performed. Across different subsets the scales differ, so compare algorithms on identical instances and report raw totals alongside cost.

At each arrival, calculate:

```text
absolute_arrival_minutes = departure_minutes + cumulative_distance_km / 60 * 60
local_arrival_minutes = absolute_arrival_minutes modulo 1440
day if 420 <= local_arrival_minutes < 1140, otherwise night
arrival_risk = destination.day_risk or destination.night_risk
```

The two factors of 60 convert the fixed speed in km/h to minutes. At this speed, a kilometre takes one minute. Time is retained as an unrounded float; displayed seconds are truncated. Day counting and modulo handle midnight and multiple days. Service time is zero, and there is no waiting. The initial and final depot have no scored arrival risk, but return distance and return time are included. Crime Index is not used in the objective.

The distance matrix uses a spherical Haversine model with radius 6371 km, not road distances. GeoNames coordinates and the Numbeo scores in the master CSV are not altered. Numbeo scores describe perceptions rather than crime probabilities; see the README for source attribution, matching decisions, and data limitations.

## State and data structures

| Structure | Purpose |
| --- | --- |
| Immutable city records | Keep IDs, source metadata, coordinates, and safety/risk values together. |
| Symmetric distance matrix | Reuse geographical distances in search and full-tour evaluation. |
| Integer visited bit mask | Check membership and add a city without copying a Python set. |
| State with current city, accumulated distance/risk, and parent | Extend prefixes and reconstruct the winning route. Arrival time follows from distance. |
| Beam list and bounded heap via `heapq.nsmallest` | Retain up to `W` candidates across all parents at each depth. |
| Generation counter | Resolve equal costs deterministically without comparing state objects. |

City indices are assigned by ascending GeoNameID. Every parent expands unvisited cities in that order. The serial counter resolves ties by generation order. There is no randomness. Runtime measurements can vary, while route selection is reproducible for the same inputs.

Do not merge states solely because `(visited_mask, current_city)` matches. Different prefix distances yield different arrival times, so the remaining stops can incur different risks. The implementation preserves these alternatives within the beam-width limit.

## Search and ranking

At each depth, generate every one-city extension of every retained prefix. Select the globally cheapest `W` candidates, rather than keeping `W` children separately for each parent. Before the last depth, the ranking is the accumulated prefix cost; no future-risk or remaining-distance estimate is added. At the last depth, add the distance back to the depot **before selecting the final beam**. This ensures final ranking uses closed-tour cost.

```text
beam = [state at depot with zero distance/risk and depot marked visited]
for depth = 1 to n - 1:
    candidates = a stream
    for state in beam:
        for next city not in state.visited:
            distance = state.distance + distance_matrix[state.current][next]
            time = departure + distance / speed converted to minutes
            risk = state.risk + destination risk selected from time
            child = state(next, updated mask, distance, risk, parent=state)
            ranked_distance = distance
            if depth == n - 1:
                ranked_distance += distance_matrix[next][depot]
            yield (weighted_cost(ranked_distance, risk), generation_number, child)
    beam = up to W cheapest candidates, ordered by rank and generation number
reconstruct beam[0] by following parent pointers
append depot and evaluate the entire closed tour with evaluate_tour()
```

This is a heuristic. A prefix with an expensive early arrival can later produce a better route, yet be pruned. Returning more alternatives costs time and memory, and finite beam width does not guarantee an optimum. The search has exactly `n - 1` extension levels and needs no separate stopping threshold.

## Complexity

Let `n` be the selected city count and `W` the beam width. Under the usual unit-cost assumptions for arithmetic and bit masks:

- Building the distance matrix costs `O(n^2)` time and space.
- At most `W` parents are expanded per depth. There are at most `O(W * n^2)` generated candidates across all depths.
- Selecting up to `W` candidates with a bounded heap costs `O(log(W + 1))` per candidate in the worst case, giving total time `O(n^2 + W * n^2 * log(W + 1))`.
- Candidate generation is streamed, so all children are not stored together. Retained parent chains contain at most `O(W * n)` state objects, giving auxiliary storage of `O(n^2 + W * n)` objects/numeric slots, including the matrix.
- Final reconstruction and evaluation cost `O(n)` time and space.

Python integers are arbitrary precision: a visited mask contains `n` bits. For very large instances, bit operations take more than constant time, and mask storage contributes `O(W * n^2)` bits across the parent chains. The unit-cost analysis is appropriate for the current 43-location dataset. The bounds are upper bounds; a wide beam may have fewer candidates than `W`. An unpruned beam can enumerate factorially many tours, so choosing factorial `W` is only suitable for tiny reference instances. Runtime in the result measures search plus final evaluation, excluding CSV loading and matrix construction; memory is not measured by the runner.

## Usage and verification

From the repository root, using Python 3.10 or newer:

```bash
python3 beam_search.py --depot "Kuala Lumpur" \
  --cities "Ipoh" "Johor Bahru" "Kuantan" "Malacca" \
  --departure 18:00 --alpha 0.5 --beam-width 100 --output result.json
python3 -m unittest discover -s tests -v
```

Names and GeoNameIDs are accepted; the depot is automatically included. Without `--cities`, all 43 master records are selected. For realistic delivery experiments, choose and justify a regional subset rather than interpreting cross-sea Haversine legs as driving routes. A JSON output records the dataset SHA-256, selected IDs, model constants, scaling divisors, search parameters, implementation version, every arrival, raw/scaled totals, and search statistics.

The 23 automated tests pass. They cover CSV validation and leading-zero administrative codes, Haversine checks, exact 07:00/19:00 boundaries, no waiting/service, return-depot handling, route-order effects, midnight/multi-day travel, coincident coordinates, objective endpoints, valid tours, deterministic ties, invalid inputs, and low beam widths. An unpruned beam matches exhaustive optimal cost on a six-city subset for nine departure/alpha combinations. A 43-city smoke check also produces a valid closed tour. These checks do not establish the quality of a narrow beam or replace the required comparative experiments with 2-opt.
