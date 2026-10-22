"""Deterministic itinerary optimizer. The LLM never picks routes or prices; this module does."""
from __future__ import annotations

from datetime import date, timedelta
from itertools import permutations

from .cities import CITIES, distance_km
from .models import FlightOption, Itinerary, Priority, Savings, Stay, TripRequest
from .providers.base import DataProvider

WEIGHTS = {Priority.cost: (0.8, 0.2), Priority.balanced: (0.5, 0.5), Priority.fast: (0.2, 0.8)}
PREFERRED_BOOST = 0.92  # score multiplier for the preferred airline (lower is better)
POLICY_PENALTY = 0.12  # score added per stay over the hotel cap


def ref_price(km: float) -> float:
    return 70 + 0.105 * km


def ref_minutes(km: float) -> float:
    return (km / 830 + 1.1) * 60


class Planner:
    """Prices candidate visiting orders for one trip request."""

    def __init__(self, provider: DataProvider, req: TripRequest):
        self.p, self.req = provider, req
        self.wc, self.wt = WEIGHTS[req.priority]
        self._baseline: Itinerary | None = None

    # -- single leg ---------------------------------------------------------------
    def pick_leg(self, a: str, b: str, day: date) -> FlightOption:
        r = self.req
        opts = [o for o in self.p.search_flights(a, b, day) if o.airline not in r.avoid_airlines]
        timely = [o for o in opts if o.depart_min >= r.earliest_departure_hour * 60]
        opts = timely or opts  # relax the departure-time filter rather than fail
        if not opts:
            raise LookupError(f"No flights available {a}->{b} on {day}")
        km = distance_km(a, b)

        def leg_score(o: FlightOption) -> float:
            s = self.wc * o.price / ref_price(km) + self.wt * o.duration_min / ref_minutes(km)
            return s * (PREFERRED_BOOST if o.airline == r.preferred_airline else 1.0)

        return min(opts, key=leg_score)

    # -- whole itinerary ----------------------------------------------------------
    def build(self, order: list[str]) -> Itinerary:
        r = self.req
        path = [r.origin, *order, r.origin]
        day, legs, stays = r.start_date, [], []
        for i in range(len(path) - 1):
            leg = self.pick_leg(path[i], path[i + 1], day)
            legs.append(leg)
            if i < len(order):
                city = path[i + 1]
                hotel = self.p.search_hotel(city, day, r.nights_per_stop)
                stays.append(Stay(city=city, check_in=day, nights=r.nights_per_stop, hotel=hotel,
                                  ground_cost=CITIES[city].ground_cost, over_policy=hotel.nightly_rate > r.hotel_cap,
                                  inbound=leg))
                day += timedelta(days=r.nights_per_stop)
        flights = sum(l.price for l in legs)
        hotels = sum(s.hotel.nightly_rate * s.nights for s in stays)
        ground = sum(s.ground_cost for s in stays)
        return Itinerary(
            order=list(order), legs=legs, stays=stays, flights_cost=flights, hotels_cost=hotels, ground_cost=ground,
            total_cost=flights + hotels + ground, total_minutes=sum(l.duration_min for l in legs),
            total_km=sum(l.km for l in legs), violations=sum(s.over_policy for s in stays),
        )

    @property
    def baseline(self) -> Itinerary:
        """The traveler's own order, priced by the same engine (so savings come from routing only)."""
        if self._baseline is None:
            self._baseline = self.build(self.req.stops)
        return self._baseline

    def score(self, it: Itinerary) -> float:
        b = self.baseline
        return self.wc * it.total_cost / b.total_cost + self.wt * it.total_minutes / b.total_minutes + POLICY_PENALTY * it.violations

    def optimize(self, top_k: int = 3) -> list[Itinerary]:
        """Evaluate every visiting order (at most 6! = 720) and return the best `top_k`."""
        candidates = []
        for order in permutations(self.req.stops):
            it = self.build(list(order))
            it.score = self.score(it)
            candidates.append(it)
        candidates.sort(key=lambda i: i.score)
        return candidates[:top_k]


def compute_savings(baseline: Itinerary, best: Itinerary) -> Savings:
    cost = baseline.total_cost - best.total_cost
    return Savings(cost=round(cost, 2), minutes=baseline.total_minutes - best.total_minutes,
                   pct=round(100 * cost / baseline.total_cost, 1) if baseline.total_cost else 0.0)
