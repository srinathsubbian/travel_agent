"""Plain-language explanations. Claude writes the text, but only from numbers the optimizer computed.
If no API key is set, the call fails, or the text contains an amount we did not supply, a template is used."""
from __future__ import annotations

import json
import re
from collections import Counter

from .cities import CITIES
from .config import Settings
from .llm import generate_text, llm_enabled
from .models import Itinerary, TripRequest

SYSTEM = (
    "You explain business-trip itineraries to travelers. You are given JSON facts computed by an optimizer. "
    "Write 3 to 4 short sentences in plain language: why this visiting order was chosen, what it saves versus the "
    "traveler's original order, and any policy problem. Use ONLY numbers present in the JSON; never invent fares, "
    "times, airlines or cities. Write dollar amounts as $1,234. No markdown, no bullet points."
)


def _money(n: float) -> str:
    return f"${abs(round(n)):,}"


def _dur(m: int) -> str:
    m = abs(int(m))
    return f"{m // 60}h {m % 60:02d}m"


def build_facts(req: TripRequest, baseline: Itinerary, best: Itinerary) -> dict:
    names = lambda it: [CITIES[c].name for c in (req.origin, *it.order, req.origin)]  # noqa: E731
    airlines = Counter(l.airline for l in best.legs)
    over = [{"city": CITIES[s.city].name, "rate": round(s.hotel.nightly_rate)} for s in best.stays if s.over_policy]
    return {
        "priority": req.priority.value,
        "original_route": names(baseline),
        "optimized_route": names(best),
        "optimized_km": round(best.total_km),
        "original_km": round(baseline.total_km),
        "cost_saved": round(baseline.total_cost - best.total_cost),  # negative means it costs more
        "optimized_cost": round(best.total_cost),
        "original_cost": round(baseline.total_cost),
        "air_time_saved_minutes": baseline.total_minutes - best.total_minutes,
        "airline_legs": dict(airlines),
        "preferred_airline": req.preferred_airline,
        "hotel_cap": round(req.hotel_cap),
        "stays_over_cap": over,
        "same_order": best.order == baseline.order,
    }


def template_explanation(f: dict) -> str:
    parts = []
    if f["same_order"]:
        parts.append("Your original order is already the strongest option for this priority, so it was kept.")
    else:
        dk = f["original_km"] - f["optimized_km"]
        parts.append(
            f"The route {' to '.join(f['optimized_route'])} flies {abs(dk):,} km {'less' if dk >= 0 else 'more'} "
            "than your original order" + (", which removes backtracking." if dk >= 0 else ", trading distance for better fares and timings.")
        )
    c, m = f["cost_saved"], f["air_time_saved_minutes"]
    parts.append(
        f"That is {'a saving of' if c >= 0 else 'an extra'} {_money(c)} and {_dur(m)} {'less' if m >= 0 else 'more'} "
        f"in the air, with priority set to {f['priority']}."
    )
    if f["stays_over_cap"]:
        bad = ", ".join(f"{s['city']} at {_money(s['rate'])}" for s in f["stays_over_cap"])
        parts.append(f"Over the {_money(f['hotel_cap'])} nightly cap: {bad}. Reordering cannot fix this, so it needs an exception.")
    else:
        parts.append(f"All stays are within the {_money(f['hotel_cap'])} nightly cap.")
    return " ".join(parts)


def _amounts_ok(text: str, facts: dict) -> bool:
    """Every dollar figure in the LLM text must be a number we supplied."""
    allowed = {abs(int(facts[k])) for k in ("cost_saved", "optimized_cost", "original_cost", "hotel_cap")}
    allowed |= {int(s["rate"]) for s in facts["stays_over_cap"]}
    for raw in re.findall(r"\$([\d,]+(?:\.\d+)?)", text):
        if round(float(raw.replace(",", ""))) not in allowed:
            return False
    return True


def explain(req: TripRequest, baseline: Itinerary, best: Itinerary, settings: Settings) -> str:
    facts = build_facts(req, baseline, best)
    fallback = template_explanation(facts)
    if not llm_enabled(settings):
        return fallback
    try:
        text = generate_text(settings, SYSTEM, json.dumps(facts), max_tokens=400)
        return text if text and _amounts_ok(text, facts) else fallback
    except Exception:
        return fallback
