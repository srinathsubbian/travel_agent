"""Pydantic models shared by the API, optimizer and agent."""
from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from .cities import CITIES


class Priority(str, Enum):
    cost = "cost"
    balanced = "balanced"
    fast = "fast"


class TripRequest(BaseModel):
    origin: str = Field(description="Home city code, e.g. NYC")
    stops: list[str] = Field(min_length=1, max_length=6, description="City codes to visit")
    start_date: date
    nights_per_stop: int = Field(default=2, ge=1, le=7)
    hotel_cap: float = Field(default=250, gt=0, description="Max nightly hotel rate allowed by policy (USD)")
    preferred_airline: str | None = None
    avoid_airlines: list[str] = Field(default_factory=list)
    earliest_departure_hour: int = Field(default=0, ge=0, le=23)
    priority: Priority = Priority.balanced

    @field_validator("origin")
    @classmethod
    def _origin(cls, v: str) -> str:
        v = v.strip().upper()
        if v not in CITIES:
            raise ValueError(f"Unsupported city '{v}'. Supported: {', '.join(sorted(CITIES))}")
        return v

    @field_validator("stops")
    @classmethod
    def _stops(cls, v: list[str]) -> list[str]:
        out = [s.strip().upper() for s in v]
        bad = [s for s in out if s not in CITIES]
        if bad:
            raise ValueError(f"Unsupported cities: {bad}. Supported: {', '.join(sorted(CITIES))}")
        if len(set(out)) != len(out):
            raise ValueError("Stops must be unique")
        return out

    @model_validator(mode="after")
    def _no_origin_in_stops(self) -> "TripRequest":
        if self.origin in self.stops:
            raise ValueError("Origin cannot also be a stop")
        return self


class FlightOption(BaseModel):
    from_code: str
    to_code: str
    day: date
    airline: str
    price: float
    duration_min: int
    depart_min: int  # minutes after local midnight
    km: float


class HotelOption(BaseModel):
    city: str
    name: str
    nightly_rate: float


class Stay(BaseModel):
    city: str
    check_in: date
    nights: int
    hotel: HotelOption
    ground_cost: float
    over_policy: bool
    inbound: FlightOption


class Itinerary(BaseModel):
    order: list[str]
    legs: list[FlightOption]
    stays: list[Stay]
    flights_cost: float
    hotels_cost: float
    ground_cost: float
    total_cost: float
    total_minutes: int
    total_km: float
    violations: int
    score: float = 0.0


class Savings(BaseModel):
    cost: float
    minutes: int
    pct: float


class OptimizeResult(BaseModel):
    baseline: Itinerary
    options: list[Itinerary]
    savings: Savings
    explanation: str
    data_source: str


class RepriceRequest(BaseModel):
    trip: TripRequest
    order: list[str]

    @model_validator(mode="after")
    def _same_cities(self) -> "RepriceRequest":
        if sorted(o.upper() for o in self.order) != sorted(self.trip.stops):
            raise ValueError("order must contain exactly the trip's stops")
        self.order = [o.upper() for o in self.order]
        return self


class FeedbackIn(BaseModel):
    vote: str = Field(pattern="^(up|down)$")
    order: list[str]
    comment: str = ""


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
