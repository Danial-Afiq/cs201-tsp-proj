# AGENTS.md — CS201 TSP project context

**Read this first when working on this repository.** Also read [README.md](README.md) for the complete human-facing design. [CLAUDE.md](CLAUDE.md) is a pointer to this document, not an independent source of instructions.

## Official CS201 project brief (source of truth)

- **Expected file in this repository:** [`docs/Project_2627T1.pdf`](docs/Project_2627T1.pdf). The team must upload the lecturer-provided PDF there separately; this Markdown file does **not** embed the PDF.
- **Before planning, implementing, refactoring, evaluating or preparing submission materials**, read the official brief carefully, particularly its **project overview and learning goals; core requirements; choice of use case; dataset rules; deadlines and deliverables; presentation requirements; grading rubric; peer evaluation; and AI-use policy**.
- The official PDF is the **authoritative source for assignment requirements**. `AGENTS.md` and `README.md` summarise those requirements and record our team's proposed design decisions; they must not override the lecturer's instructions. If the documents conflict, follow the official PDF and update the Markdown documentation to match.
- If you cannot open or extract the PDF (or the file has not been uploaded yet), **say so explicitly**. Do not claim to have reviewed it or invent missing requirements. Use the existing documentation only as a provisional summary and flag any requirement that still needs verification.
- Use `README.md` for the project overview and algorithm details, and this file for development instructions and decisions. Keep the two documents consistent when the brief or project scope changes.

## Project mission

CS201 *Beyond the Classic TSP*: implement and evaluate **two meaningfully different solutions** to one modified problem, **Safety-Aware + Day/Night TSP** for a delivery driver visiting Malaysian cities. Compare **Safety-Aware 2-opt** and **Safety-Aware Beam Search**. Distance-only Nearest Neighbor is an auxiliary baseline and suggested initial tour for 2-opt.

**Current status (2026-10-25):** documentation/planning only. Do **not** claim the algorithms, Numbeo datasets, tests, experiments or CI already exist.

## Non-negotiable model rules

1. Choose a fixed start/end depot. Visit every selected other city **exactly once** and return to the depot.
2. Use the same `RouteEvaluator` (or equivalent shared pure function) for both algorithms. `cost = totalDistanceKm + lambda * totalDangerAtArrival`.
3. Every city has a **base danger score from 0–100** (sourced from an available Crime Index or explicitly simulated). Daytime danger = base score; **nighttime danger = 1.5 × base score**. This multiplier is a **simulation assumption**, not measured crime probability or a statistically validated difference. Do not independently derive night risk from Numbeo's day/night survey questions.
4. **Day = 07:00–18:59; night = 19:00–06:59** in Malaysia local time. Classify danger using the **arrival time at each city**, not the chosen roads. Add no new delivery danger for the final return to the depot.
5. **Fixed speed = 60 km/h**, and **delivery/service time = 0 minutes at every city**. Travel time = (distance km / 60 km/h). Driver leaves immediately on arrival; **no waiting until morning** is permitted. Recalculate all downstream arrival times after a route change; handle midnight and cutoff boundaries correctly.
6. Use the shared `cost = totalDistanceKm + lambda * totalArrivalDanger` objective for both algorithms. `lambda` and departure time may be varied deliberately for experiments; speed, 1.5× night factor, zero-stop-time and day/night bounds are the agreed **fixed base-model assumptions**. Document any separate sensitivity experiment clearly.
7. Fixed risk added once per required city would not affect city order. The day/night variation must be modelled explicitly. Since base scores range from 0–100, nighttime penalties can exceed 100; they are **relative model scores, not percentages**. Straight-line GeoNames/Haversine distances are **not actual road distances** or reliable road ETAs.

## Agreed model assumptions (team decisions)

| # | Assumption | Implementation requirement |
| --- | --- | --- |
| 1 | Higher crime risk at night | `nightDanger = 1.5 * baseDanger`. Do not use a different per-city night multiplier. |
| 2 | Different city danger scores | Each city receives a base `0–100` score from documented available crime data or explicitly simulated input. |
| 3 | Fixed day/night schedule | Day `07:00 <= t < 19:00`; night otherwise (local 24-hour clock). |
| 4 | Constant travelling speed | Exactly `60 km/h` for the baseline simulation. |
| 5 | Negligible delivery time | Exactly `0 minutes` per delivery; do not introduce a 30-minute stop. |
| 6 | Cannot wait for morning | No waiting; departure from a city occurs immediately after arrival. |
| 7 | Risk depends on arrival city and time | Charge risk when **arriving at delivery cities**, not while driving each edge. |

**Canonical evaluator:** Starting from the user-selected departure time, for each leg calculate `arrivalNext = arrivalCurrent + distanceKm / 60` (hours). Set `currentTime = arrivalNext` for the next leg, because time spent in city is zero. Charge either base or 1.5×base on delivery arrival; do not charge a separate danger score when returning to the depot. Sum all leg distances for the full cost. Do not cap night penalties at 100: these are model points, not probabilities. Vary `lambda` when studying distance/safety trade-offs.

## Input and provenance

- **Required primary dataset:** lecturer-provided GeoNames `MY.txt`; filter relevant `P` (populated-place) features and justify a manageable initial subset (about 8–12 locations). Track GeoNameID, name and coordinates.
- **Supplemental source:** Numbeo city-level **Crime Index** where city-specific data is available, as one possible source for the base 0–100 danger value. Store source URL, retrieval/update date, contributor count if possible, exact city matching and terms-of-use considerations. Do not replace the agreed 1.5× night model with Numbeo's separate day/night walking-safety scores.
- Do not treat Numbeo Crime Index scores as a proven probability of a delivery driver being robbed. The 1.5× night factor is simulated, not sourced from Numbeo.
- Missing values must be excluded or explicitly labelled as **synthetic**. Do not fabricate empirical observations, experimental results, screenshots or citations.
- Do not scrape or redistribute data without confirming provider permissions.

## Algorithm A — Safety-Aware 2-opt

- Start with valid full tour (proposed initialiser: distance-only Nearest Neighbor).
- Represent tour with array/list of city indices; depot pinned at both ends.
- For all valid `(i,j)` non-depot pairs, reverse section `[i..j]`, fully evaluate the tour (arrival times and risks included), and keep the best strict improvement per pass.
- Stop when no move helps or at explicitly documented cap; deterministic tie handling.
- Full rescoring gives **O(p n³)** for `p` passes; count initial-tour construction in end-to-end runtime. Distance matrix requires O(n²) memory.

## Algorithm B — Safety-Aware Beam Search

- Each state: current city, visited mask, time, accumulated distance/danger/cost and parent pointer for route reconstruction.
- Extend every retained state by every currently unvisited city; compute its arrival danger then.
- At each depth, keep at most `k` children ranked by a documented heuristic. Suggested first version: `costSoFar + distance(lastCity, depot)`. This is a weak optimistic remainder and **does not guarantee optimality**.
- Use bounded **max-heap** (Java `PriorityQueue` with reverse comparator) so the worst kept state can be replaced efficiently.
- Complete every retained full visiting order with the depot return; compare **real full-tour cost**, not just partial ranking. A `k=1` beam isn't necessarily Nearest Neighbor.
- If ranking each child costs O(1), straightforward complexity ~**O(k n² log(k+1))**, with retained ancestry up to O(kn) and the O(n²) distance matrix. More complex heuristics change this bound.
- Be careful deduplicating: same visited cities/last city with different arrival times are not necessarily equivalent.

## Suggested architecture (not existing files)

```text
src/City.java
src/DistanceMatrix.java
src/GeoNamesLoader.java
src/RouteEvaluator.java
src/NearestNeighbor.java
src/SafetyTwoOpt.java
src/SafetyBeamSearch.java
src/Main.java
tests/
data/processed/
experiments/
```

Only create these files if they fit the actual team-chosen Java structure. Prefer small testable classes and simple standard-library structures. Don't insert AVL/BST/heap code just for complexity or marketing; each choice must have a real purpose.

## Testing and experiments

- Assert tour validity (depot twice, each other selected city once), time boundaries at 06:59/07:00/18:59/19:00, midnight crossings, **zero delivery duration**, **no waiting**, **60 km/h constant speed**, **night = 1.5× base danger**, `lambda=0`, `k=1`, ties, beam capacity, no-improvement 2-opt cases.
- Common test inputs and scorer for both approaches and the distance-only baseline. Verify that swapping city order changes clock times but never adds stop time; verify nighttime score can exceed 100 without being silently clipped.
- Record costs, distances, risk, runtime, number of candidates checked, 2-opt passes, beam prunes, parameters and reproducible random seed where applicable.
- Run city-count scaling, departure-time, lambda, beam-width and starting-route studies. Include losing cases and limitations, not just favorable examples.
- Optional exhaustive enumeration on tiny inputs can confirm optimality; do not claim global optimum otherwise.
- Don't invent benchmark numbers or assert that tests pass unless executed.

## Submission and presentation

- Week 12 Sunday 23:00: submit `G<X>T<X>.zip` on eLearn with all code, used data, experiment folders and actual running instructions; submit presentation slides.
- Week 13: presentation and mandatory peer evaluation / other-group critique.
- Explain problem assumption change, input/output/constraints, pseudocode, meaningful DSA choices, asymptotic cost, actual results, trade-offs, source limitations and AI contributions. Every team member should be able to defend the design.
- Rubric: 10% interestingness; 30% experimentation; 40% presentation; 10% critique; 10% X-factor. Fancy UI alone does not count as X-factor.
- The brief allows AI assistance with attribution. Preserve evidence and representative prompts; do not fabricate.

## Instructions for coding agents

- Before code changes, inspect the repo and read README.md/AGENTS.md.
- Respect the agreed **2-opt and Beam Search** choices; present proposed departures rather than silently changing algorithms.
- Do not conflate A* road shortest paths with solving a city-visiting TSP tour.
- If implementation/scoring decisions change, update the docs and corresponding tests in the same change.
- Avoid unrelated refactors, replacing teammates' work, unnecessary dependencies or silent dataset rewriting.
- Keep explanations and inline comments understandable for a CS201 student; accurately disclose assumptions and complexity.
- Run tests that are actually available; report what passed and what could not be verified.

## Open decisions (not settled yet)

City list and Numbeo mapping; exact base-score dates and coverage; departure time(s) and safety weights; 2-opt initial route and cap; beam rank function, width and ties; build tool, CLI and data licensing. Update this section whenever the team agrees to a change.
