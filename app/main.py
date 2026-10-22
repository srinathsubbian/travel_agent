"""FastAPI app. Run with: uvicorn app.main:app --reload"""
from __future__ import annotations

import json
import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from .agent import run_agent
from .calendar_export import to_booking_request, to_ics
from .cities import CITIES
from .config import get_settings
from .llm import llm_enabled
from .models import ChatIn, FeedbackIn, Itinerary, OptimizeResult, RepriceRequest, TripRequest
from .service import run_optimize, run_reprice

app = FastAPI(title="Business Trip Itinerary Optimizer", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _guard(fn, *args):
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/health")
def health():
    s = get_settings()
    return {"status": "ok", "data_provider": s.data_provider, "llm_provider": s.llm_provider, "llm_enabled": llm_enabled(s)}


@app.get("/cities")
def cities():
    return {code: c.name for code, c in CITIES.items()}


@app.post("/optimize", response_model=OptimizeResult)
def optimize(req: TripRequest):
    """Rank the best visiting orders and compare against the traveler's own order."""
    return _guard(run_optimize, req, get_settings())


@app.post("/reprice", response_model=Itinerary)
def reprice(body: RepriceRequest):
    """Live repricing after the user drags stops into a new order."""
    return _guard(run_reprice, body, get_settings())


@app.post("/export/ics", response_class=PlainTextResponse)
def export_ics(body: RepriceRequest):
    it = _guard(run_reprice, body, get_settings())
    return PlainTextResponse(to_ics(it), media_type="text/calendar",
                             headers={"Content-Disposition": 'attachment; filename="trip.ics"'})


@app.post("/export/booking")
def export_booking(body: RepriceRequest):
    it = _guard(run_reprice, body, get_settings())
    return to_booking_request(body.trip, it)


@app.post("/feedback")
def feedback(body: FeedbackIn):
    """Append feedback as JSON lines; analyze later to tune weights and defaults."""
    path = get_settings().feedback_file
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({**body.model_dump(), "ts": int(time.time())}) + "\n")
    return {"status": "saved"}


@app.post("/agent/chat")
def agent_chat(body: ChatIn):
    """Natural-language planning, e.g. 'Plan NYC to Seattle, Denver and Boston from Nov 2, cheapest'."""
    return run_agent(body.message, get_settings())
