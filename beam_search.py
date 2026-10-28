"""Safety-aware day/night TSP using only the Python standard library.

Run ``python3 beam_search.py --help`` for command-line options. Data loading,
problem construction and evaluate_tour() are independent of the search so a
future 2-opt implementation can use exactly the same model and objective.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import itertools
import json
import math
import time
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Sequence
from urllib.parse import urlsplit


EARTH_RADIUS_KM = 6371.0
SPEED_KMH = 60.0
MINUTES_PER_DAY = 1440
DAY_START_MINUTES = 7 * 60
DAY_END_MINUTES = 19 * 60
IMPLEMENTATION_VERSION = "1"
DEFAULT_DATA = Path(__file__).resolve().parent / "data/processed/cities_cleaned.csv"
CSV_COLUMNS = (
    "geonameid", "name", "latitude", "longitude", "feature_class",
    "feature_code", "admin1_code", "population", "crime_index", "day_safety",
    "night_safety", "day_risk", "night_risk", "numbeo_contributors",
    "numbeo_last_update", "numbeo_url",
)


@dataclass(frozen=True, slots=True)
class City:
    geonameid: int
    name: str
    latitude: float
    longitude: float
    feature_class: str
    feature_code: str
    admin1_code: str
    population: int
    crime_index: float
    day_safety: float
    night_safety: float
    day_risk: float
    night_risk: float
    numbeo_contributors: int
    numbeo_last_update: str
    numbeo_url: str


def _decimal_field(row: dict[str, str], column: str, low: int, high: int) -> Decimal:
    try:
        value = Decimal(row[column])
    except InvalidOperation as exc:
        raise ValueError(f"{column} must be numeric") from exc
    if not value.is_finite() or not low <= value <= high:
        raise ValueError(f"{column} must be finite and in [{low}, {high}]")
    return value


def _integer_field(row: dict[str, str], column: str, minimum: int = 0) -> int:
    try:
        value = int(row[column])
    except ValueError as exc:
        raise ValueError(f"{column} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{column} must be at least {minimum}")
    return value


def load_cities(path: str | Path = DEFAULT_DATA) -> tuple[City, ...]:
    """Validate the 16-column master CSV without modifying its source values."""
    cities: list[City] = []
    seen: set[int] = set()
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source, strict=True)
        if (reader.fieldnames is None or len(reader.fieldnames) != len(CSV_COLUMNS)
                or set(reader.fieldnames) != set(CSV_COLUMNS)):
            raise ValueError("CSV header must contain exactly the 16 documented columns")
        for line, raw in enumerate(reader, start=2):
            try:
                if None in raw or any(value is None or not value.strip() for value in raw.values()):
                    raise ValueError("missing values or incorrect number of columns")
                row = {key: value.strip() for key, value in raw.items()}
                identity = _integer_field(row, "geonameid", 1)
                if identity in seen:
                    raise ValueError(f"duplicate geonameid {identity}")
                latitude = _decimal_field(row, "latitude", -90, 90)
                longitude = _decimal_field(row, "longitude", -180, 180)
                scores = {
                    key: _decimal_field(row, key, 0, 100)
                    for key in ("crime_index", "day_safety", "night_safety", "day_risk", "night_risk")
                }
                for period in ("day", "night"):
                    if scores[f"{period}_safety"] + scores[f"{period}_risk"] != Decimal(100):
                        raise ValueError(f"{period}_risk must equal 100 - {period}_safety exactly")
                if row["feature_class"] != "P":
                    raise ValueError("feature_class must be P (a populated location)")
                if date.fromisoformat(row["numbeo_last_update"]).isoformat() != row["numbeo_last_update"]:
                    raise ValueError("numbeo_last_update must use YYYY-MM-DD")
                url = urlsplit(row["numbeo_url"])
                if url.scheme not in ("http", "https") or not url.netloc:
                    raise ValueError("numbeo_url must be an absolute HTTP(S) URL")
                cities.append(City(
                    geonameid=identity, name=row["name"], latitude=float(latitude),
                    longitude=float(longitude), feature_class=row["feature_class"],
                    feature_code=row["feature_code"], admin1_code=row["admin1_code"],
                    population=_integer_field(row, "population"),
                    crime_index=float(scores["crime_index"]),
                    day_safety=float(scores["day_safety"]), night_safety=float(scores["night_safety"]),
                    day_risk=float(scores["day_risk"]), night_risk=float(scores["night_risk"]),
                    numbeo_contributors=_integer_field(row, "numbeo_contributors"),
                    numbeo_last_update=row["numbeo_last_update"], numbeo_url=row["numbeo_url"],
                ))
                seen.add(identity)
            except (ValueError, InvalidOperation) as exc:
                raise ValueError(f"CSV row {line}: {exc}") from exc
    if not cities:
        raise ValueError("CSV contains no cities")
    return tuple(cities)


def haversine_km(first: City, second: City) -> float:
    """Great-circle distance in a spherical model with radius 6371 km."""
    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second.longitude - first.longitude)
    value = (math.sin(delta_lat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, max(0.0, value))))


@dataclass(frozen=True, slots=True)
class RoutingProblem:
    cities: tuple[City, ...]
    depot: int  # Index into cities, not a GeoNameID.
    departure_minutes: float  # Local minutes since midnight on departure day.
    alpha: float
    distances_km: tuple[tuple[float, ...], ...]
    distance_divisor_km: float
    risk_divisor: float

    def cost(self, distance_km: float, risk: float) -> float:
        return (self.alpha * distance_km / self.distance_divisor_km
                + (1 - self.alpha) * risk / self.risk_divisor)


def make_problem(
    cities: Sequence[City], depot_id: int, departure_minutes: float = 8 * 60,
    alpha: float = 0.5,
) -> RoutingProblem:
    """Build one instance and its fixed scales, reusable across algorithms."""
    if not math.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError("alpha must be finite and in [0, 1]")
    if not math.isfinite(departure_minutes) or not 0 <= departure_minutes < MINUTES_PER_DAY:
        raise ValueError("departure must be in [00:00, 24:00)")
    ordered = tuple(sorted(cities, key=lambda city: city.geonameid))
    if len(ordered) < 2:
        raise ValueError("select at least two cities, including the depot")
    ids = [city.geonameid for city in ordered]
    if len(set(ids)) != len(ids) or any(type(identity) is not int or identity <= 0 for identity in ids):
        raise ValueError("cities must have unique positive integer GeoNameIDs")
    if depot_id not in ids:
        raise ValueError(f"depot GeoNameID {depot_id} is not in the selected cities")
    for city in ordered:
        for label, value, low, high in (
            ("latitude", city.latitude, -90, 90), ("longitude", city.longitude, -180, 180),
            ("day_safety", city.day_safety, 0, 100), ("night_safety", city.night_safety, 0, 100),
            ("day_risk", city.day_risk, 0, 100), ("night_risk", city.night_risk, 0, 100),
        ):
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{city.name}: invalid {label}")
        for period in ("day", "night"):
            if not math.isclose(getattr(city, f"{period}_safety") + getattr(city, f"{period}_risk"),
                                100.0, rel_tol=0, abs_tol=1e-12):
                raise ValueError(f"{city.name}: invalid {period} risk complement")
    size = len(ordered)
    distances = [[0.0] * size for _ in range(size)]
    for first in range(size):
        for second in range(first + 1, size):
            distance = haversine_km(ordered[first], ordered[second])
            distances[first][second] = distances[second][first] = distance
    longest_edge = max(max(row) for row in distances)
    return RoutingProblem(
        cities=ordered, depot=ids.index(depot_id), departure_minutes=departure_minutes,
        alpha=alpha, distances_km=tuple(tuple(row) for row in distances),
        distance_divisor_km=size * longest_edge if longest_edge > 0 else 1.0,
        risk_divisor=100.0 * (size - 1),
    )


def is_day(arrival_minutes: float) -> bool:
    local_minutes = arrival_minutes % MINUTES_PER_DAY
    return DAY_START_MINUTES <= local_minutes < DAY_END_MINUTES


def _arrival_minutes(problem: RoutingProblem, distance_km: float) -> float:
    # No service or waiting time; deriving time from distance avoids a second clock.
    return problem.departure_minutes + distance_km / SPEED_KMH * 60


def _arrival_risk(city: City, arrival_minutes: float) -> float:
    return city.day_risk if is_day(arrival_minutes) else city.night_risk


@dataclass(frozen=True, slots=True)
class Visit:
    city: City
    arrival_minutes: float  # Includes whole days after departure.
    leg_distance_km: float
    arrival_risk: float | None  # None at the initial and final depot.


@dataclass(frozen=True, slots=True)
class TourEvaluation:
    tour: tuple[int, ...]  # City indices, including depot at both ends.
    visits: tuple[Visit, ...]
    total_distance_km: float
    total_risk: float
    distance_scaled: float
    risk_scaled: float
    cost: float


def evaluate_tour(problem: RoutingProblem, tour: Sequence[int]) -> TourEvaluation:
    """Validate and freshly evaluate a complete tour; suitable for future 2-opt."""
    route = tuple(tour)
    size = len(problem.cities)
    if (len(route) != size + 1
            or any(type(index) is not int or not 0 <= index < size for index in route)
            or route[0] != problem.depot or route[-1] != problem.depot
            or set(route[:-1]) != set(range(size))):
        raise ValueError("tour must start/end at the depot and visit every other city exactly once")
    visits = [Visit(problem.cities[problem.depot], problem.departure_minutes, 0.0, None)]
    distance = risk = 0.0
    for step, (first, second) in enumerate(zip(route, route[1:]), start=1):
        leg = problem.distances_km[first][second]
        distance += leg
        arrival = _arrival_minutes(problem, distance)
        arrival_risk = None if step == size else _arrival_risk(problem.cities[second], arrival)
        if arrival_risk is not None:
            risk += arrival_risk
        visits.append(Visit(problem.cities[second], arrival, leg, arrival_risk))
    return TourEvaluation(
        tour=route, visits=tuple(visits), total_distance_km=distance, total_risk=risk,
        distance_scaled=distance / problem.distance_divisor_km,
        risk_scaled=risk / problem.risk_divisor, cost=problem.cost(distance, risk),
    )


@dataclass(frozen=True, slots=True)
class _State:
    current: int
    visited: int  # Bit i records whether city index i has been visited.
    distance_km: float
    risk: float
    parent: _State | None


@dataclass(frozen=True, slots=True)
class BeamSearchResult:
    evaluation: TourEvaluation
    beam_width: int
    expanded_states: int
    generated_states: int
    peak_beam_size: int
    runtime_seconds: float  # Search + final evaluation, excluding CSV/matrix setup.


def beam_search(problem: RoutingProblem, beam_width: int = 100) -> BeamSearchResult:
    """Keep the globally best W partial tours at each depth.

    Rank prefixes by the weighted cost accumulated so far, using the complete
    instance's scales. At the last depth include the return distance BEFORE
    pruning. This is a heuristic, without an optimality guarantee for finite W.
    States with the same visited set/current city are deliberately not merged:
    different distances imply different arrival times and future risks.
    """
    if type(beam_width) is not int or beam_width < 1:
        raise ValueError("beam_width must be a positive integer")
    started = time.perf_counter()
    size = len(problem.cities)
    beam = [_State(problem.depot, 1 << problem.depot, 0.0, 0.0, None)]
    serial = itertools.count()
    expanded = generated = 0
    peak = 1

    def candidates(frontier: list[_State], close_tour: bool) -> Iterator[tuple[float, int, _State]]:
        nonlocal generated
        for state in frontier:
            for following in range(size):  # Cities have a stable GeoNameID order.
                if state.visited & (1 << following):
                    continue
                distance = state.distance_km + problem.distances_km[state.current][following]
                risk = state.risk + _arrival_risk(
                    problem.cities[following], _arrival_minutes(problem, distance),
                )
                child = _State(following, state.visited | (1 << following), distance, risk, state)
                ranked_distance = distance
                if close_tour:
                    ranked_distance += problem.distances_km[following][problem.depot]
                generated += 1
                # The serial gives deterministic ties without comparing state objects.
                yield problem.cost(ranked_distance, risk), next(serial), child

    for depth in range(1, size):
        expanded += len(beam)
        # The iterator avoids storing every candidate in a separate list.
        kept = heapq.nsmallest(beam_width, candidates(beam, close_tour=depth == size - 1))
        beam = [entry[2] for entry in kept]
        peak = max(peak, len(beam))

    route: list[int] = []
    node: _State | None = beam[0]  # Final beam is ordered by complete-tour cost.
    while node is not None:
        route.append(node.current)
        node = node.parent
    route.reverse()
    route.append(problem.depot)
    evaluation = evaluate_tour(problem, route)
    return BeamSearchResult(
        evaluation=evaluation, beam_width=beam_width, expanded_states=expanded,
        generated_states=generated, peak_beam_size=peak,
        runtime_seconds=time.perf_counter() - started,
    )


def resolve_city(cities: Sequence[City], reference: str) -> City:
    matches = [city for city in cities
               if str(city.geonameid) == reference.strip() or city.name.casefold() == reference.strip().casefold()]
    if len(matches) != 1:
        raise ValueError(f"city {reference!r} is unknown or ambiguous; use a name or GeoNameID from the CSV")
    return matches[0]


def select_cities(cities: Sequence[City], depot: City, references: Sequence[str] | None) -> tuple[City, ...]:
    """Select stops without altering the master data; always include the depot."""
    if references is None:
        return tuple(cities)
    selected = [resolve_city(cities, reference) for reference in references]
    if len({city.geonameid for city in selected}) != len(selected):
        raise ValueError("--cities contains duplicate locations")
    if all(city.geonameid != depot.geonameid for city in selected):
        selected.append(depot)
    return tuple(selected)


def parse_departure(value: str) -> float:
    try:
        hours, minutes = value.split(":")
        if len(hours) != 2 or len(minutes) != 2 or not hours.isdecimal() or not minutes.isdecimal():
            raise ValueError
        hour, minute = int(hours), int(minutes)
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            raise ValueError
    except ValueError as exc:
        raise argparse.ArgumentTypeError("departure must be a 24-hour local time, HH:MM") from exc
    return float(60 * hour + minute)


def format_arrival(minutes: float) -> str:
    # Truncate rather than round a pre-boundary arrival into the next period.
    seconds = math.floor(minutes * 60)
    day, seconds = divmod(seconds, 24 * 60 * 60)
    hour, seconds = divmod(seconds, 60 * 60)
    minute, second = divmod(seconds, 60)
    return f"D+{day} {hour:02d}:{minute:02d}:{second:02d}"


def result_as_dict(problem: RoutingProblem, result: BeamSearchResult) -> dict:
    """Export the instance, objective, route and search statistics for experiments."""
    evaluation = result.evaluation
    return {
        "algorithm": "Safety-Aware Beam Search", "implementation_version": IMPLEMENTATION_VERSION,
        "instance": {
            "selected_geonameids": [city.geonameid for city in problem.cities],
            "depot_geonameid": problem.cities[problem.depot].geonameid,
            "departure_minutes": problem.departure_minutes, "timezone": "Asia/Kuala_Lumpur",
            "speed_kmh": SPEED_KMH, "service_minutes": 0, "waiting_allowed": False,
            "day_window": "07:00 <= local time < 19:00", "depot_return_risk_charged": False,
            "distance_model": "Haversine", "earth_radius_km": EARTH_RADIUS_KM,
        },
        "objective": {
            "alpha": problem.alpha,
            "normalisation": "distance / (n * max_pairwise_distance); risk / (100 * (n - 1))",
            "distance_divisor_km": problem.distance_divisor_km,
            "risk_divisor": problem.risk_divisor,
            "total_distance_km": evaluation.total_distance_km, "total_risk": evaluation.total_risk,
            "distance_scaled": evaluation.distance_scaled, "risk_scaled": evaluation.risk_scaled,
            "cost": evaluation.cost,
        },
        "search": {
            "beam_width": result.beam_width, "expanded_states": result.expanded_states,
            "generated_states": result.generated_states, "peak_beam_size": result.peak_beam_size,
            "runtime_seconds": result.runtime_seconds,
            "ranking": "accumulated weighted cost; return distance included at final depth",
            "tie_breaking": "generation order, expanding cities in ascending GeoNameID order",
        },
        "route": [
            {"geonameid": visit.city.geonameid, "name": visit.city.name,
             "arrival_minutes": visit.arrival_minutes, "arrival_local": format_arrival(visit.arrival_minutes),
             "period": "day" if is_day(visit.arrival_minutes) else "night",
             "leg_distance_km": visit.leg_distance_km, "arrival_risk": visit.arrival_risk}
            for visit in evaluation.visits
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="master CSV (default: bundled cleaned data)")
    parser.add_argument("--depot", default="1735161", help="depot name or GeoNameID (default: Kuala Lumpur)")
    parser.add_argument("--cities", nargs="+", help="selected city names/IDs; depot is included automatically (default: all)")
    parser.add_argument("--departure", type=parse_departure, default=8 * 60.0, help="local HH:MM (default: 08:00)")
    parser.add_argument("--alpha", type=float, default=0.5, help="distance weight in [0, 1] (default: 0.5)")
    parser.add_argument("--beam-width", type=int, default=100, help="positive number of retained states (default: 100)")
    parser.add_argument("--output", type=Path, help="also save route and reproducibility metadata as JSON")
    args = parser.parse_args(argv)
    try:
        cities = load_cities(args.data)
        depot = resolve_city(cities, args.depot)
        problem = make_problem(select_cities(cities, depot, args.cities), depot.geonameid, args.departure, args.alpha)
        result = beam_search(problem, args.beam_width)
        if args.output is not None:
            payload = result_as_dict(problem, result)
            payload["dataset"] = {
                "path": str(args.data.resolve()),
                "sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
            }
            args.output.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (ValueError, OSError, csv.Error) as exc:
        parser.error(str(exc))

    evaluation = result.evaluation
    print(f"Safety-Aware Beam Search | cities={len(problem.cities)} | beam width={result.beam_width}")
    print(f"Depot: {depot.name} ({depot.geonameid}) | departure: {format_arrival(problem.departure_minutes)}")
    print(f"Cost = {problem.alpha:g} * distance_scaled + {1 - problem.alpha:g} * risk_scaled")
    print(f"Distance: {evaluation.total_distance_km:.3f} km | scaled: {evaluation.distance_scaled:.6f}")
    print(f"Arrival risk: {evaluation.total_risk:.2f} | scaled: {evaluation.risk_scaled:.6f}")
    print(f"Combined cost: {evaluation.cost:.6f}")
    print(f"Scaling divisors: distance={problem.distance_divisor_km:.6f} km; risk={problem.risk_divisor:g}")
    print(f"Search: {result.expanded_states} expanded, {result.generated_states} generated, {result.runtime_seconds:.6f} s")
    print(f"\n{'Stop':>4}  {'City (GeoNameID)':<36} {'Local arrival':<16} {'Period':<5} {'Leg km':>10} {'Risk':>8}")
    for index, visit in enumerate(evaluation.visits):
        label = f"{visit.city.name} ({visit.city.geonameid})"
        risk = "-" if visit.arrival_risk is None else f"{visit.arrival_risk:.2f}"
        period = "day" if is_day(visit.arrival_minutes) else "night"
        print(f"{index:>4}  {label:<36} {format_arrival(visit.arrival_minutes):<16} {period:<5} {visit.leg_distance_km:>10.3f} {risk:>8}")
    if args.output is not None:
        print(f"\nSaved JSON: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
