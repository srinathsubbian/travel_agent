"""Calendar (.ics) and booking-request exports."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .cities import CITIES
from .models import Itinerary, TripRequest


def _fmt(day, minute: int) -> str:
    dt = datetime(day.year, day.month, day.day) + timedelta(minutes=minute)
    return dt.strftime("%Y%m%dT%H%M%S")


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def to_ics(it: Itinerary) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Itinerary Optimizer//EN"]
    for i, leg in enumerate(it.legs):
        lines += [
            "BEGIN:VEVENT", f"UID:leg{i}-{leg.day}@itinerary-optimizer", f"DTSTAMP:{stamp}",
            f"DTSTART:{_fmt(leg.day, leg.depart_min)}", f"DTEND:{_fmt(leg.day, leg.depart_min + leg.duration_min)}",
            f"SUMMARY:{_esc(f'Flight {CITIES[leg.from_code].name} to {CITIES[leg.to_code].name} ({leg.airline})')}",
            f"DESCRIPTION:{_esc(f'Fare ${leg.price:,.0f}. Times are approximate local times.')}", "END:VEVENT",
        ]
    for i, s in enumerate(it.stays):
        end = s.check_in + timedelta(days=s.nights)
        lines += [
            "BEGIN:VEVENT", f"UID:stay{i}-{s.check_in}@itinerary-optimizer", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{s.check_in:%Y%m%d}", f"DTEND;VALUE=DATE:{end:%Y%m%d}",
            f"SUMMARY:{_esc('Hotel: ' + s.hotel.name)}",
            f"DESCRIPTION:{_esc(f'{s.nights} nights at ${s.hotel.nightly_rate:,.0f} per night')}", "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def to_booking_request(req: TripRequest, it: Itinerary) -> dict:
    """Payload for a booking or approval system. Replace the traveler placeholder with your user id."""
    return {
        "traveler": "demo-traveler",
        "policy": {"hotel_cap_per_night": req.hotel_cap, "violations": it.violations},
        "flights": [{"from": l.from_code, "to": l.to_code, "date": l.day.isoformat(), "airline": l.airline,
                     "fare": l.price, "duration_min": l.duration_min} for l in it.legs],
        "hotels": [{"city": s.city, "name": s.hotel.name, "check_in": s.check_in.isoformat(), "nights": s.nights,
                    "nightly_rate": s.hotel.nightly_rate, "over_policy": s.over_policy} for s in it.stays],
        "estimated_total": round(it.total_cost, 2),
        "status": "pending_approval" if it.violations else "ready_to_book",
    }
