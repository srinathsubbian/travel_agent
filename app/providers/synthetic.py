"""Deterministic synthetic fares and hotel rates for tests, demos and API fallback."""
from __future__ import annotations

from datetime import date

from ..cities import CITIES, distance_km
from ..models import FlightOption, HotelOption
from .base import DataProvider

# (name, price factor, duration factor)
AIRLINES = [("Meridian Air", 1.00, 1.00), ("Northline", 0.88, 1.10), ("Skybridge", 1.12, 0.94)]


def _h(text: str) -> float:
    """Stable hash to [0, 1). Same inputs always give the same fares."""
    x = 2166136261
    for ch in text:
        x ^= ord(ch)
        x = (x * 16777619) & 0xFFFFFFFF
    return (x % 1000) / 1000


class SyntheticProvider(DataProvider):
    name = "synthetic"

    def search_flights(self, origin: str, dest: str, day: date) -> list[FlightOption]:
        d = distance_km(origin, dest)
        base = 70 + 0.105 * d
        day_factor = 0.85 + 0.4 * _h(f"{origin}{dest}{day}")
        hours = d / 830 + 1.1
        out = []
        for airline, pf, tf in AIRLINES:
            price = round(base * day_factor * pf * (0.97 + 0.06 * _h(airline + origin + dest)))
            depart = (6 + int(_h(airline + dest + str(day)) * 12)) * 60 + int(_h(origin + airline + str(day)) * 4) * 15
            out.append(
                FlightOption(
                    from_code=origin, to_code=dest, day=day, airline=airline, price=float(price),
                    duration_min=round(hours * tf * 60), depart_min=depart, km=round(d),
                )
            )
        return out

    def search_hotel(self, city: str, check_in: date, nights: int) -> HotelOption:
        c = CITIES[city]
        rate = round(c.hotel_base * (0.9 + 0.25 * _h(f"{city}{check_in}")))
        return HotelOption(city=city, name=f"{c.name} Business Hotel", nightly_rate=float(rate))
