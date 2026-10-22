"""Reference data for supported airports/cities. Extend this table to add destinations."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float
    hotel_base: float  # typical nightly rate in USD
    ground_cost: float  # typical airport transfers + local transport per stay


CITIES: dict[str, City] = {
    "NYC": City("New York", 40.64, -73.78, 265, 55),
    "BOS": City("Boston", 42.36, -71.01, 240, 40),
    "CHI": City("Chicago", 41.98, -87.90, 195, 45),
    "ATL": City("Atlanta", 33.64, -84.43, 170, 40),
    "DFW": City("Dallas", 32.90, -97.04, 165, 45),
    "DEN": City("Denver", 39.86, -104.67, 185, 50),
    "SEA": City("Seattle", 47.45, -122.31, 230, 50),
    "SFO": City("San Francisco", 37.62, -122.38, 285, 60),
}

# Amadeus airport codes (flights) and city codes (hotels) for each internal code.
AIRPORT = {"NYC": "JFK", "BOS": "BOS", "CHI": "ORD", "ATL": "ATL", "DFW": "DFW", "DEN": "DEN", "SEA": "SEA", "SFO": "SFO"}
CITY_CODE = {"NYC": "NYC", "BOS": "BOS", "CHI": "CHI", "ATL": "ATL", "DFW": "DFW", "DEN": "DEN", "SEA": "SEA", "SFO": "SFO"}


def distance_km(a: str, b: str) -> float:
    """Great-circle distance between two supported cities."""
    A, B = CITIES[a], CITIES[b]
    r = math.pi / 180
    dlat, dlon = (B.lat - A.lat) * r, (B.lon - A.lon) * r
    h = math.sin(dlat / 2) ** 2 + math.cos(A.lat * r) * math.cos(B.lat * r) * math.sin(dlon / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))
