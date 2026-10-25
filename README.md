# SafeRoute — Safety-Aware Travelling Salesperson Problem

CS201 Data Structures & Algorithms — *Beyond the Classic TSP*.

> **Status:** Planning/documentation. No algorithms or experiments have been implemented or verified in this repository yet.

## Problem in simple English

A delivery driver carrying valuable goods must visit selected Malaysian cities once and return to the starting city. The shortest route isn't always the most desirable: a different visiting order may let the driver reach a city in daylight instead of at night. We therefore compare **total travel distance** and **estimated day/night safety**.

The project uses **one modified TSP problem and two different solutions**:

| | Approach A — Safety-Aware 2-opt | Approach B — Safety-Aware Beam Search |
|---|---|---|
| Main idea | Build a full tour, then reverse sections to improve it | Keep several promising partial tours while building routes |
| Style | Local search | Bounded heuristic search |
| Key data structures | Array/list and distance matrix | Bounded heap / priority queue, bitmask, parent-pointer states and distance matrix |
| Strength | Straightforward route improvement | Explores multiple possibilities instead of committing immediately |
| Limitation | Can stop at a local optimum | Beam pruning can discard the eventual best route |
| Optimality guaranteed? | No | No |

## Inputs, output and scoring

**Inputs:** a chosen depot; selected GeoNames cities; distance matrix; **one base danger score (0–100) per city**; departure time; fixed assumed speed of **60 km/h**; safety weight `lambda`; and beam width `k` for Beam Search.

**Output:** a complete tour `depot -> each delivery city exactly once -> depot`, with total kilometres, time-dependent danger score and combined cost.

### Agreed assumptions (apply identically to both algorithms)

| # | Assumption | How we implement it |
| --- | --- | --- |
| 1 | Crime risk is higher at night | A city's nighttime danger is **1.5 ×** its daytime/base danger score. This is **our assumption**, not a measured effect. |
| 2 | Each city has a different danger score | Assign each city a **base danger score from 0–100**, using available crime data or **clearly labelled simulated values**. |
| 3 | Day and night have fixed hours | **Day:** 07:00–18:59; **Night:** 19:00–06:59 (Malaysia local time). |
| 4 | Driver travels at a constant speed | Use **60 km/h** for all trips to estimate arrival times. |
| 5 | Time spent delivering in each city is negligible | **0 minutes per stop**; the driver leaves immediately upon arrival. |
| 6 | Driver cannot wait until morning | **No waiting:** the driver immediately continues to the next city, even at night. |
| 7 | Safety depends on city and arrival time | Apply a risk score **when arriving at each city**, not for individual roads or travel legs. |

### Shared scoring model

```text
baseDanger[city]  = input value from 0 to 100
nightDanger[city] = 1.5 * baseDanger[city]
arrivalDanger     = baseDanger[city] (day) OR nightDanger[city] (night)

travelTimeHours = distanceKm / 60
arrivalTimeNext = arrivalTimeCurrent + travelTimeHours
# delivery time = 0, so departureTimeNext = arrivalTimeNext

D = distance of every leg, including the final return to depot
R = sum of arrivalDanger for each delivery city (NOT the returning depot)
combinedCost = D + lambda * R
```

Example: for a city with base danger **60**, arriving at 2 PM contributes **60** danger points, while arriving at 9 PM contributes **90**. A base score of 80 would give 120 at night: that is allowed because these values are **relative risk penalties, not percentages/probabilities**. The **base** index is 0–100, not necessarily the nighttime penalty.

Here `lambda` converts danger points into **kilometre-equivalent cost**; e.g., `lambda = 2` makes one danger point count as 2 km in the scoring formula. Vary `lambda` in experiments rather than claiming it is a true monetary risk.

**Important:** If all mandatory cities are visited once with fixed danger scores, the risk sum is constant for every route. **Changing the score at night** makes the visiting order matter whenever routes produce different day/night arrival patterns. If all deliveries occur in the same period, risk may still be constant.

Times should use Malaysia local time, wrap correctly past midnight, and respect the exact **07:00 / 19:00** boundaries. Straight-line Haversine distance divided by 60 km/h is a **simulation**, not a road-driving ETA.

### Scoring illustration (made-up numbers)

| Tour | Distance | Total danger | Cost with `lambda=2` |
|---|---:|---:|---:|
| Route X | 500 km | 80 | 660 |
| Route Y | 540 km | 45 | **630** |

Route Y is preferred under these assumptions despite being longer.

## Data and provenance

**Primary data:** Lecturer-provided Malaysia GeoNames `MY.txt`. Filter to populated places (`feature class P`), choose and justify a manageable subset (initially about 8–12 cities), and retain GeoNameID, name, latitude and longitude. Optionally retain population. Compute a pairwise **Haversine straight-line** distance matrix; never label it as actual road distance.

**Supplemental danger scores:** [Numbeo city-level Crime Index pages](https://www.numbeo.com/crime/country_result.jsp?country=Malaysia), where available, can supply a city's **base 0–100 danger score**. Use *one clearly documented base score* for each city. Numbeo values describe survey-reported/perceived crime, **not the probability of robbery or the safety of a delivery truck**. Save source URL, retrieval/update date, contributor count if available, and exact city match.

**Do not use Numbeo's separate day/night walking-safety scores to calculate the algorithm's night multiplier.** Under our agreed model, **night danger is always computed as `1.5 × baseDanger`**. The 1.5 factor is a documented **simulation assumption**, not something verified by Numbeo. Separate Numbeo day/night values could be discussed as context, but must not silently replace this formula.

If a city has no matching base index, exclude it or explicitly use **simulated** base-danger data in a separate, documented experiment. Do not silently fill missing data, invent measurements, or scrape/redistribute data contrary to source terms.

## Approach A — Safety-Aware 2-opt

1. Build a **valid full tour** using distance-only Nearest Neighbor as an initial baseline.
2. Calculate the full tour's cost, including every arrival time and the return-to-depot distance.
3. Try reversing every segment that does not include the two depot endpoints.
4. Recalculate the **entire route** after each reversal, since a changed order changes later arrival times and whether the base danger is multiplied by 1.5.
5. Keep the best strict improvement in each pass. Stop when no tested reversal helps (or at a documented pass limit).

Example of a candidate reversal:

```text
Before: KL -> Shah Alam -> Seremban -> Ipoh -> JB -> KL
After:  KL -> Shah Alam -> Ipoh -> Seremban -> JB -> KL
```

Whether it really helps depends on recomputed distance and arrival-time danger—not on the visual order alone.

```text
route = nearestNeighborByDistance(cities, depot)
repeat:
    best = route
    for every pair (i,j) of non-depot positions, i < j:
        candidate = reverse(route[i..j])
        if evaluateFullTour(candidate) < evaluateFullTour(best):
            best = candidate
    if best did not improve on route: break
    route = best
return route
```

**DSA:** array or `ArrayList<Integer>` for route; `boolean[]` to track the initial tour's visited cities; shared `double[][]` distance matrix. With `n` cities and `p` passes, simple full-route evaluation per reversal is **O(p n³)**; nearest-neighbor initialization is **O(n²)**. Distance matrix occupies **O(n²)** memory. Include initialization in end-to-end runtime.

## Approach B — Safety-Aware Beam Search

Beam Search builds possible routes step by step but keeps only the **best `k` partial routes per depth**.

A partial state holds: last city, visited-city bitmask, accumulated distance, danger and score, current clock time, and parent pointer (to reconstruct the route without copying full lists for every child).

1. Begin at the depot with no delivery cities visited.
2. From each retained partial route, generate one child for each unvisited city.
3. Calculate each child's arrival time, danger, distance and cost.
4. Give each child a ranking value, initially:

   `estimatedTotal = costSoFar + straightLineDistance(currentCity, depot)`.

   This is a **weak, optimistic remaining-distance estimate**; it ignores future stops and risk. It helps ranking but does not guarantee an optimal tour.
5. Retain at most `k` lowest-ranked children using a **bounded max-heap**. Its root stores the *worst retained child*, so a better candidate can replace it in `O(log k)`.
6. Repeat until all selected delivery cities are visited. Add the return-to-depot leg and select the lowest **actual completed-tour cost**.

Illustrative pruning when `k = 2`:

```text
KL -> Shah Alam -> Seremban     rank 210   KEEP
KL -> Ipoh -> Shah Alam         rank 235   KEEP
KL -> JB -> Seremban            rank 310   DROP
```

The ranks above are fictional. A discarded route **might** have led to a better final tour. A beam width of 1 is greedy-like but is not necessarily equivalent to Nearest Neighbor.

```text
beam = [initial depot state]
while delivery cities remain:
    nextBeam = boundedMaxHeap(capacity = k)
    for state in beam:
        for city not yet visited in state:
            child = extend(state, city)  // new arrival time and risk
            priority = child.costSoFar + directDistance(child.lastCity, depot)
            retainAmongBestK(nextBeam, child, priority)
    beam = contents(nextBeam)
return lowest-cost completed route after including return to depot
```

**DSA:** `PriorityQueue` configured as a **max-heap** for bounded top-`k` selection; bitmask for visited cities; parent-linked states; distance matrix/graph. With constant-time candidate ranking and up to `k` states per layer, expect **O(k n² log(k+1))** time for a straightforward bounded-heap approach and up to **O(kn + n²)** retained-state/matrix space. A more expensive heuristic changes complexity; analyse the *implemented* version. For very large `n`, use a `BitSet` rather than a single integer mask.

## Fair testing

Use identical city sets, base danger scores, departure times, the agreed fixed speed/day-night/zero-stop-time assumptions, and lambda for all comparisons. Compare a **distance-only Nearest Neighbor baseline** (not a third redesigned solution), 2-opt, and Beam Search. Record:

- Tour, total distance, total arrival danger and combined cost.
- End-to-end runtime, candidate evaluations, 2-opt passes, beam-pruned candidates and memory if measured.
- Configuration: selected GeoNames IDs, dataset provenance, `lambda`, start time, beam width, implementation version and random seed (if used).

Suggested experiments: city counts such as 5/8/10/12; morning vs afternoon/evening start; `lambda` from 0 to high safety preference; beam widths `k=1,3,5,10,...`; 2-opt sensitivity to initial route; optionally delays and perturbed risk inputs. For small `n`, exhaustive enumeration can provide a **verified optimum** for measuring heuristic quality; don't claim either heuristic is optimal without checking.

**X-factor target:** Show the **distance-versus-safety trade-off** and how increasing beam width affects route quality and runtime. Real insight and reproducible experiments matter more than a decorative interface.

## Correctness checks

- Every delivery city appears exactly once; depot is first and last.
- Return distance counts, but returning to depot does not add another delivery-risk score.
- Delivery time is **exactly zero**; arrival at 06:59, 07:00, 18:59 and 19:00 is classified correctly; cross midnight correctly. No waiting is allowed.
- Both approaches call one shared route evaluator for their final reported costs.
- 2-opt never reverses depot endpoints and recomputes times after each change.
- Beam Search correctly handles `k=1`, ties, empty candidate layers, and all cities visited.
- `lambda=0` removes danger from the optimisation objective; nighttime risk must equal exactly **1.5 ×** daytime/base risk, and all stops add **0 minutes**.
- Source-backed versus simulated values are unmistakably identified; no invented results.

## Proposed repository layout (not yet created)

```text
README.md
AGENTS.md
CLAUDE.md
data/raw/               # only if licence/storage permits
data/processed/         # selected city rows + safety data provenance
src/                    # shared model, evaluator, algorithms, CLI
tests/                  # time boundaries and route-validity tests
experiments/            # configurations, raw outputs and summaries
```

No runtime commands are advertised yet: source code has not been added. Update this section with the *actual* directory layout, dependencies and build/run instructions when implementation starts.

## Project deliverables

From the provided CS201 project brief:

- **Week 12 Sunday, 11 PM:** submit via eLearn a `G<X>T<X>.zip` containing *all source code necessary to reproduce the experiments*, datasets in the used format, clearly labelled experiment folders and a README with run instructions; also submit presentation slides.
- **Week 13:** group presentation, critique and mandatory peer evaluation. All members should be able to explain both designs.
- Slides: motivation/why classic TSP is insufficient; modified input/output/constraints; algorithms/data structures and pseudocode; complexity, actual experiments, trade-offs, limitations and AI-use acknowledgement.
- Acknowledge AI tools, contributions and representative prompts according to the brief. **No fabricated experimental results or evidence.**
- Project grading: interestingness 10%, experimentation 30%, presentation 40%, other-team critique 10%, X-factor 10%. Project is worth 20% of the course grade.

## Open decisions

Exact selected cities and verified or simulated **base danger** values; departure time(s) and lambda range; 2-opt start and pass cap; Beam Search ranking, beam widths and tie-breaking; exact language/tooling and repository layout. Document decisions in [AGENTS.md](AGENTS.md) as they are settled.
