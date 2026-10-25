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
3. City danger is derived from perceived day/night safety (`100 - safetyScore`) based on the **actual computed arrival time** at each delivery stop. No delivery danger added on depot return.
4. Update clock by estimated intercity travel time and per-city delivery/service time. Recalculate all following arrival times after changing visiting order. Handle midnight and exact day/night boundaries.
5. `lambda`, departure hour, day/night cutoff, travel speed and service time are **model assumptions**, configurable and explicitly documented; avoid claiming they represent real theft probability.
6. If all cities are mandatory, summing only fixed per-city danger scores is mathematically useless for route order. The time-dependent model is intentional.
7. Straight-line GeoNames/Haversine distances are **not real road distances**. Do not invent roads or ETA accuracy.

## Input and provenance

- **Required primary dataset:** lecturer-provided GeoNames `MY.txt`; filter relevant `P` (populated-place) features and justify a manageable initial subset (about 8–12 locations). Track GeoNameID, name and coordinates.
- **Supplemental source:** Numbeo perceived safety walking alone by day/night, where city-specific observations are available. Store source URL, retrieval/update date, contributor count if possible, exact city matching and terms-of-use considerations.
- Don't treat Numbeo safety scores as a proven probability of a delivery driver being robbed.
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

- Assert tour validity (depot twice, each other selected city once), time boundaries at 06:59/07:00/18:59/19:00, midnight crossings, delivery duration, `lambda=0`, `k=1`, ties, beam capacity, no-improvement 2-opt cases.
- Common test inputs and scorer for both approaches and the distance-only baseline.
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

City list and Numbeo mapping; exact score dates and coverage; speed/service/day cutoff assumptions; safety weights; 2-opt initial route and cap; beam rank function, width and ties; build tool, CLI and data licensing. Update this section whenever the team agrees to a change.
