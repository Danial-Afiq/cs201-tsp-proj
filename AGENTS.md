# Guidance for AI coding agents

Read this file and [README.md](README.md) before changing the repository. Read [docs/Project_2627T1.pdf](docs/Project_2627T1.pdf) when work depends on assignment requirements, presentation content, dataset rules, deliverables, grading, peer evaluation, or AI-use policy.

## Source of truth

The official project brief is authoritative. This file records the team's current interpretation and project decisions. If it conflicts with the brief, follow the brief and correct the documentation.

Do not present suggestions, pseudocode, planned architecture, experiments, or untested behavior as lecturer requirements or completed work.

## Project objective and status

The project proposes a Safety-Aware Day/Night TSP for a delivery driver visiting Malaysian locations. It changes the classic distance-only objective by including a safety cost that depends on the time of arrival.

The two proposed redesigned approaches are:

- Safety-Aware 2-opt, a local search over complete tours; and
- Safety-Aware Beam Search, a bounded search over partial tours.

They are intended to differ meaningfully in algorithm and data structure design. Their detailed implementations remain open to experimentation and justification.

**Current status (2026-10-26):** `data/processed/cities_cleaned.csv` is a validated 43-row master dataset. The algorithms, automated tests, experiments, and benchmark results have not yet been implemented or run. Never claim otherwise without repository evidence.

## Agreed problem model

Keep these decisions consistent across implementations and documentation:

1. Choose one depot for a problem instance. Visit every selected non-depot location exactly once and return to the depot.
2. Use the weighted objective `C = alpha * D_scaled + (1 - alpha) * R_scaled`, with `0 <= alpha <= 1`.
3. Use the stored Numbeo scores: `day_risk = 100 - day_safety` and `night_risk = 100 - night_safety`.
4. Select risk from the arrival time at each non-depot destination. Do not charge another arrival risk for the final return to the depot.
5. Day is `07:00 <= local time < 19:00`; night is `19:00 <= local time` or `local time < 07:00`.
6. Travel speed is a constant 60 km/h. Service time is zero. The driver leaves immediately and cannot wait for daylight.
7. Compute geographical distance from the stored WGS84 coordinates using Haversine distance. Treat it as a simplified model rather than road distance.
8. Recompute downstream arrival times and risks whenever route order changes. Handle midnight, multi-day travel, and day/night boundaries correctly.

Crime Index is contextual data and is not a substitute for day or night arrival risk. Safety scores are survey perceptions, not probabilities.

## Normalisation

The exact definitions of `D_scaled` and `R_scaled` are open design choices. A chosen method must be mathematically sound, documented, and applied consistently to all algorithms compared on the same problem instance.

Do not hard-code a normalisation constant derived from one temporary subset as a permanent project rule. Report raw distance and risk alongside scaled components so results remain interpretable. If the normalisation design changes, update the evaluator, tests, experiment metadata, and documentation together.

## Master dataset

`data/processed/cities_cleaned.csv` contains 43 reliably matched populated locations from 48 Numbeo records. It is a source pool, not a mandatory route and not an experiment-specific sample.

Future code may select subsets by region, size, data quality, or another justified experimental purpose. Do not delete valid rows from the master data merely because locations are close together, far apart, in Sabah or Sarawak, have few contributors, or make one algorithm inconvenient.

The five excluded Numbeo records are Gombak, Kedah, Langkawi, Penang, and Selangor. README explains why each lacks a safe one-to-one city match. Do not silently remap regional or island scores to convenient cities.

### CSV contract

The 16 columns are:

```text
geonameid,name,latitude,longitude,feature_class,feature_code,admin1_code,
population,crime_index,day_safety,night_safety,day_risk,night_risk,
numbeo_contributors,numbeo_last_update,numbeo_url
```

Treat `admin1_code` as text and preserve leading zeros. Use `geonameid` as the stable identity. Preserve GeoNames coordinates and classifications as source values. Validate numeric ranges, ISO dates, unique IDs, nonmissing required fields, and exact risk complements when loading.

The master file intentionally contains no routes, distance matrix, arrival times, scaled values, or departure-specific risk. Compute those for each problem instance.

The removed columns `data_quality_flag`, `numbeo_pdf_pages`, `numbeo_source`, and `numbeo_location` must not be restored without an explicit team decision. Contributor count and update date remain available for quality analysis.

## Data provenance and matching

- `MY.txt` is the lecturer-provided primary source and follows the 19-field layout in `Metadata.txt`.
- The Numbeo inventory and 48 PDFs are supplementary sources for crime, safety, contributor, date, and URL fields.
- The optional XLSX file is a convenience copy, not the geographic authority.
- Match names using primary, ASCII, and alternate names, then verify feature type, state, coordinates, population, and PDF location context.
- Prefer a specific populated-place record over an administrative area, island, terrain feature, airport, river, or port with the same name.
- Keep one row per GeoNameID. Do not fabricate, impute, average, or transfer scores between different places.
- Preserve GeoNames attribution and document Numbeo limitations and permissions in user-facing work.

Important resolved aliases include Ampang Jaya to Ampang `1735168`, Bandar Penggaram to Batu Pahat `1732687`, Nilai to Kampung Baharu Nilai `1771287`, and Skudai (Sekudai) to Skudai `1732745`. Serdang uses `1744366`; the PDF's nearby-city distances rule out the similarly named Selangor record.

## Algorithm implementation flexibility

The current algorithm names and high-level ideas are team decisions. Internal structures and heuristics remain proposals until implemented and tested.

For 2-opt, a valid initial tour, segment-reversal policy, improvement strategy, tie handling, and stopping rule may be chosen based on evidence. Re-evaluate the full affected route logic because arrival-time risk can change after a move.

For Beam Search, state fields, ranking, pruning, deduplication, reconstruction, and beam-width handling may be refined. Partial states that reach the same city after visiting the same set are not automatically equivalent if their arrival times differ.

Arrays, lists, matrices, bit sets, priority queues, parent pointers, and other structures are options rather than mandatory choices. Select structures that serve the final algorithm and explain their time and space costs. Do not add a data structure solely to make the project look more complex.

Shared evaluation logic is strongly preferred so both approaches use the same distance, time, risk, scaling, and tour-validity rules. Keep algorithm-specific search logic separate from data loading and route evaluation.

## Engineering and testing guidance

- Inspect the repository before editing and keep changes within the requested scope.
- Prefer small, testable components and standard-library dependencies where practical.
- Reject invalid `alpha`, malformed rows, duplicate IDs, missing required values, impossible coordinates, and invalid tours with clear errors.
- Test route validity, risk complements, Haversine symmetry and zero diagonal, day/night cutoffs, midnight and multi-day travel, zero service time, no waiting, and final-depot handling.
- Test both algorithms with the same instances and evaluator. Include edge cases such as two-city instances, ties, equal day/night scores, all-day or all-night arrivals, and low beam widths.
- Check that changing route order changes downstream times without changing source data.
- Use deterministic seeds or tie rules when reproducibility requires them.
- State theoretical complexity for the actual implementation. Measure runtime and memory separately from asymptotic claims.
- Run only tests that exist and report their real results. Do not invent logs, benchmarks, screenshots, or successful checks.

## Experiments

Experiment design is not final. Reasonable studies may vary subset size, region, depot, departure time, `alpha`, beam width, 2-opt choices, or normalisation. Each comparison must hold the problem instance and scoring rules constant across algorithms.

Record enough metadata to reproduce each run: dataset version, selected GeoNameIDs, depot, departure time, speed, day/night definition, scaling method, parameters, implementation version, and random seed when relevant.

Useful evaluation measures may include route validity, total and scaled distance, total and scaled risk, combined cost, runtime, memory, stability, number of explored states or improvements, and gap to exhaustive search on small instances. Include cases where a proposal performs poorly and explain limitations.

## Documentation and submission

Keep README and this file consistent with implemented behavior. Update status language when evidence changes. Preserve the distinction among agreed assumptions, proposals, implemented features, tested behavior, and experimental findings.

The final submission and presentation must satisfy the official brief, including reproducible source code and data, run instructions, experimental results, complexity and trade-off discussion, peer evaluation, and the AI-use acknowledgement. Team members must understand and defend the work. GenAI cannot answer live presentation or demonstration questions.
