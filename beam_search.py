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
REST_POLICY = (
    "rest until 07:00 before departing at night or on a leg that would still be underway "
    "at the next 07:00; optional rest until 07:00 by day before any leg except the return"
)
IMPLEMENTATION_VERSION = "2"
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
    alpha: float  # Distance weight.
    beta: float  # Elapsed-time weight; risk receives the remaining weight.
    distances_km: tuple[tuple[float, ...], ...]
    distance_divisor_km: float
    risk_divisor: float
    time_divisor_minutes: float

    @property
    def risk_weight(self) -> float:
        return max(0.0, 1 - self.alpha - self.beta)

    def cost(self, distance_km: float, risk: float, elapsed_minutes: float) -> float:
        return (self.alpha * distance_km / self.distance_divisor_km
                + self.beta * elapsed_minutes / self.time_divisor_minutes
                + self.risk_weight * risk / self.risk_divisor)


def instance_scales(size: int, longest_edge_km: float) -> tuple[float, float, float]:
    """Fixed distance, risk and time divisors that bound complete tours by 1."""
    # Each of the n legs drives at most d_max after a rest shorter than a day.
    time_divisor = size * (_drive_minutes(longest_edge_km) + MINUTES_PER_DAY)
    distance_divisor = size * longest_edge_km if longest_edge_km > 0 else 1.0
    return distance_divisor, 100.0 * (size - 1), time_divisor


def make_problem(
    cities: Sequence[City], depot_id: int, departure_minutes: float = 8 * 60,
    alpha: float = 0.4, beta: float = 0.2,
) -> RoutingProblem:
    """Build one instance and its fixed scales, reusable across algorithms."""
    if not math.isfinite(alpha) or not 0 <= alpha <= 1:
        raise ValueError("alpha must be finite and in [0, 1]")
    if not math.isfinite(beta) or beta < 0 or alpha + beta > 1 + 1e-12:
        raise ValueError("beta must be finite and non-negative, with alpha + beta <= 1")
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
    distance_divisor, risk_divisor, time_divisor = instance_scales(
        size, max(max(row) for row in distances))
    return RoutingProblem(
        cities=ordered, depot=ids.index(depot_id), departure_minutes=departure_minutes,
        alpha=alpha, beta=beta, distances_km=tuple(tuple(row) for row in distances),
        distance_divisor_km=distance_divisor, risk_divisor=risk_divisor,
        time_divisor_minutes=time_divisor,
    )


def is_day(arrival_minutes: float) -> bool:
    local_minutes = arrival_minutes % MINUTES_PER_DAY
    return DAY_START_MINUTES <= local_minutes < DAY_END_MINUTES


def _drive_minutes(distance_km: float) -> float:
    return distance_km / SPEED_KMH * 60


def _wait_until_morning(clock_minutes: float) -> float:
    """Minutes until the next 07:00; zero exactly at 07:00."""
    return (DAY_START_MINUTES - clock_minutes) % MINUTES_PER_DAY


def _departure_waits(
    clock_minutes: float, leg_minutes: float, rest_allowed: bool,
) -> tuple[float, ...]:
    """Waits available before the next leg, preferred option first.

    Nobody departs at night or drives through a whole night: such a leg first
    rests until 07:00, from when any leg may start. Otherwise the driver leaves
    at once or, when allowed, rests overnight until 07:00.
    """
    wait = _wait_until_morning(clock_minutes)
    if not is_day(clock_minutes) or 0 < wait <= leg_minutes:
        return (wait,)
    return (0.0, wait) if rest_allowed and wait > 0 else (0.0,)


def _arrival_risk(city: City, arrival_minutes: float) -> float:
    return city.day_risk if is_day(arrival_minutes) else city.night_risk


@dataclass(frozen=True, slots=True)
class Visit:
    city: City
    arrival_minutes: float  # Includes whole days after departure.
    leg_distance_km: float
    arrival_risk: float | None  # None at the initial and final depot.
    wait_minutes: float  # Rest before the next leg; 0 at the final depot.
    rest: str | None  # Mandatory "night"/"long leg", optional "chosen", or None.


@dataclass(frozen=True, slots=True)
class TourEvaluation:
    tour: tuple[int, ...]  # City indices, including depot at both ends.
    visits: tuple[Visit, ...]
    rest_stops: tuple[int, ...]  # Tour positions where the driver rests, of either kind.
    total_distance_km: float
    total_risk: float
    total_time_minutes: float  # Departure to final depot arrival, including rests.
    total_wait_minutes: float
    distance_scaled: float
    risk_scaled: float
    time_scaled: float
    cost: float


def _validated_route(problem: RoutingProblem, tour: Sequence[int]) -> tuple[int, ...]:
    route = tuple(tour)
    size = len(problem.cities)
    if (len(route) != size + 1
            or any(type(index) is not int or not 0 <= index < size for index in route)
            or route[0] != problem.depot or route[-1] != problem.depot
            or set(route[:-1]) != set(range(size))):
        raise ValueError("tour must start/end at the depot and visit every other city exactly once")
    return route


def schedule_tour(
    problem: RoutingProblem, tour: Sequence[int], rest_stops: Sequence[int] = (),
) -> TourEvaluation:
    """Evaluate a tour with overnight rests at the given tour positions.

    Mandatory rests (at night, or before a leg that would run through a
    night) happen whether listed or not. An optional rest may be listed at any
    position except the last stop before the return.
    Local time is tracked as the segment start (departure, or 07:00 after a
    rest) plus minutes driven since, exactly as in Beam Search, so both
    classify boundary arrivals identically.
    """
    route = _validated_route(problem, tour)
    size = len(problem.cities)
    chosen = set(rest_stops)
    if any(type(position) is not int or not 0 <= position < size for position in chosen):
        raise ValueError("rest stops must be tour positions before the return leg")
    segment_start = segment_base = problem.departure_minutes  # Local and absolute start.
    driven = distance = risk = waited = 0.0
    visits: list[Visit] = []
    rests: list[int] = []
    for position, city_index in enumerate(route):
        leg = arrival_risk = None
        if position:
            leg = problem.distances_km[route[position - 1]][city_index]
            distance += leg
            driven += _drive_minutes(leg)
            if position < size:
                arrival_risk = _arrival_risk(problem.cities[city_index], segment_start + driven)
                risk += arrival_risk
        arrival = segment_base + driven
        if position == size:
            visits.append(Visit(problem.cities[city_index], arrival, leg, None, 0.0, None))
            break
        clock = segment_start + driven
        next_leg = _drive_minutes(problem.distances_km[city_index][route[position + 1]])
        waits = _departure_waits(clock, next_leg, position < size - 1)
        if position == size - 1 and position in chosen and waits[0] == 0:
            raise ValueError("an optional rest is not allowed before the return leg")
        wait = waits[-1] if len(waits) == 1 or position in chosen else 0.0
        rest = None
        if wait > 0:
            rest = "chosen" if len(waits) == 2 else "night" if not is_day(clock) else "long leg"
            rests.append(position)
            # Snap to the exact 07:00 instant so long tours accumulate no drift.
            segment_base = DAY_START_MINUTES + MINUTES_PER_DAY * round(
                (arrival + wait - DAY_START_MINUTES) / MINUTES_PER_DAY)
            wait = segment_base - arrival
            waited += wait
            segment_start, driven = float(DAY_START_MINUTES), 0.0
        visits.append(Visit(problem.cities[city_index], arrival, leg or 0.0, arrival_risk, wait, rest))
    elapsed = visits[-1].arrival_minutes - problem.departure_minutes
    return TourEvaluation(
        tour=route, visits=tuple(visits), rest_stops=tuple(rests),
        total_distance_km=distance, total_risk=risk, total_time_minutes=elapsed,
        total_wait_minutes=waited, distance_scaled=distance / problem.distance_divisor_km,
        risk_scaled=risk / problem.risk_divisor,
        time_scaled=elapsed / problem.time_divisor_minutes,
        cost=problem.cost(distance, risk, elapsed),
    )


def _best_rest_stops(problem: RoutingProblem, route: tuple[int, ...]) -> tuple[int, ...]:
    """Choose the cheapest overnight rests for a fixed tour in O(n^2) time.

    Every rest ends at 07:00, so the best continuation after resting at a
    position is independent of the day and is computed once (dynamic
    programming from the end of the tour). Ties prefer driving on.
    """
    size = len(problem.cities)
    time_weight = problem.beta / problem.time_divisor_minutes
    risk_weight = problem.risk_weight / problem.risk_divisor
    after_rest = [0.0] * size  # Best cost leaving route[k] at 07:00.
    next_rest: list[int | None] = [None] * size

    def drive(start: int, segment_start: float) -> tuple[float, int | None]:
        """Cheapest remaining cost and first rest when leaving route[start] now."""
        best_cost, best_rest = math.inf, None
        driven = risk = 0.0
        for position in range(start + 1, size + 1):
            driven += _drive_minutes(problem.distances_km[route[position - 1]][route[position]])
            clock = segment_start + driven
            if position == size:
                cost = risk_weight * risk + time_weight * driven
                if cost <= best_cost:
                    best_cost, best_rest = cost, None
                break
            risk += _arrival_risk(problem.cities[route[position]], clock)
            next_leg = _drive_minutes(problem.distances_km[route[position]][route[position + 1]])
            waits = _departure_waits(clock, next_leg, position < size - 1)
            if waits[-1] > 0:
                cost = (risk_weight * risk + time_weight * (driven + waits[-1])
                        + after_rest[position])
                if cost <= best_cost:
                    best_cost, best_rest = cost, position
            if waits[0] > 0:  # The rest is mandatory.
                break
        return best_cost, best_rest

    for position in range(size - 1, -1, -1):
        after_rest[position], next_rest[position] = drive(position, DAY_START_MINUTES)
    first_leg = _drive_minutes(problem.distances_km[route[0]][route[1]])
    waits = _departure_waits(problem.departure_minutes, first_leg, rest_allowed=True)
    rest: int | None = None
    if waits[-1] > 0:
        best_cost, rest = time_weight * waits[-1] + after_rest[0], 0
    if waits[0] == 0:
        cost, first = drive(0, problem.departure_minutes)
        if waits[-1] == 0 or cost <= best_cost:
            rest = first
    rests: list[int] = []
    while rest is not None:
        rests.append(rest)
        rest = next_rest[rest]
    return tuple(rests)


def evaluate_tour(problem: RoutingProblem, tour: Sequence[int]) -> TourEvaluation:
    """Validate a complete tour and evaluate it with its cheapest rest schedule.

    Suitable for 2-opt: the result depends only on the tour order.
    """
    route = _validated_route(problem, tour)
    return schedule_tour(problem, route, _best_rest_stops(problem, route))


@dataclass(frozen=True, slots=True)
class _State:
    current: int
    visited: int  # Bit i records whether city index i has been visited.
    distance_km: float
    risk: float
    elapsed_minutes: float  # Since departure, including rests.
    segment_start: float  # Local departure time, or 07:00 after the latest rest.
    driven_minutes: float  # Since segment_start; local clock = start + driven.
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

    Each extension either leaves at once or first rests until 07:00 (mandatory
    at night or before a leg that would run through a night). Prefixes are ranked by the weighted cost accumulated so far, using
    the complete instance's scales; at the last depth the return leg, including
    any night rest before it, is added BEFORE pruning. This is a heuristic,
    without an optimality guarantee for finite W. States with the same visited
    set/current city are deliberately not merged: different clocks imply
    different future risks. The final tour is re-evaluated with its cheapest
    rest schedule.
    """
    if type(beam_width) is not int or beam_width < 1:
        raise ValueError("beam_width must be a positive integer")
    started = time.perf_counter()
    size = len(problem.cities)
    beam = [_State(problem.depot, 1 << problem.depot, 0.0, 0.0, 0.0,
                   problem.departure_minutes, 0.0, None)]
    serial = itertools.count()
    expanded = generated = 0
    peak = 1

    def candidates(frontier: list[_State], close_tour: bool) -> Iterator[tuple[float, float, int, _State]]:
        nonlocal generated
        for state in frontier:
            clock = state.segment_start + state.driven_minutes
            for following in range(size):  # Cities have a stable GeoNameID order.
                if state.visited & (1 << following):
                    continue
                leg = problem.distances_km[state.current][following]
                # Every leg generated here ends at a scored stop, so a rest is allowed.
                for wait in _departure_waits(clock, _drive_minutes(leg), rest_allowed=True):
                    segment_start, driven = ((state.segment_start, state.driven_minutes) if wait == 0
                                             else (float(DAY_START_MINUTES), 0.0))
                    driven += _drive_minutes(leg)
                    arrival = segment_start + driven
                    child = _State(
                        following, state.visited | (1 << following), state.distance_km + leg,
                        state.risk + _arrival_risk(problem.cities[following], arrival),
                        state.elapsed_minutes + wait + _drive_minutes(leg),
                        segment_start, driven, state,
                    )
                    ranked_distance, ranked_elapsed = child.distance_km, child.elapsed_minutes
                    if close_tour:
                        back = problem.distances_km[following][problem.depot]
                        ranked_distance += back
                        back_minutes = _drive_minutes(back)
                        ranked_elapsed += _departure_waits(arrival, back_minutes, False)[0] + back_minutes
                    generated += 1
                    # Equal costs prefer the earlier clock; the serial then gives
                    # deterministic ties without comparing state objects.
                    yield (problem.cost(ranked_distance, child.risk, ranked_elapsed),
                           ranked_elapsed, next(serial), child)

    for depth in range(1, size):
        expanded += len(beam)
        # The iterator avoids storing every candidate in a separate list.
        kept = heapq.nsmallest(beam_width, candidates(beam, close_tour=depth == size - 1))
        beam = [entry[3] for entry in kept]
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


def format_duration(minutes: float) -> str:
    hours, minute = divmod(math.floor(minutes), 60)
    return f"{hours}:{minute:02d}"


def result_as_dict(problem: RoutingProblem, result: BeamSearchResult) -> dict:
    """Export the instance, objective, route and search statistics for experiments."""
    evaluation = result.evaluation
    return {
        "algorithm": "Safety-Aware Beam Search", "implementation_version": IMPLEMENTATION_VERSION,
        "instance": {
            "selected_geonameids": [city.geonameid for city in problem.cities],
            "depot_geonameid": problem.cities[problem.depot].geonameid,
            "departure_minutes": problem.departure_minutes, "timezone": "Asia/Kuala_Lumpur",
            "speed_kmh": SPEED_KMH, "service_minutes": 0, "rest_policy": REST_POLICY,
            "day_window": "07:00 <= local time < 19:00", "depot_return_risk_charged": False,
            "distance_model": "Haversine", "earth_radius_km": EARTH_RADIUS_KM,
        },
        "objective": {
            "alpha": problem.alpha, "beta": problem.beta, "risk_weight": problem.risk_weight,
            "normalisation": ("distance / (n * max_pairwise_distance); risk / (100 * (n - 1)); "
                              "time / (n * (max_leg_minutes + 1440))"),
            "distance_divisor_km": problem.distance_divisor_km,
            "risk_divisor": problem.risk_divisor,
            "time_divisor_minutes": problem.time_divisor_minutes,
            "total_distance_km": evaluation.total_distance_km, "total_risk": evaluation.total_risk,
            "total_time_minutes": evaluation.total_time_minutes,
            "total_wait_minutes": evaluation.total_wait_minutes,
            "distance_scaled": evaluation.distance_scaled, "risk_scaled": evaluation.risk_scaled,
            "time_scaled": evaluation.time_scaled, "cost": evaluation.cost,
        },
        "search": {
            "beam_width": result.beam_width, "expanded_states": result.expanded_states,
            "generated_states": result.generated_states, "peak_beam_size": result.peak_beam_size,
            "runtime_seconds": result.runtime_seconds,
            "ranking": ("accumulated weighted cost; return leg and any night rest before it "
                        "included at final depth; final tour re-evaluated with optimal rests"),
            "tie_breaking": ("earlier elapsed time, then generation order, expanding cities in "
                             "ascending GeoNameID order and leaving now before resting"),
        },
        "route": [
            {"geonameid": visit.city.geonameid, "name": visit.city.name,
             "arrival_minutes": visit.arrival_minutes, "arrival_local": format_arrival(visit.arrival_minutes),
             "period": "day" if is_day(visit.arrival_minutes) else "night",
             "leg_distance_km": visit.leg_distance_km, "arrival_risk": visit.arrival_risk,
             "rest": visit.rest, "wait_minutes": visit.wait_minutes}
            for visit in evaluation.visits
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="master CSV (default: bundled cleaned data)")
    parser.add_argument("--depot", default="1735161", help="depot name or GeoNameID (default: Kuala Lumpur)")
    parser.add_argument("--cities", nargs="+", help="selected city names/IDs; depot is included automatically (default: all)")
    parser.add_argument("--departure", type=parse_departure, default=8 * 60.0, help="local HH:MM (default: 08:00)")
    parser.add_argument("--alpha", type=float, default=0.4, help="distance weight in [0, 1] (default: 0.4)")
    parser.add_argument("--beta", type=float, default=0.2,
                        help="elapsed-time weight; risk gets 1 - alpha - beta (default: 0.2)")
    parser.add_argument("--beam-width", type=int, default=100, help="positive number of retained states (default: 100)")
    parser.add_argument("--output", type=Path, help="also save route and reproducibility metadata as JSON")
    args = parser.parse_args(argv)
    try:
        cities = load_cities(args.data)
        depot = resolve_city(cities, args.depot)
        problem = make_problem(select_cities(cities, depot, args.cities), depot.geonameid, args.departure,
                               args.alpha, args.beta)
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
    print(f"Cost = {problem.alpha:g} * distance_scaled + {problem.beta:g} * time_scaled"
          f" + {problem.risk_weight:g} * risk_scaled")
    print(f"Distance: {evaluation.total_distance_km:.3f} km | scaled: {evaluation.distance_scaled:.6f}")
    print(f"Trip time: {format_duration(evaluation.total_time_minutes)} h, including"
          f" {format_duration(evaluation.total_wait_minutes)} h resting | scaled: {evaluation.time_scaled:.6f}")
    print(f"Arrival risk: {evaluation.total_risk:.2f} | scaled: {evaluation.risk_scaled:.6f}")
    print(f"Combined cost: {evaluation.cost:.6f}")
    print(f"Scaling divisors: distance={problem.distance_divisor_km:.6f} km; risk={problem.risk_divisor:g};"
          f" time={problem.time_divisor_minutes:.3f} min")
    print(f"Search: {result.expanded_states} expanded, {result.generated_states} generated, {result.runtime_seconds:.6f} s")
    print(f"\n{'Stop':>4}  {'City (GeoNameID)':<36} {'Local arrival':<16} {'Period':<5} {'Leg km':>10} {'Risk':>8}"
          f"  Rest before leaving")
    for index, visit in enumerate(evaluation.visits):
        label = f"{visit.city.name} ({visit.city.geonameid})"
        risk = "-" if visit.arrival_risk is None else f"{visit.arrival_risk:.2f}"
        period = "day" if is_day(visit.arrival_minutes) else "night"
        rest = "-" if visit.rest is None else f"{format_duration(visit.wait_minutes)} h ({visit.rest})"
        print(f"{index:>4}  {label:<36} {format_arrival(visit.arrival_minutes):<16} {period:<5}"
              f" {visit.leg_distance_km:>10.3f} {risk:>8}  {rest}")
    if args.output is not None:
        print(f"\nSaved JSON: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
