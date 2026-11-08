# SafeRoute: Safety-Aware Day/Night TSP

SafeRoute is an SMU CS201 redesign of the Traveling Salesperson Problem for a delivery driver visiting Malaysian locations. A valid tour starts and ends at one depot and visits every selected city exactly once. Unlike classic distance-only TSP, SafeRoute minimizes a weighted combination of normalized distance, elapsed journey time, and arrival risk. Risk changes with the arrival clock, so route order and overnight rests matter.

The default objective is **40% distance, 20% journey time, and 40% arrival risk** (`alpha=0.4`, `beta=0.2`). The 43-city processed dataset uses GeoNames as the primary geographic source and Numbeo day/night safety perceptions as supplementary attributes.

## Algorithms

| Implementation | Submission role | Design |
| --- | --- | --- |
| `beam_search.py` | Primary approach 1 | Ordinary Safety-Aware Beam Search keeps a bounded set of partial tours. It uses an integer visited bit mask, parent-linked states, a distance matrix, and a bounded heap. Default beam width: 100. |
| `two_opt.py` | Primary approach 2 | Safety-Aware 2-opt improves a complete tour by reversing route segments and fully re-evaluating time-dependent risk and rests. The default is best improvement from a distance-only nearest-neighbor tour. |
| `lookahead_beam_search.py` | Optional X-factor | A more expensive Beam Search variant that ranks each prefix by a greedy completed tour instead of accumulated cost alone. Default beam width: 20. |

The two primary approaches differ meaningfully: Beam Search explores many bounded partial routes, while 2-opt performs local search over one complete route. All implementations share the same data loader, problem model, objective, and full-tour evaluator from `beam_search.py`.

## Dataset

All runs use [data/processed/cities_cleaned.csv](data/processed/cities_cleaned.csv): 43 Malaysian populated places, one row per GeoNameID.

**Records selected.** The lecturer-provided GeoNames file `MY.txt` (71,709 rows) is the primary source. We kept the places that have a Numbeo crime-and-safety page. Of the 48 Numbeo records, 43 could be matched reliably to a specific populated-place record (feature class `P`). Five were excluded because they do not refer to one city:

| Excluded record | Why |
| --- | --- |
| Gombak | Matches only an `ADM2` district, not a specific populated place. |
| Kedah, Selangor | State-level labels (`ADM1`); their scores must not be assigned to one city. |
| Langkawi | An island or district score, not a score for the town of Kuah. |
| Penang | Means the state or island; George Town already has its own Numbeo record. |

**Columns used.** From GeoNames: `geonameid`, `name`, `latitude` and `longitude` (for Haversine distance), `feature_class`, `feature_code`, `admin1_code` (kept as text so leading zeros survive), and `population` (context only).

**Filtering and preprocessing.**
- Numbeo labels were matched against GeoNames primary, ASCII and alternate names.
- Duplicate names were resolved by feature code, state, coordinates, population and the nearby-city distances in each Numbeo PDF. Examples: Ampang Jaya → Ampang, Bandar Penggaram → Batu Pahat, Nilai → Kampung Baharu Nilai.
- Every Numbeo value was checked against its PDF: 48 PDFs, 288 fields, no mismatches.
- No values were imputed, averaged, or moved between places. GeoNames coordinates and classifications are unchanged.

**Supplementary and derived attributes.**
- From Numbeo: `day_safety` and `night_safety` (walking-alone safety scores used by the model), plus `crime_index`, `numbeo_contributors`, `numbeo_last_update` and `numbeo_url` (context and data quality).
- Derived: `day_risk = 100 - day_safety` and `night_risk = 100 - night_safety`.
- Distances, arrival times and scaled costs are not stored. They are computed for each problem instance.

**Subsets used in experiments.** The 43-row file is a source pool, not a fixed route.
- The 9-city studies sample from the 19 Peninsular locations with at least 15 Numbeo contributors. This avoids cross-sea legs and very thin survey data.
- The larger studies use the regional subsets listed under the primary experiments below.

**Sources and attribution.**
- Geographic data: [GeoNames](https://www.geonames.org/), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Safety data: [Numbeo](https://www.numbeo.com/crime/). These scores are perceptions from self-selected contributors, not crime probabilities. Contributor counts vary, and update dates range from 2021 to 2026.

## Requirements

- Python 3.10 or newer. Commands below use `python3`; on Windows, use `python` (or `py`) instead.
- Python standard library only; no package installation is required

Package the final submission as `G<X>T<X>.zip` while preserving the paths below. After extraction, open a terminal in the repository root and run all commands from that directory.

## Repository layout

```text
.
|-- beam_search.py                     # Ordinary Beam Search and shared model
|-- two_opt.py                         # Safety-Aware 2-opt
|-- lookahead_beam_search.py           # Optional lookahead variant
|-- data/
|   `-- processed/cities_cleaned.csv   # 43 validated Malaysian locations
|-- experiments/
|   |-- compare_two_opt.py             # Primary experiments E1 and E2
|   |-- lookahead_gap.py               # X-factor experiment
|   `-- results/
|       |-- comparison.json            # Recorded full primary experiment
|       `-- lookahead_gap.json         # Recorded X-factor experiment
|-- tests/                             # Unit and integration tests
|-- docs/
|   |-- beam_search.md                 # Model, algorithm, and complexity details
|   |-- two_opt.md                     # 2-opt design and experiment discussion
|   `-- Project_2627T1.pdf             # Official project brief
`-- README.md
```

## Run the algorithms

City names or GeoNameIDs are accepted. The depot is added automatically; omitting `--cities` selects all 43 records. `--output` saves detailed reproducibility metadata for the two primary algorithms.

Ordinary Beam Search:

```bash
python3 beam_search.py --depot "Kuala Lumpur" --cities "Ipoh" "Johor Bahru" "Kuantan" "Malacca" --departure 18:00 --alpha 0.4 --beta 0.2 --beam-width 100 --output beam_run.json
```

Safety-Aware 2-opt:

```bash
python3 two_opt.py --depot "Kuala Lumpur" --cities "Ipoh" "Johor Bahru" "Kuantan" "Malacca" --departure 18:00 --alpha 0.4 --beta 0.2 --strategy best --initial nearest-neighbor --output two_opt_run.json
```

Lookahead Beam Search:

```bash
python3 lookahead_beam_search.py --depot "Kuala Lumpur" --cities "Ipoh" "Johor Bahru" "Kuantan" "Malacca" --departure 18:00 --alpha 0.4 --beta 0.2 --beam-width 20
```

Use `python3 <script> --help` for every supported option.

## Reproduce the primary experiments

`experiments/compare_two_opt.py` compares Safety-Aware 2-opt with **ordinary** Beam Search using identical problem instances and the default 40/20/40 objective.

Experiments 1 and 2 share this runner because they use the same algorithms and evaluation framework. A single run executes both experiments and reports their results in separately labelled sections.

- **E1 - solution quality:** 200 seeded random 9-city Peninsular instances, with departures sampled from 06:00, 10:00, 14:00, and 18:00. Every instance is solved exactly by brute force over all `8!` stop orders. The main metric is mean optimality gap, `(heuristic cost - optimum) / optimum`.
- **E2 - larger datasets:** 15-city Klang Valley (Kuala Lumpur depot), 37-city Peninsular Malaysia (Kuala Lumpur depot), the same 37 cities (Johor Bahru depot), 6-city East Malaysia (Kuching depot), and all 43 cities (Kuala Lumpur depot). Each runs at 08:00 and 18:00. The reported cost advantage is `(Beam W=100 cost - 2-opt cost) / Beam W=100 cost`; positive values favor 2-opt.
- **Additional analyses:** 40 morning-departure trials and 20 objective-weight trials by default, plus runtime and memory measurements. The relevant defaults are therefore 200/40/20.

Quick validation run:

```bash
python3 experiments/compare_two_opt.py --quick --output experiments/results/quick_check.json
```

`--quick` reduces the small studies to one trial and skips the 37-city and 43-city runs. It checks the pipeline; it does not reproduce the full reported evidence.

Full reproduction:

```bash
python3 experiments/compare_two_opt.py --output experiments/results/full_reproduction.json
```

Allow roughly **30-45 minutes**, depending on hardware. The terminal shows a readable summary; the JSON file keeps the detailed inputs, routes, metrics, timings, and metadata. The submitted baseline record is `experiments/results/comparison.json`.

## Reproduce the X-factor experiment

The optional study compares ordinary and Lookahead Beam Search against brute force on 200 seeded 9-city Peninsular instances. Its default beam widths are 1, 20, and 100, with departures sampled from 06:00, 10:00, 14:00, and 18:00.

```bash
python3 experiments/lookahead_gap.py --output experiments/results/lookahead_reproduction.json
```

The submitted record is `experiments/results/lookahead_gap.json`; the command above writes to a separate file so the record is not overwritten.

This is a small-instance optimality-gap study, not a third primary submission approach and not a comparison with 2-opt.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Assumptions and limitations

- Distances are straight-line Haversine distances, not road-network distances; speed is fixed at 60 km/h and service time is zero.
- Day is 07:00 to before 19:00. Numbeo safety scores are perception-based indicators, not probabilities of harm.
- Mandatory and optional rests end at 07:00; the shared evaluator chooses the cheapest valid rest schedule for each complete tour.
- Cross-sea Haversine legs in the all-43-city study are an abstract stress test, not realistic driving routes. Regional subsets are more operationally meaningful.
- Normalization depends on the selected instance, so combined costs should only be compared between algorithms solving the same instance.
