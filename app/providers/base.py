"""Provider interface: anything that can price flights and hotels."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..models import FlightOption, HotelOption


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def search_flights(self, origin: str, dest: str, day: date) -> list[FlightOption]:
        """Return all fare options for one leg on one day (may be empty)."""

    @abstractmethod
    def search_hotel(self, city: str, check_in: date, nights: int) -> HotelOption:
        """Return the best-value hotel for a stay."""


class CachedProvider(DataProvider):
    """Memoizes a provider. Route search re-prices the same (leg, day) many times,
    so this keeps real API calls to a minimum and respects rate limits."""

    def __init__(self, inner: DataProvider):
        self.inner = inner
        self.name = inner.name
        self._flights: dict[tuple, list[FlightOption]] = {}
        self._hotels: dict[tuple, HotelOption] = {}
        self.calls = 0

    def search_flights(self, origin, dest, day):
        key = (origin, dest, day)
        if key not in self._flights:
            self.calls += 1
            self._flights[key] = self.inner.search_flights(origin, dest, day)
        return self._flights[key]

    def search_hotel(self, city, check_in, nights):
        key = (city, check_in, nights)
        if key not in self._hotels:
            self.calls += 1
            self._hotels[key] = self.inner.search_hotel(city, check_in, nights)
        return self._hotels[key]
