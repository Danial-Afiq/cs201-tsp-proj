# AGENTS.md — CS201 TSP project context

**Read this first when working on this repository.** Also read [README.md](README.md) for the complete human-facing design. [CLAUDE.md](CLAUDE.md) is a pointer to this document, not an independent source of instructions.

## Official CS201 project brief (source of truth)

- **Official file present in this repository:** [`docs/Project_2627T1.pdf`](docs/Project_2627T1.pdf), reviewed for this data/documentation update on 2026-10-26. This Markdown file does **not** embed or replace the PDF.
- **Before planning, implementing, refactoring, evaluating or preparing submission materials**, read the official brief carefully, particularly its **project overview and learning goals; core requirements; choice of use case; dataset rules; deadlines and deliverables; presentation requirements; grading rubric; peer evaluation; and AI-use policy**.
- The official PDF is the **authoritative source for assignment requirements**. `AGENTS.md` and `README.md` summarise those requirements and record our team's proposed design decisions; they must not override the lecturer's instructions. If the documents conflict, follow the official PDF and update the Markdown documentation to match.
- If you cannot open or extract the PDF (or the file has not been uploaded yet), **say so explicitly**. Do not claim to have reviewed it or invent missing requirements. Use the existing documentation only as a provisional summary and flag any requirement that still needs verification.
- Use `README.md` for the project overview and algorithm details, and this file for development instructions and decisions. Keep the two documents consistent when the brief or project scope changes.

## Project mission

CS201 *Beyond the Classic TSP*: implement and evaluate **two meaningfully different solutions** to one modified problem, **Safety-Aware + Day/Night TSP** for a delivery driver visiting Malaysian cities. Compare **Safety-Aware 2-opt** and **Safety-Aware Beam Search**. Distance-only Nearest Neighbor is an auxiliary baseline and suggested initial tour for 2-opt.

**Current status (2026-10-26):** [data/processed/cities_cleaned.csv](data/processed/cities_cleaned.csv) contains 18 cities matched to lecturer GeoNames records and verified against supplied Numbeo PDFs. Data validation has run. Algorithms, algorithm tests, experiments and CI are still unimplemented; do not claim otherwise.

## Non-negotiable model rules

1. Choose a fixed start/end depot. Visit every selected other city **exactly once** and return to the depot.
2. Use the same `RouteEvaluator` (or equivalent shared pure function) for both algorithms: **`cost = alpha * D_scaled + (1 - alpha) * R_scaled`**, `0 <= alpha <= 1`.
3. Use actual separate Numbeo scores: **`day_risk = 100 - day_safety`**, **`night_risk = 100 - night_safety`**. Both risks are in `[0,100]`. Crime Index is descriptive metadata, not either arrival risk. Do not force night risk to exceed day risk, simulate a multiplier, or replace missing scores with invented data.
4. **Day = 07:00–18:59; night = 19:00–06:59** in Malaysia local time. Classify danger using the **arrival time at each city**, not the chosen roads. Add no new delivery danger for the final return to the depot.
5. **Fixed speed = 60 km/h**, and **delivery/service time = 0 minutes at every city**. Travel time = (distance km / 60 km/h). Driver leaves immediately on arrival; **no waiting until morning** is permitted. Recalculate all downstream arrival times after a route change; handle midnight and cutoff boundaries correctly.
6. For `n >= 2` selected cities including the depot, set `m=n-1`, `D_scaled=D/(n*L)`, `R_scaled=R/(100*m)`. `D` includes all `n` closed-tour legs; `R` includes the `m` delivery arrivals. `L` is the maximum pairwise Haversine distance across the frozen full 18-city reference CSV, computed once using Earth radius `6371.0088 km`: approximately `679.6472875815844 km` (Kangar–Johor Bahru). Preserve full precision; require `L>0`. Use this same reference `L` across subset sizes, algorithms, weights and departure times. Never use route-specific min/max, candidate-dependent denominators or partial-beam city counts. Each component is bounded in `[0,1]` because legs are at most `L` and risks at most 100.
7. `alpha=1` is distance-only, `alpha=0` is arrival-risk-only (distance still controls time), and `alpha=0.5` gives equal numerical weighting of normalised components. Keep speed, zero stop time, no waiting and day/night boundaries fixed. Fixed per-city risk would be constant across visiting orders; day/night variation can change this, but all-day/all-night routes may still tie. Scores are relative survey perceptions, not probabilities; Haversine distances are **not road distances** or reliable road ETAs.

**Across sizes:** the denominators measure average leg distance relative to the same reference span and average delivery risk relative to 100. They remove simple growth in totals from adding stops; they do not make different city subsets equally difficult or equally safe. Report raw totals, averages, scaled components, cost and runtime; compare algorithms on the same instance. A changed reference dataset requires a new recorded `L` and dataset version. Equal numerical weights need not imply equal practical influence or equal empirical ranges.

## Agreed model assumptions (team decisions)

| # | Assumption | Implementation requirement |
| --- | --- | --- |
| 1 | Daytime | `07:00 <= t < 19:00` in Malaysia local time (7 AM–7 PM). |
| 2 | Nighttime | `19:00 <= t` or `t < 07:00` (7 PM–7 AM). |
| 3 | Constant travelling speed | Exactly `60 km/h`. |
| 4 | Negligible delivery time | Exactly `0 minutes` per city. |
| 5 | Cannot wait for morning | No waiting; depart immediately on arrival. |
| 6 | Risk depends on arrival city and time | Use that city's actual day/night safety complement at each delivery arrival. |
| 7 | Distance | Haversine from original GeoNames coordinates; geographic approximation, not road distance. |

**Canonical evaluator (implementation specification, not existing code):** Starting from the chosen departure time, each leg adds `distanceKm / 60` hours. Preserve elapsed time across days; use local time modulo 24 only for day/night classification. Sum every leg's distance; select `day_risk` or `night_risk` on each non-depot delivery arrival. Do not charge risk at initial departure or final depot return. No stop time or waiting is added. Return raw `D`, `R`, arrival details, `D/(n*L)`, `R/(100*m)` and the alpha-weighted cost. Reuse the same transition helper/constants in Beam Search and fully rescore completed tours for reporting.

Verified example: Kuala Lumpur day safety 56.86 and night safety 31.96 imply risks 43.14 and 68.04. A separate **hypothetical**, five-city illustration with fixed `L` above and `alpha=0.5`: `(D=500,R=80)` costs approximately `0.17357`; `(D=540,R=45)` costs `0.13570`. These are explanatory totals, not completed experiments.

## Input and provenance

- **Required primary dataset:** lecturer-provided 19-column GeoNames `MY.txt`, not the optional XLSX copy. Of 71,709 rows, 21,672 are class `P`; exclude 50,037 other features. The city/town candidate rule permits `PPL`, `PPLA`, `PPLA2`, `PPLA3`, `PPLA4`, `PPLC`, `PPLG`: 21,405 rows, excluding 267 other `P` records. No invalid global coordinate ranges or duplicate source IDs were found. There is no minimum dataset size in brief Section 5.
- **Selected 18:** Kangar, Alor Setar, Sungai Petani, George Town, Bukit Mertajam, Taiping, Ipoh, Kota Bharu, Kuala Terengganu, Kuantan, Kuala Lumpur, Petaling Jaya, Shah Alam, Klang, Seremban, Malacca, Muar, Johor Bahru. These cover 11 states plus Kuala Lumpur; four are in the Klang Valley. Preserve the city list unless the team requests a new dataset version.
- **Supplemental source:** all 48 `numbeo_inventory.csv` records were checked against the 48 archived PDFs. Crime Index, overall Safety Index, day/night safety, contributors and update date match exactly (288 comparisons). The cleaned CSV uses the actual day/night walking-alone scores. Overall Safety Index is redundant and omitted; Crime Index remains contextual. PDFs and raw inputs remain outside this change's Git deliverables.
- **Matching:** preserve source GeoNameIDs and exact coordinate text; match primary/ASCII/alternate names with feature, state and location checks. There are 1,734 repeated-name groups covering 5,254 eligible source rows, so names are not unique keys. Use Kelantan Kota Bharu 1736376, not Perak Kota Baharu 1735271 or district 1736375; Ipoh 1734634, not Menglembu 1734639; and populated, not administrative, matches for Kuala Lumpur, Klang, Kuala Terengganu, Kuantan and Seremban. `Kangar, Perlis` maps to Kangar 1736278. README records all 30 exclusions and exact source hashes.
- **Exclusions:** avoid Sabah/Sarawak/Labuan cross-sea trips; do not assign Kedah/Selangor regional scores to cities. Penang is ambiguous: use the distinct George Town city source. Gombak is a district match; Langkawi has island/district versus Kuah ambiguity; Serdang has multiple settlement/duplicate-coordinate candidates. `PPLX` Skudai and Subang Jaya are outside this snapshot's conservative city rule. Other reliable candidates were omitted for geographic redundancy and/or weaker survey support; no padding to a target count.
- **Quality:** 11 selected rows have fewer than 30 contributors; six updates predate 2024-10-26. Flags are descriptive, not automatic exclusions or score multipliers. Retain low-count Kangar (5) for the northern endpoint and Muar (7) for an intermediate southern stop. As-of date is 2026-10-26. Contributor counts range 5–839 and updates 2024-06-14–2026-10-21. Do not silently refresh dates/scores or imply `none` means statistically reliable.
- Numbeo reports self-selected perceptions (PDFs refer to the preceding five years), not actual crime probabilities or delivery-driver-specific safety. Mixed dates, sparse samples, city-level averages and metro overlap limit conclusions. George Town is on Penang Island with bridge access, but Haversine legs do not follow bridges or roads and may cross water. No literal road-driving claim is permitted.
- Missing empirical values must be excluded or explicitly missing, never imputed without an agreed method. Any synthetic sensitivity data must remain separate and labelled. Do not fabricate observations, results, screenshots or citations.
- Do not scrape or redistribute data without confirming provider permissions.

**CSV contract (20 columns):** `geonameid` integer unique key; `name` original text; `latitude`, `longitude` original decimal-degree coordinates; `feature_class`, `feature_code` original source labels; `admin1_code` source text with leading zeros; `population` original integer context only; `crime_index`, `day_safety`, `night_safety` PDF decimals; `day_risk`, `night_risk` exact two-decimal complements; `numbeo_contributors` integer; `numbeo_last_update` ISO date from the PDF; `numbeo_location` original source label; `numbeo_source` exact `Crime Indexes.zip!/PDF filename`; `numbeo_pdf_pages` inclusive range of the source document; `numbeo_url` city URL extracted from PDF links; `data_quality_flag` semicolon-separated `low_contributors_lt30` and/or `update_older_than_24_months`, or `none`. The thresholds are project screening rules, not confidence intervals. The archive is external and filenames do not imply PDFs are committed. The five extra provenance/classification columns beyond the suggested schema are explained in README.

**Data/algorithm boundary:** CSV contains unscaled geographic and safety values plus city-level risk complements. Load it identically for both algorithms; verify types, unique IDs, ranges, nonmissing fields, correct complements and source mappings. Build Haversine matrices, arrival times, route totals and scaling in shared algorithm code, never in this CSV. Do not add routes, scaled costs or departure-specific risk columns. Source population is context only. Keep GeoNames attribution (supplied metadata: CC BY 4.0) and Numbeo attribution; broader redistribution permissions remain to be checked.

## Algorithm A — Safety-Aware 2-opt

- Start with valid full tour (proposed initialiser: distance-only Nearest Neighbor).
- Represent tour with array/list of city indices; depot pinned at both ends.
- For all valid `(i,j)` non-depot pairs, reverse section `[i..j]`, fully evaluate the tour (arrival times and risks included), and keep the best strict improvement per pass.
- Stop when no move helps or at explicitly documented cap; deterministic tie handling.
- Full rescoring gives **O(p n³)** for `p` passes; count initial-tour construction in end-to-end runtime. Distance matrix requires O(n²) memory.

## Algorithm B — Safety-Aware Beam Search

- Each state: current city, visited mask, time, accumulated distance/danger/cost and parent pointer for route reconstruction.
- Extend every retained state by every currently unvisited city; compute its arrival danger then.
- At each depth, retain at most `k` children. First-version rank: `alpha * (distanceSoFar + distance(lastCity,depot)) / (n*L) + (1-alpha) * riskSoFar / (100*m)`. Use full-instance `n`, `m` and reference `L` at every depth. Direct return is a metric lower bound and remaining risk is nonnegative; this optimistic ranking **does not guarantee optimality** after beam pruning. Do not add unscaled kilometres to a scaled score.
- Use bounded **max-heap** (Java `PriorityQueue` with reverse comparator) so the worst kept state can be replaced efficiently.
- Complete every retained full visiting order with the depot return; compare **real full-tour cost**, not just partial ranking. A `k=1` beam isn't necessarily Nearest Neighbor.
- If ranking each child costs O(1), straightforward complexity ~**O(k n² log(k+1))**, with retained ancestry up to O(kn) and the O(n²) distance matrix. More complex heuristics change this bound.
- Be careful deduplicating: same visited cities/last city with different arrival times are not necessarily equivalent.

## Suggested architecture (implementation not yet created)

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
data/processed/cities_cleaned.csv  # already present; other entries are proposed
experiments/
```

Only create these files if they fit the actual team-chosen Java structure. Prefer small testable classes and simple standard-library structures. Don't insert AVL/BST/heap code just for complexity or marketing; each choice must have a real purpose.

## Testing and experiments

- Assert tour validity (depot twice, each other city once), boundaries at 06:59/07:00/18:59/19:00, midnight and multi-day crossings, **zero delivery duration**, **no waiting**, **60 km/h**, correct safety complements, `alpha=0/0.5/1`, invalid alpha, `n<2`, `L<=0`, `k=1`, ties, capacity and no-improvement 2-opt cases.
- Common inputs and scorer for both approaches and the distance-only baseline. Verify that changing city order changes downstream times but never adds stop time; allow equal day/night values and constant-risk routes. Check shared fixed denominators, scaled bounds `[0,1]`, no separate return-depot risk, and agreement between incremental and full scoring. Distance still affects times at `alpha=0`.
- Record costs, raw/scaled distances and risk, averages, arrival details, runtime, candidates, 2-opt passes, beam prunes, all instance IDs/depot, `n`, `m`, `L`, alpha, departure, dataset/implementation version and reproducible seed where applicable.
- Proposed city counts **5/8/12/18**, departures **07:00/13:00/18:00**, alpha **0/0.25/0.5/0.75/1**, beam-width and starting-route studies. Use predeclared nested subsets from README with fixed depot and the same full-reference `L`; also compare a local family and the seven-city `contributors >=30` sensitivity subset. The latter lacks east-coast coverage and still contains older Ipoh data; do not present it as unbiased. Include losing cases and limitations. No experiments have run yet.
- Exhaustive enumeration on tiny inputs can confirm optimality; consider both route orientations because risk is time-dependent. Do not claim global optimum otherwise. The 5–18-city timing range does not prove asymptotic complexity.
- Don't invent benchmark numbers or assert that tests pass unless executed.

## Submission and presentation

- Week 12 Sunday 23:00: submit `G<X>T<X>.zip` on eLearn with all code, used data, experiment folders and actual running instructions; submit presentation slides.
- Week 13: presentation and mandatory peer evaluation / other-group critique.
- Brief permits Java, Python or another approved language. Include required third-party libraries and actual run instructions. Only the most recent submission is retained.
- Explain problem assumption change, input/output/constraints, pseudocode, meaningful DSA choices, asymptotic cost, actual results, trade-offs, source limitations and AI contributions. Every team member should be able to defend the design.
- Rubric: 10% interestingness; 30% experimentation; 40% presentation; 10% critique; 10% X-factor. Project is 20% of the course grade. Fancy UI alone does not count as X-factor.
- Brief Section 5 requires explaining records/columns, selection justification, filtering/preprocessing and supplementary/derived attributes. README contains these decisions; use them in the presentation without implying experiments are done.
- The brief allows AI assistance with attribution: name tools, how/where used, original team contributions and **three real representative prompts** in the project report submission. Codex assisted this data/documentation update under the user's supplied model decisions; retain this request as one prompt, not three invented examples. Every member remains accountable. **No GenAI answering queries during the live presentation/demo.** Preserve evidence; do not fabricate.
- Peer evaluation is mandatory and non-submission is penalised; question the assigned presenting group. Raise group problems by Week 10; use the course Teams Project Clarification Forum for assignment questions.

## Instructions for coding agents

- Before code changes, inspect the repo and read README.md/AGENTS.md.
- Respect the agreed **2-opt and Beam Search** choices; present proposed departures rather than silently changing algorithms.
- Do not conflate A* road shortest paths with solving a city-visiting TSP tour.
- If implementation/scoring decisions change, update the docs and corresponding tests in the same change.
- Avoid unrelated refactors, replacing teammates' work, unnecessary dependencies or silent dataset rewriting.
- Keep explanations and inline comments understandable for a CS201 student; accurately disclose assumptions and complexity.
- Run tests that are actually available; report what passed and what could not be verified.

## Open decisions (not settled yet)

The 18-city selection, verified scores/dates, shared scaled objective and seven model assumptions are settled. Final depot/departure/alpha grid; 2-opt initial route and cap; beam width and ties (the weak first-version rank is specified above); build tool, CLI and broader data redistribution remain open. Update this section whenever the team agrees to a change. This data-cleaning change must commit **exactly** `README.md`, `AGENTS.md` and `data/processed/cities_cleaned.csv`; do not modify `CLAUDE.md`, implement algorithms or commit raw inputs/temporary tooling as part of it.
