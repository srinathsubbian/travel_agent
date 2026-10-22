"""Amadeus Self-Service adapter (flight offers + hotel offers).

Free sandbox keys: https://developers.amadeus.com. NOT exercised by the unit tests (they need
credentials and network); `get_provider` wraps this in a fallback to the synthetic provider
so a failed call never breaks the app.
"""
from __future__ import annotations

import re
import time
from datetime import date, timedelta

import httpx

from ..cities import AIRPORT, CITY_CODE, distance_km
from ..config import Settings
from ..models import FlightOption, HotelOption
from .base import DataProvider


def _iso_duration_minutes(value: str) -> int:
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", value)
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0) if m else 0


class AmadeusProvider(DataProvider):
    name = "amadeus"

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.http = client or httpx.Client(base_url=settings.amadeus_base_url, timeout=20)
        self._token: str | None = None
        self._token_expiry = 0.0

    # -- auth and request helpers -------------------------------------------------
    def _auth(self) -> str:
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        r = self.http.post(
            "/v1/security/oauth2/token",
            data={"grant_type": "client_credentials", "client_id": self.s.amadeus_client_id,
                  "client_secret": self.s.amadeus_client_secret},
        )
        r.raise_for_status()
        body = r.json()
        self._token, self._token_expiry = body["access_token"], time.time() + int(body.get("expires_in", 1500))
        return self._token

    def _get(self, path: str, params: dict, retries: int = 3) -> dict:
        """GET with bearer auth and exponential backoff on 429/5xx (rate limits)."""
        for attempt in range(retries):
            r = self.http.get(path, params=params, headers={"Authorization": f"Bearer {self._auth()}"})
            if r.status_code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("unreachable")

    # -- provider API -------------------------------------------------------------
    def search_flights(self, origin: str, dest: str, day: date) -> list[FlightOption]:
        data = self._get(
            "/v2/shopping/flight-offers",
            {"originLocationCode": AIRPORT[origin], "destinationLocationCode": AIRPORT[dest],
             "departureDate": day.isoformat(), "adults": 1, "currencyCode": "USD", "max": 10},
        )
        best: dict[str, FlightOption] = {}  # cheapest offer per airline
        for offer in data.get("data", []):
            itin = offer["itineraries"][0]
            airline = (offer.get("validatingAirlineCodes") or [itin["segments"][0]["carrierCode"]])[0]
            depart = itin["segments"][0]["departure"]["at"]  # 2026-11-02T08:15:00 (local)
            opt = FlightOption(
                from_code=origin, to_code=dest, day=day, airline=airline,
                price=float(offer["price"]["grandTotal"]), duration_min=_iso_duration_minutes(itin["duration"]),
                depart_min=int(depart[11:13]) * 60 + int(depart[14:16]), km=round(distance_km(origin, dest)),
            )
            if airline not in best or opt.price < best[airline].price:
                best[airline] = opt
        return list(best.values())

    def search_hotel(self, city: str, check_in: date, nights: int) -> HotelOption:
        hotels = self._get("/v1/reference-data/locations/hotels/by-city", {"cityCode": CITY_CODE[city]})
        ids = [h["hotelId"] for h in hotels.get("data", [])[:20]]
        if not ids:
            raise LookupError(f"no hotels found for {city}")
        offers = self._get(
            "/v3/shopping/hotel-offers",
            {"hotelIds": ",".join(ids), "checkInDate": check_in.isoformat(),
             "checkOutDate": (check_in + timedelta(days=nights)).isoformat(), "adults": 1, "currency": "USD"},
        )
        best = None
        for entry in offers.get("data", []):
            for off in entry.get("offers", []):
                total = float(off["price"]["total"])
                if best is None or total < best[0]:
                    best = (total, entry["hotel"].get("name", "Hotel"))
        if best is None:
            raise LookupError(f"no hotel offers for {city}")
        return HotelOption(city=city, name=best[1], nightly_rate=round(best[0] / nights, 2))


class FallbackProvider(DataProvider):
    """Try the primary provider; on any failure use the fallback and remember it happened."""

    def __init__(self, primary: DataProvider, fallback: DataProvider):
        self.primary, self.fallback = primary, fallback
        self.name = primary.name
        self.used_fallback = False

    def search_flights(self, origin, dest, day):
        try:
            options = self.primary.search_flights(origin, dest, day)
            if options:
                return options
        except Exception:
            pass
        self.used_fallback, self.name = True, f"{self.primary.name}+synthetic fallback"
        return self.fallback.search_flights(origin, dest, day)

    def search_hotel(self, city, check_in, nights):
        try:
            return self.primary.search_hotel(city, check_in, nights)
        except Exception:
            self.used_fallback, self.name = True, f"{self.primary.name}+synthetic fallback"
            return self.fallback.search_hotel(city, check_in, nights)
