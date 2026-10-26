# SafeRoute — Safety-Aware Travelling Salesperson Problem

CS201 Data Structures & Algorithms — *Beyond the Classic TSP*.

> **Status (2026-10-26):** Data cleaning complete: 18 cities with PDF-verified Numbeo values in [cities_cleaned.csv](data/processed/cities_cleaned.csv). Algorithms and experiments remain planned, not implemented or tested.

The official [CS201 project brief](docs/Project_2627T1.pdf) is authoritative for assignment requirements. The model below records team decisions, not additional lecturer requirements.

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

**Inputs:** a chosen depot; selected GeoNames cities with actual Numbeo day/night safety scores and derived risks; Haversine distance matrix; departure time; fixed speed of **60 km/h**; distance weight `alpha` in `[0,1]`; fixed normalisation constants; and beam width `k` for Beam Search.

**Output:** a complete tour `depot -> each delivery city exactly once -> depot`, with total kilometres, arrival times, total arrival risk, scaled distance/risk and combined cost. The depot occurs only at the start and end; each other selected city occurs once.

### Agreed assumptions (apply identically to both algorithms)

| # | Assumption | How we implement it |
| --- | --- | --- |
| 1 | Daytime | `07:00 <= local time < 19:00` (7 AM–7 PM). |
| 2 | Nighttime | `19:00 <= local time` or `local time < 07:00` (7 PM–7 AM). |
| 3 | Constant travelling speed | **60 km/h** for all simulated trips. |
| 4 | Negligible delivery time | **0 minutes**; leave immediately on arrival. |
| 5 | Cannot wait until morning | No waiting at any stop. |
| 6 | Risk depends on city and actual arrival time | Choose the city's measured day/night safety complement at each delivery arrival. |
| 7 | Geographic distance | Haversine from original GeoNames coordinates; an approximation, not road distance. |

### Shared scoring model

```text
day_risk[city]   = 100 - day_safety[city]
night_risk[city] = 100 - night_safety[city]
arrivalRisk     = day_risk[city] (day) OR night_risk[city] (night)

travelTimeHours = distanceKm / 60
arrivalTimeNext = arrivalTimeCurrent + travelTimeHours
# delivery time = 0, so departureTimeNext = arrivalTimeNext

D = distance of every leg, including the final return to depot
R = sum of arrivalRisk for each delivery city (NOT the returning depot)
n = number of selected cities INCLUDING the depot; require n >= 2
m = n - 1 delivery arrivals
L = maximum pairwise Haversine distance in the full 18-city reference dataset
D_scaled = D / (n * L)
R_scaled = R / (100 * m)
combinedCost = alpha * D_scaled + (1 - alpha) * R_scaled
```

Use **C = α D_scaled + (1−α) R_scaled** in a single shared `RouteEvaluator`. For example, Kuala Lumpur's verified safety scores are 56.86 by day and 31.96 at night: arrival risk is **43.14** at 2 PM or **68.04** at 9 PM. Crime Index is retained as context and is not an input to either risk formula. Scores are survey perceptions, not probabilities.

**Fixed scaling:** use Earth radius `6371.0088 km` and double precision. For this frozen reference dataset, `L ≈ 679.6472875815844 km` (Kangar–Johor Bahru); derive it once from all 18 rows, retaining full precision. Every valid closed tour has `n` legs each at most `L`, so `0 <= D_scaled <= 1`; every delivery risk lies in `[0,100]`, so `0 <= R_scaled <= 1`. Require positive `L`; reject degenerate all-coincident reference coordinates. No candidate-specific min/max, observed-tour calibration, or rescaling of partial beams is allowed. Both algorithms and the baseline use identical denominators for a given instance.

Keep the same full-reference `L` for all smaller subsets in this experiment family; only `n` and `m` change with subset size. This makes distance an average-leg fraction of the same geographic span and risk an average-arrival fraction of 100. It prevents raw totals from growing solely because more cities were added, but different subsets still differ in geometry and safety: cross-size costs are **not** an isolated measure of algorithm quality. Compare algorithms on the same instance and report raw totals, per-leg/per-stop averages, runtime and, for tiny cases, gaps to the exact optimum. A changed reference dataset needs a new recorded `L` and experiment version.

**Weights:** `alpha=1` minimises distance only; `alpha=0` uses only arrival risk, although distance still determines arrival times; `alpha=0.5` gives equal numerical weight to the two scaled quantities. Equal weights do not promise equal practical influence or equal observed ranges. This is a modelling preference, not a monetary or probability calibration.

**Important:** If all mandatory cities are visited once with fixed danger scores, the risk sum is constant for every route. **Changing the score at night** makes the visiting order matter whenever routes produce different day/night arrival patterns. If all deliveries occur in the same period, risk may still be constant.

Times should use Malaysia local time, wrap correctly past midnight, and respect the exact **07:00 / 19:00** boundaries. Straight-line Haversine distance divided by 60 km/h is a **simulation**, not a road-driving ETA.

### Scoring illustration (made-up numbers)

Illustrative `n=5`, `m=4`, `L=679.6472875815844 km`, `alpha=0.5`; both tours use the same constants. These hypothetical totals are not experiment results.

| Tour | Distance | Total risk | D_scaled | R_scaled | Combined cost |
|---|---:|---:|---:|---:|---:|
| Route X | 500 km | 80 | 0.14714 | 0.20000 | 0.17357 |
| Route Y | 540 km | 45 | 0.15891 | 0.11250 | **0.13570** |

Route Y is preferred under these assumptions despite being longer.

## Data and provenance

**Primary data:** the lecturer-provided `MY.txt`, interpreted using `Metadata.txt`: 71,709 records, each with 19 tab-separated fields. All IDs are unique and all coordinates are present and within global latitude/longitude bounds. Keep populated-place class `P` (21,672); discard 50,037 administrative, water, terrain, building and other non-populated features. A conservative city/town candidate rule retains `PPL`, `PPLA`, `PPLA2`, `PPLA3`, `PPLA4`, `PPLC` and `PPLG` (21,405), excluding 267 other `P` records such as neighbourhood sections, abandoned/historical places and locality/group variants. This rule describes this source snapshot, not the current legal status of every Malaysian municipality. Population is context, not a minimum threshold or cost weight.

**Supplemental data:** `numbeo_inventory.csv` contains 48 locations. All 48 were checked against all 48 original PDFs in `Crime Indexes.zip`: Crime Index, overall Safety Index, daytime safety, nighttime safety, contributors and last update agree exactly (288 field comparisons). No numeric corrections or imputation were necessary. Overall Safety Index was checked but omitted from the deliverable because the two separate day/night values drive this model. The raw PDFs are the verification source; linked Numbeo pages may subsequently change. The supplied XLSX is an optional convenience copy, not the geographic source used for the join.

### Selected records and justification (brief Section 5)

The cleaned dataset contains **18 cities across 11 states plus Kuala Lumpur**, with seven northern/west-coast, three east-coast, four Klang Valley and four southern stops. There is no minimum dataset size in the brief. This selection balances regional coverage, clear city matches and source support, while retaining nearby stops and avoiding a route dominated by the Klang Valley.

| Group | Selected cities (Numbeo contributors) | Why retained |
|---|---|---|
| Northern/west coast | Kangar (5), Alor Setar (14), Sungai Petani (15), George Town (41), Bukit Mertajam (15), Taiping (10), Ipoh (37) | Northern endpoint, Kedah corridor, Penang city/mainland pair and Perak stops. |
| East coast | Kota Bharu (18), Kuala Terengganu (17), Kuantan (16) | Cover all three east-coast states rather than only the better-sampled west coast. |
| Klang Valley | Kuala Lumpur (839), Petaling Jaya (87), Shah Alam (41), Klang (89) | Four well-supported nearby urban stops; plausible local delivery segments. |
| South | Seremban (22), Malacca (23), Muar (7), Johor Bahru (133) | Southern corridor, with Muar adding an intermediate Johor stop. |

Kangar and Muar have only 5 and 7 contributors, but their distinct geographic roles justify retention with flags. George Town is on Penang Island in the Peninsular Malaysia region; bridge access makes it a reasonable regional stop, but our direct Haversine edges do **not** follow bridges and may cross water. They remain a geographic simulation. No Sabah, Sarawak, Labuan or Langkawi stops are included.

### Matching and exclusions

Match on original name, ASCII name and alternate names, then check feature class/code, state code and coordinates; never deduplicate merely by name. The eligible pool contains 1,734 repeated case-insensitive name groups covering 5,254 records. IDs preserve identity. All selected geographic fields, including coordinate text precision and population, are copied unchanged. `Kangar, Perlis` maps to `Kangar` (1736278); its qualified Numbeo name is retained separately. Other selected names match their GeoNames primary names.

Important disambiguation: use Kota Bharu **1736376**, the Kelantan state capital, not Kota Baharu **1735271** in Perak or the district **1736375**. Its PDF's nearby-city context supports Kelantan. Use Ipoh **1734634**, not Menglembu **1734639** with alternate name Ipoh. Use populated Kuala Lumpur **1735161**, Klang **1732905**, Kuala Terengganu **1734705**, Kuantan **1735227** and Seremban **1734810**, not their similarly named administrative/river/port records. Malacca **1734759** is the populated city (also called Melaka), not state-level data.

All **30 unselected Numbeo locations** are accounted for below. Exclusion does not imply their survey scores are false.

| Locations | Reason not included |
|---|---|
| Bintulu, Kota Kinabalu, Kuching, Miri, Sibu, Labuan | Outside the Peninsular experiment; would require cross-sea travel. |
| Kedah, Selangor | State labels; do not assign regional scores to a state capital or Kuala Selangor just because of an alias. |
| Penang | Ambiguous state/island/city label; keep the separate George Town city PDF, not both. |
| Gombak | Only exact/alias match is an administrative district in this source. |
| Langkawi | Island/district label also aliases Kuah; no reliable city-level assignment, and island transfer is outside scope. |
| Serdang | Multiple settlements; Serdang and Seri Kembangan also share coordinates. Insufficient evidence for a unique city entity. |
| Skudai (Sekudai), Subang Jaya | Source classifies these as `PPLX` (sections of populated places), outside the conservative city/town rule. No silent reclassification. |
| Ampang Jaya, Bangi, Cyberjaya, Kajang, Kepong, Kota Damansara, Puchong, Putra Heights, Putrajaya, Rawang | Limit further Klang Valley concentration. Cyberjaya has 36 contributors but adds less geographic variety; Ampang's territory/municipal extent also needs care. |
| Bayan Lepas, Butterworth, Kulim | Existing Penang/Kedah stops cover this area; these alternatives have 9, 5 and 4 contributors. |
| Bandar Penggaram | Valid alternate-name match to Batu Pahat (1732687), but only 3 contributors and a 2021 update; Muar provides an intermediate southern stop with better support. |
| Nilai, Seri Iskandar | Nearby coverage already supplied by Seremban and Ipoh/Taiping; only 9 and 5 contributors. |

No missing scores were found in the 48 rows. Extreme values were reviewed, not edited: excluded Putra Heights has night safety 0.00 with 3 contributors; Labuan has day safety 100.00 with 4. Both are within the scale. Bandar Penggaram has equal day/night scores, which is allowed. No assumption forces every city's night risk to exceed its day risk.

### Cleaned CSV schema and quality flags

UTF-8 comma-separated file, one header and **18 data rows**; order is for readability, not a prescribed tour. Consumers should parse integer/decimal values and keep `admin1_code` as text (including leading zeros).

| Columns | Type and purpose |
|---|---|
| `geonameid`, `name` | Integer stable GeoNames key and original city name; identity and route labels. |
| `latitude`, `longitude` | Original WGS84 decimal-degree coordinates for Haversine distance. |
| `feature_class`, `feature_code`, `admin1_code` | Source classification and first-level administrative code for audit/matching. All selected rows are class `P`; codes are from this GeoNames snapshot, not assumed ISO state codes. |
| `population` | Original integer population, descriptive context only; not a current census claim. |
| `crime_index` | PDF decimal index, descriptive context only; not the risk used by algorithms. |
| `day_safety`, `night_safety` | Separate PDF walking-alone safety scores in `[0,100]`. |
| `day_risk`, `night_risk` | Decimal complements `100 - safety`, calculated exactly to two decimals. |
| `numbeo_contributors` | Integer contributor count for assessing survey support, not a statistical confidence interval. |
| `numbeo_last_update` | PDF's update date as `YYYY-MM-DD`; not a retrieval date or observation timestamp. |
| `numbeo_location` | Original Numbeo location label to make the join traceable. |
| `numbeo_source`, `numbeo_pdf_pages`, `numbeo_url` | Exact `Crime Indexes.zip!/PDF filename`, inclusive page range of the source PDF, and its city URL extracted from PDF links. The archive is supplied separately, not a repository-relative file. |
| `data_quality_flag` | Semicolon-separated flags below, or `none` (no flagged condition, not a guarantee of accuracy). |

The five additions to the suggested schema (`feature_class`, `admin1_code`, `numbeo_location`, `numbeo_pdf_pages`, `numbeo_url`) preserve match and source context. No route costs, scaled values, distance matrix or departure-specific risks are stored here.

As of **2026-10-26**, `low_contributors_lt30` flags **11/18** rows; 30 is a transparent project screening threshold, not a confidence guarantee or automatic exclusion rule. `update_older_than_24_months` flags **6/18** rows (Kangar, Alor Setar, Taiping, Ipoh, Kota Bharu, Muar; dates before 2024-10-26). Updates span 2024-06-14 to 2026-10-21; contributor counts span 5–839. Do not silently down-weight these risks: include them in the main experiment and report a separately labelled quality-subset sensitivity analysis. The PDFs describe perceptions accumulated over the preceding five years, so update dates do not make all responses contemporaneous.

**Validation:** unique IDs and coordinate pairs; exact ID/name/coordinate/feature/population matches to `MY.txt`; valid numeric ranges and dates; all selected Numbeo values verified against PDFs; exact decimal risk complements; resolvable archive members and PDF source links; no missing required fields. No algorithm correctness or performance results are claimed.

**Reproducibility:** source filenames and SHA-256 fingerprints identify the supplied snapshots. Temporary extraction/validation scripts and raw inputs are not Git deliverables for this change.

| Input | SHA-256 |
|---|---|
| `MY.txt` | `0102511fbe91060bf3c67b3962ccd2ba1d9f887afe81b7aff8e184061c1280f6` |
| `numbeo_inventory.csv` | `59d54299b827b4b34d747064c665a77646e10e28bbd0a295c4c8de9fb08612af` |
| `Crime Indexes.zip` | `3d53486ebe3946680978485410e2b12b85530c855fb019d4d58b82cbaf2cc0c0` |

**Limitations and attribution:** GeoNames is the required primary source and its supplied metadata specifies CC BY 4.0. Numbeo is survey-based and self-selected: walking alone is only a proxy for delivery-driver exposure, not actual crime probabilities. Small and unequal samples, mixed update dates, city-wide averages and possible metropolitan overlap limit inference. Do not extrapolate this purposive sample to all Malaysia or claim reliable road ETAs. Preserve attribution and check provider permissions before broader redistribution; no raw PDFs are included in this commit. Missing empirical scores in future additions must be excluded or left explicitly missing, never fabricated. Any synthetic sensitivity inputs must remain separate and clearly labelled.

## Approach A — Safety-Aware 2-opt

1. Build a **valid full tour** using distance-only Nearest Neighbor as an initial baseline.
2. Calculate the full tour's cost, including every arrival time and the return-to-depot distance.
3. Try reversing every segment that does not include the two depot endpoints.
4. Recalculate the **entire route** after each reversal, since a changed order changes later arrival times and which city's day/night risk applies. Compare the shared alpha-weighted scaled cost with unchanged experiment constants.
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
        candidate = copy of route with positions [i..j] reversed
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

   `rank = alpha * (distanceSoFar + directDistance(currentCity, depot)) / (n * L) + (1 - alpha) * riskSoFar / (100 * m)`.

   This is a **weak, optimistic completed-cost bound**: direct return distance is a lower bound under the Haversine metric, and remaining risk is bounded below by zero. Use the **full instance** `n`, `m` and fixed reference `L` at every depth, never the number visited. Beam pruning still prevents an optimality guarantee. At `alpha=0`, the distance term vanishes; deterministic ties matter.
5. Retain at most `k` lowest-ranked children using a **bounded max-heap**. Its root stores the *worst retained child*, so a better candidate can replace it in `O(log k)`.
6. Repeat until all selected delivery cities are visited. Add the return-to-depot leg and select the lowest **actual completed-tour cost**.

Illustrative pruning when `k = 2`:

```text
KL -> Shah Alam -> Seremban     rank 0.10   KEEP
KL -> Ipoh -> Shah Alam         rank 0.12   KEEP
KL -> JB -> Seremban            rank 0.15   DROP
```

The ranks above are fictional. A discarded route **might** have led to a better final tour. A beam width of 1 is greedy-like but is not necessarily equivalent to Nearest Neighbor.

```text
beam = [initial depot state]
while delivery cities remain:
    nextBeam = boundedMaxHeap(capacity = k)
    for state in beam:
        for city not yet visited in state:
            child = extend(state, city)  // new arrival time and risk
            priority = alpha * (child.distance + directDistance(child.lastCity, depot)) / (n * L)
                     + (1 - alpha) * child.risk / (100 * m)
            retainAmongBestK(nextBeam, child, priority)
    beam = contents(nextBeam)
return lowest-cost completed route after including return to depot
```

Share the time/risk transition and scoring constants with `RouteEvaluator`; recompute the completed winning tour with that evaluator before reporting it. States with the same visited set and last city but different arrival times are not interchangeable.

**DSA:** `PriorityQueue` configured as a **max-heap** for bounded top-`k` selection; bitmask for visited cities; parent-linked states; distance matrix/graph. With constant-time candidate ranking and up to `k` states per layer, expect **O(k n² log(k+1))** time for a straightforward bounded-heap approach and up to **O(kn + n²)** retained-state/matrix space. A more expensive heuristic changes complexity; analyse the *implemented* version. For very large `n`, use a `BitSet` rather than a single integer mask.

## Fair testing

Use identical city sets, depot, verified day/night scores, departure times, fixed model assumptions, `alpha` and normalisation constants for all comparisons. Compare a **distance-only Nearest Neighbor baseline** (not a third redesigned solution), 2-opt, and Beam Search. Score the baseline with the same evaluator even though its construction ignores risk. Record:

- Tour, arrival times/day-night choices, total distance, total arrival risk, both scaled components and combined cost; also mean leg distance and mean delivery risk.
- End-to-end runtime, candidate evaluations, 2-opt passes, beam-pruned candidates and memory if measured.
- Configuration: selected GeoNames IDs, depot, dataset provenance, `alpha`, `n`, `m`, full-reference `L`, start time, beam width, implementation version and random seed (if used).

Suggested experiments: city counts **5/8/12/18** (including the depot); departures **07:00/13:00/18:00**; `alpha=0,0.25,0.5,0.75,1`; beam widths `k=1,3,5,10,...`; 2-opt sensitivity to initial route. These are proposed runs, not results. For small `n`, exhaustive enumeration can provide a **verified optimum**; evaluate both directions because time-dependent risk need not be symmetric. No global optimality claim otherwise.

Predeclare nested subsets and keep them identical for both algorithms. One geographically spread family with Kuala Lumpur as depot: **5** = Kuala Lumpur, Ipoh, Kota Bharu, Kuantan, Johor Bahru; **8** adds Alor Setar, Kuala Terengganu, Malacca; **12** adds Kangar, George Town, Seremban, Muar; **18** adds the remaining six rows. Use the CSV IDs, not row positions, in saved configurations. Also test a separately labelled compact/local family and the seven-city `contributors >= 30` subset (George Town, Ipoh, Kuala Lumpur, Petaling Jaya, Shah Alam, Klang, Johor Bahru). The latter loses east-coast coverage and still includes an older Ipoh update, so it is a sensitivity check, not a replacement claimed to be unbiased. Do not pick subsets after seeing which algorithm wins.

Eighteen stops support meaningful local-search and beam-width comparisons without needing a huge instance; small subsets support exact checks. Runtime scaling over 5–18 cities is limited evidence, not proof of asymptotic complexity. Keep speed, service time and waiting fixed in main runs. Any perturbation study must be separate and labelled synthetic; do not overwrite empirical CSV values.

**X-factor target:** Show the **distance-versus-safety trade-off** and how increasing beam width affects route quality and runtime. Real insight and reproducible experiments matter more than a decorative interface.

## Correctness checks

- Every delivery city appears exactly once; depot is first and last.
- Return distance counts, but returning to depot does not add another delivery-risk score.
- Delivery time is **exactly zero**; arrival at 06:59, 07:00, 18:59 and 19:00 is classified correctly; cross midnight correctly. No waiting is allowed.
- Both approaches call one shared route evaluator for their final reported costs.
- 2-opt never reverses depot endpoints and recomputes times after each change.
- Beam Search correctly handles `k=1`, ties, empty candidate layers, and all cities visited.
- `alpha=1` removes risk from cost; `alpha=0` removes distance's direct contribution, but travel still changes arrival times. Check `alpha=0.5`, out-of-range weights, fixed shared denominators, bounds `[0,1]`, and partial-beam scoring with full-instance denominators.
- Verify `day_risk=100-day_safety`, `night_risk=100-night_safety`, equal day/night values, all-day/all-night routes, and no forced nighttime uplift. All stops add **0 minutes**.
- Source-backed versus simulated values are unmistakably identified; no invented results.

## Repository layout and planned implementation

```text
README.md
AGENTS.md
CLAUDE.md
docs/Project_2627T1.pdf  # official brief, present
data/processed/cities_cleaned.csv  # cleaned data, present
data/raw/               # proposed, only if licence/storage permits
src/                    # proposed: shared model, evaluator, algorithms, CLI
tests/                  # proposed: time boundaries and route-validity tests
experiments/            # proposed: configurations, raw outputs and summaries
```

No runtime commands are advertised yet: source code has not been added. Update this section with the *actual* directory layout, dependencies and build/run instructions when implementation starts.

## Project deliverables

From the provided CS201 project brief:

- **Week 12 Sunday, 11 PM:** submit via eLearn a `G<X>T<X>.zip` containing *all source code necessary to reproduce the experiments*, datasets in the used format, clearly labelled experiment folders and a README with run instructions; also submit presentation slides.
- **Week 13:** group presentation, critique and mandatory peer evaluation. All members should be able to explain both designs.
- Java, Python or another approved language is permitted. Include required third-party libraries and actual run instructions; only the most recent eLearn submission is retained.
- Slides: motivation/why classic TSP is insufficient; modified input/output/constraints; algorithms/data structures and pseudocode; complexity, actual experiments, trade-offs, limitations and AI-use acknowledgement.
- Acknowledge AI tools, how/where used, original team contributions and **three representative prompts** in the project report submission. For this change, Codex assisted with source extraction, matching/selection, validation and documentation under the team's supplied model decisions; preserve this request as one real prompt, and record two other genuine prompts when available. **No fabricated experimental results or evidence. No GenAI assistance answering queries during the live presentation/demo.** Everyone must be able to explain and modify the work.
- Peer evaluation is mandatory; non-submission is penalised. Questions must be posed to the assigned other team. Raise group issues by Week 10; use the course Teams Project Clarification Forum for assignment clarifications.
- Project grading: interestingness 10%, experimentation 30%, presentation 40%, other-team critique 10%, X-factor 10%. Project is worth 20% of the course grade.

## Open decisions

The 18-city dataset, empirical day/night formulas, shared scaled objective and seven model assumptions are settled. Final depot/departure/alpha experiment grid (suggestions above); 2-opt start and pass cap; Beam Search width and tie-breaking (weak rank specified above as the first version); language/build tooling; run commands and broader data-redistribution permissions remain to be finalised. Record changes in [AGENTS.md](AGENTS.md).
