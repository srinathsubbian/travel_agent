"""Conversational planning agent: Claude turns a natural-language request into a structured trip,
calls the deterministic optimizer as a tool, and answers using only the tool's results."""
from __future__ import annotations

import json
from datetime import date

from pydantic import ValidationError

from .cities import CITIES
from .config import Settings
from .llm import generate_text, key_hint, llm_enabled, openai_client, token_arg
from .models import OptimizeResult, TripRequest
from .service import run_optimize

MAX_TURNS = 5

TOOLS = [
    {
        "name": "optimize_trip",
        "description": (
            "Find the best visiting order for a multi-city business trip. Prices every ordering and returns the "
            "best options, savings versus the traveler's own order, policy violations and an explanation. "
            f"Supported city codes: {', '.join(f'{k} ({v.name})' for k, v in CITIES.items())}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {"type": "string", "description": "Home city code"},
                "stops": {"type": "array", "items": {"type": "string"}, "description": "City codes to visit, in the order the traveler mentioned them"},
                "start_date": {"type": "string", "description": "YYYY-MM-DD departure date"},
                "nights_per_stop": {"type": "integer", "minimum": 1, "maximum": 7},
                "hotel_cap": {"type": "number", "description": "Max nightly hotel rate in USD"},
                "preferred_airline": {"type": "string"},
                "avoid_airlines": {"type": "array", "items": {"type": "string"}},
                "earliest_departure_hour": {"type": "integer", "minimum": 0, "maximum": 23},
                "priority": {"type": "string", "enum": ["cost", "balanced", "fast"]},
            },
            "required": ["origin", "stops", "start_date"],
        },
    }
]


def _system_prompt() -> str:
    return (
        "You are a business travel planning assistant. Turn the traveler's request into a call to optimize_trip, "
        "then summarize the result. Ask one short question if the origin, cities or start date are missing; "
        "otherwise use sensible defaults and say which you assumed. Only quote numbers returned by the tool. "
        "Never invent fares, flights or hotels. Keep replies under 150 words, plain text. "
        f"Today's date is {date.today().isoformat()}."
    )


def summarize(res: OptimizeResult) -> dict:
    def brief(it):
        return {"order": it.order, "total_cost": round(it.total_cost), "flight_hours": round(it.total_minutes / 60, 1),
                "policy_violations": it.violations}

    return {"data_source": res.data_source, "original_order": brief(res.baseline), "best_option": brief(res.options[0]),
            "alternatives": [brief(o) for o in res.options[1:]],
            "savings": {"dollars": round(res.savings.cost), "minutes": res.savings.minutes, "percent": res.savings.pct},
            "explanation": res.explanation}


OPENAI_TOOLS = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in TOOLS]


def _execute(args: dict, settings: Settings) -> tuple[str, OptimizeResult | None, bool]:
    """Run the optimizer tool. Returns (tool output text, result, is_error). Errors go back to the model."""
    try:
        res = run_optimize(TripRequest(**args), settings)
        return json.dumps(summarize(res)), res, False
    except (ValidationError, LookupError, TypeError) as exc:
        return str(exc)[:800], None, True


def run_agent(message: str, settings: Settings) -> dict:
    """Returns {"reply": str, "result": OptimizeResult | None}."""
    if not llm_enabled(settings):
        return {"reply": f"The planning agent needs {key_hint(settings)}. The /optimize endpoint works without it.", "result": None}
    if settings.llm_provider != "openai":
        return _run_anthropic(message, settings)
    if settings.llm_tools == "off":
        return _run_json_agent(message, settings)
    try:
        return _run_openai(message, settings)
    except Exception:
        if settings.llm_tools == "on":
            raise
        return _run_json_agent(message, settings)  # endpoint probably lacks tool calling


def _run_openai(message: str, settings: Settings) -> dict:
    client = openai_client(settings)
    messages: list[dict] = [{"role": "system", "content": _system_prompt()}, {"role": "user", "content": message}]
    result = None
    for _ in range(MAX_TURNS):
        resp = client.chat.completions.create(model=settings.openai_model, messages=messages, tools=OPENAI_TOOLS,
                                              **token_arg(settings, 800))
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return {"reply": (msg.content or "").strip(), "result": result}
        messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
            {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            text, res, _err = _execute(args, settings)
            result = res or result
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
    return {"reply": "I could not finish planning that trip. Please check the cities and dates and try again.", "result": result}


def _run_anthropic(message: str, settings: Settings) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    messages: list[dict] = [{"role": "user", "content": message}]
    result = None
    for _ in range(MAX_TURNS):
        resp = client.messages.create(model=settings.model, max_tokens=800, system=_system_prompt(), tools=TOOLS, messages=messages)
        if resp.stop_reason != "tool_use":
            return {"reply": "".join(b.text for b in resp.content if b.type == "text").strip(), "result": result}
        messages.append({"role": "assistant", "content": resp.content})
        outputs = []
        for block in resp.content:
            if block.type != "tool_use":
                continue
            text, res, err = _execute(block.input, settings)
            result = res or result
            out = {"type": "tool_result", "tool_use_id": block.id, "content": text}
            if err:
                out["is_error"] = True
            outputs.append(out)
        messages.append({"role": "user", "content": outputs})
    return {"reply": "I could not finish planning that trip. Please check the cities and dates and try again.", "result": result}


EXTRACT_SYSTEM = (
    "You extract business trip parameters. Reply with ONLY one JSON object, no prose, no code fences. "
    "If origin, cities or start date are missing, reply {\"question\": \"<one short question>\"}. Otherwise reply with keys: "
    "origin (city code), stops (list of city codes in the order mentioned), start_date (YYYY-MM-DD), and optionally "
    "nights_per_stop (1-7), hotel_cap (USD), preferred_airline, avoid_airlines (list), earliest_departure_hour (0-23), "
    "priority (cost|balanced|fast). Supported city codes: "
    + ", ".join(f"{k}={v.name}" for k, v in CITIES.items())
    + f". Today's date is {date.today().isoformat()}."
)


def _parse_json(text: str) -> dict:
    text = text.strip().strip("`")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in model reply")
    return json.loads(text[start : end + 1])


def _run_json_agent(message: str, settings: Settings) -> dict:
    """For models without tool calling: the model extracts JSON, we run the optimizer, the model summarizes."""
    try:
        args = _parse_json(generate_text(settings, EXTRACT_SYSTEM, message, max_tokens=300))
    except (ValueError, json.JSONDecodeError):
        return {"reply": "I could not understand that trip request. Please name your home city, the cities to visit and a start date.", "result": None}
    if "question" in args:
        return {"reply": str(args["question"]), "result": None}
    text, res, err = _execute(args, settings)
    if err:
        return {"reply": f"I could not plan that trip: {text}", "result": None}
    try:
        reply = generate_text(
            settings, "Summarize this trip plan for the traveler in under 120 words, plain text. Use only numbers in the JSON.",
            text, max_tokens=300)
    except Exception:
        reply = res.explanation
    return {"reply": reply or res.explanation, "result": res}
