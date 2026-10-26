# SafeRoute: Safety-Aware Day/Night TSP

CS201 Data Structures & Algorithms project for *Beyond the Classic TSP*.

> **Current status (2026-10-26):** The cleaned master dataset contains 43 reliably matched Malaysian locations with PDF-verified Numbeo values. Safety-Aware 2-opt and Safety-Aware Beam Search are proposed solutions. They have not yet been implemented, tested, or evaluated.

The official [project brief](docs/Project_2627T1.pdf) is the authority for assignment requirements. This README explains our current project direction and data decisions. It does not add requirements to the brief.

## What the assignment requires

The project starts from the classic Travelling Salesperson Problem (TSP). Each team must identify a realistic assumption that the classic problem does not handle, define a corresponding TSP variant, and implement and evaluate at least two approaches that differ meaningfully in algorithm design, data structure design, or both.

The brief requires the lecturer-provided GeoNames `MY.txt` file as the primary dataset. Section 5 asks teams to explain:

1. the records selected and columns used;
2. why the partial or augmented dataset was selected;
3. the filtering or preprocessing performed; and
4. the supplementary data or derived attributes added.

The presentation must cover the motivation, variant inputs and constraints, redesigned approaches, pseudocode, complexity, experiments, trade-offs, limitations, findings, and acknowledged AI use.

## Our proposed problem

A delivery driver carrying valuable goods must visit a chosen set of Malaysian locations once and return to a depot. A shortest-distance route may reach some locations at night, when the reported perception of safety is lower. Our proposed variant therefore considers both geographical distance and arrival-time-dependent safety.

The planned output is a closed tour, its total distance, arrival times, total arrival risk, scaled distance and risk components, and combined cost. Experiment code will choose a depot and a subset from the master dataset. The CSV order is not a route.

## Proposed solutions

| Approach | Main idea | Likely strengths | Likely limitations |
| --- | --- | --- | --- |
| Safety-Aware 2-opt | Start from a valid tour and reverse route segments when the shared objective improves. | Simple local improvement and easy to explain. | May stop at a local optimum and may depend on the starting tour. |
| Safety-Aware Beam Search | Build routes in stages while retaining several promising partial routes. | Explores several alternatives without exhaustive search. | Beam pruning can discard a better final route and performance depends on design choices. |

These descriptions are proposals. The team may refine initialisation, state representation, ranking, tie handling, stopping rules, pruning, and supporting data structures after testing. Any final implementations must remain meaningfully different, use the same problem definition, and be justified with complexity and experimental evidence.

A distance-only method such as Nearest Neighbor may be used as a baseline. It is not one of the two proposed redesigned solutions unless the team deliberately changes the project plan and documents why.

## Cost model and agreed assumptions

The proposed objective is:

```text
C = alpha * D_scaled + (1 - alpha) * R_scaled
```

`D_scaled` represents total route distance on a documented scale. `R_scaled` represents total arrival risk on a documented scale. `alpha` is between 0 and 1. A larger `alpha` gives more weight to distance, while a smaller value gives more weight to safety.

The exact normalisation method remains an implementation and experiment decision. It must be mathematically sound, documented, and applied consistently to every algorithm being compared on the same problem instance. Constants derived from one temporary city subset must not become permanent project requirements.

The team has agreed on these modelling assumptions:

| Assumption | Current decision |
| --- | --- |
| Route | Start at a chosen depot, visit each selected non-depot location exactly once, and return to the depot. |
| Safety input | Use the actual Numbeo daytime and nighttime walking-alone safety scores stored in the master dataset. |
| Risk | `day_risk = 100 - day_safety`; `night_risk = 100 - night_safety`. |
| Arrival risk | Choose the destination's day or night risk from its arrival time. Do not add a second risk charge for the final return to the depot. |
| Day | `07:00 <= local time < 19:00`. |
| Night | `19:00 <= local time` or `local time < 07:00`. |
| Speed | Constant 60 km/h. |
| Service time | Zero minutes at each stop. |
| Waiting | No waiting for a safer time period. |
| Distance | Haversine distance from GeoNames coordinates, used as a simplified geographical model rather than road distance. |

Changing a route changes later arrival times, so the applicable day/night risks may also change. If every arrival happens in the same time period, the risk total may be identical for several routes. Numbeo scores are perception scores, not probabilities of crime.

## Master dataset

The project uses [data/processed/cities_cleaned.csv](data/processed/cities_cleaned.csv) as a reusable master dataset. It contains all Numbeo locations that could be matched reliably to a specific populated-place record in the supplied GeoNames snapshot. It is not preselected for one route, algorithm, region, contributor threshold, or experiment.

Algorithms should select and document suitable subsets at experiment time. A cross-sea route between Peninsular Malaysia and East Malaysia may be mathematically valid in a complete Haversine graph but unrealistic for a road-delivery story, so experiments must explain any geographical constraints they apply.

### 1. Records selected and columns used

The Numbeo inventory has 48 records. The master CSV includes **43** and excludes **5** that cannot be assigned safely to a specific populated-place record.

All included rows use feature class `P`. Their feature codes are `PPL`, `PPLA`, `PPLA2`, `PPLC`, `PPLG`, or `PPLX`. `PPLX` records such as Skudai and Subang Jaya remain in the master data because they are specific populated locations and the master is not enforcing a narrow experiment subset.

Most labels match a GeoNames primary or ASCII name directly. Important alias matches are:

| Numbeo label | GeoNames record used | Reason |
| --- | --- | --- |
| Ampang Jaya | Ampang (`1735168`) | `Ampang Jaya` is an alternate name; the coordinates agree with the PDF's nearby-city distances. |
| Bandar Penggaram | Batu Pahat (`1732687`) | `Bandar Penggaram` is an alternate name for the populated place. |
| Kangar, Perlis | Kangar (`1736278`) | The qualifier identifies the Perlis capital unambiguously. |
| Nilai | Kampung Baharu Nilai (`1771287`) | `Nilai` is an alternate name for this populated-place record. |
| Skudai (Sekudai) | Skudai (`1732745`) | The parenthetical spelling is an alternate form. |

For Serdang, the PDF's nearby-city distances do not fit the Selangor record. They support the northern record `1744366` in the supplied GeoNames data. Other repeated names were resolved by preferring the populated-place record and checking state, coordinates, population, feature code, alternate names, and PDF context. Examples include Kota Bharu (`1736376`), Kuala Lumpur (`1735161`), Kuching (`1735634`), Kajang (`10941913`), Labuan (`1733782`), and Putrajaya (`6697380`).

### 2. Justification for selection

Every reliably matched populated location is included, even when it:

- is close to another included city;
- has few Numbeo contributors or an old update date;
- is in Sabah, Sarawak, or Labuan;
- uses a GeoNames code such as `PPLX`; or
- may be unsuitable for a particular future route.

This keeps data cleaning separate from experimental design. Teammates can later choose regional, size-based, or quality-focused subsets without rebuilding the source join.

The five exclusions are:

| Numbeo record | Why excluded |
| --- | --- |
| Gombak | The exact source match is an `ADM2` district, with no reliable specific populated-place match in this snapshot. |
| Kedah | It is a state-level label (`ADM1`); its score must not be assigned to Alor Setar or another city. |
| Langkawi | The label refers to an island or district. GeoNames also lists `Langkawi` as an alternate name for Kuah, but the PDF does not justify treating the island-wide score as a Kuah city score. |
| Penang | The label can mean the state or island and is also an alternate name for George Town. A separate George Town Numbeo record exists, so there is no unique additional city match. |
| Selangor | It is a state-level label (`ADM1`); it must not be assigned to Kuala Selangor or another city. |

### 3. Filtering and preprocessing

The cleaning process:

1. Parsed all 71,709 tab-separated GeoNames rows using the 19 fields documented in `Metadata.txt`.
2. Read all 48 records in `numbeo_inventory.csv`.
3. Matched Numbeo labels against GeoNames primary names, ASCII names, and alternate names.
4. Resolved duplicate names using feature class and code, state code, coordinates, population, and the nearby-location context in the original PDF.
5. Kept one unique populated-place GeoNameID for each accepted Numbeo record.
6. Copied GeoNameID, name, coordinate text, feature fields, administrative code, and population directly from `MY.txt`.
7. Verified Crime Index, overall Safety Index, daytime safety, nighttime safety, contributor count, and update date against every PDF in `Crime Indexes.zip`: 48 PDFs and 288 field comparisons, with no mismatches.
8. Converted update dates to `YYYY-MM-DD`, extracted the canonical Numbeo URL from each PDF, and calculated the two risk complements to two decimal places.
9. Did not impute, extrapolate, average, or replace missing values. The 48 inventory rows had all required Numbeo values.

The optional XLSX copy was not used as the geographic authority. `MY.txt` remains the lecturer-provided primary source.

### 4. Supplementary and derived attributes

The cleaned CSV has 16 columns:

| Column | Meaning |
| --- | --- |
| `geonameid` | Unique GeoNames identifier for the matched populated place. |
| `name` | Original GeoNames primary name. |
| `latitude`, `longitude` | Original WGS84 coordinates used for Haversine distance. |
| `feature_class`, `feature_code` | Original GeoNames classification. |
| `admin1_code` | Original first-level administrative code, stored as text so values such as `01` and `02` keep their leading zeros. |
| `population` | Original GeoNames population value, retained as context rather than a routing weight. |
| `crime_index` | Numbeo Crime Index from the PDF, retained as context. |
| `day_safety`, `night_safety` | Numbeo walking-alone safety scores used by the model. |
| `day_risk`, `night_risk` | Derived complements `100 - safety`. |
| `numbeo_contributors` | Contributor count reported in the PDF. |
| `numbeo_last_update` | PDF update date in ISO format. |
| `numbeo_url` | Canonical Numbeo city page extracted from the PDF links. |

The schema intentionally omits `data_quality_flag`, `numbeo_pdf_pages`, `numbeo_source`, and `numbeo_location`. Quality can be assessed from contributor counts and dates, while the repository documentation records the cleaning method and alias decisions.

## Data limitations

- Numbeo data reflects self-selected perceptions gathered over the preceding five years. It is not a crime probability or a measurement specific to delivery drivers.
- Contributor counts vary substantially, and update dates range from 2021 to 2026. Low counts and older dates were retained because they describe data quality rather than matching validity.
- City-level scores hide neighbourhood and time-of-day variation beyond the two supplied safety measures.
- GeoNames population and classification values belong to the supplied snapshot and may not match current official statistics or municipal boundaries.
- Haversine edges do not follow roads, bridges, ferries, or borders. They can cross water and should not be described as realistic driving routes.
- Several urban records overlap geographically. Experiments should account for this when choosing subsets and interpreting results.

## Potential experiments

The following are options for the team to refine rather than fixed requirements:

- compare both proposed algorithms and a common baseline on the same selected instances;
- vary subset size, region, depot, departure time, `alpha`, beam width, and 2-opt design choices;
- test Peninsular-only, East Malaysia, metropolitan, nationwide, or contributor-based subsets;
- use tiny instances where exhaustive enumeration can provide a reference optimum;
- evaluate sensitivity to normalisation choices, provided each comparison uses the same sound scaling method;
- study solution cost, raw and scaled distance, raw and scaled risk, runtime, memory, route validity, stability, and gap to a reference solution when available.

Experiments should record enough information to reproduce each instance and should report losing cases and limitations as well as improvements. Do not claim optimality, correctness, or performance without evidence.

## Deliverables, rubric, and AI use

The brief requires a Week 12 Sunday 23:00 submission through eLearn and Week 13 peer evaluation. The submission ZIP must contain the source code, data used, meaningfully organised experiment files, and a README with the actual folder structure and run instructions. Presentation slides are also required.

The project contributes 20% of the course grade. The rubric allocates 10% to problem interestingness, 30% to experimentation, 40% to presentation, 10% to critique of another team's design or algorithm, and 10% to an X-factor. A fancy interface alone is not an X-factor.

AI assistance is allowed for activities listed in the brief, but the team remains responsible for every decision and deliverable. The final report must acknowledge tools, explain where they were used, identify the team's original work, and include three real representative prompts. GenAI cannot answer questions during the live presentation or demonstration.
