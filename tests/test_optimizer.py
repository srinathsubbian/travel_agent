from datetime import date

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.calendar_export import to_booking_request, to_ics
from app.config import get_settings
from app.explainer import _amounts_ok, build_facts, template_explanation
from app.main import app
from app.models import TripRequest
from app.optimizer import Planner, compute_savings
from app.providers.base import CachedProvider
from app.providers.synthetic import SyntheticProvider

client = TestClient(app)
BODY = {"origin": "NYC", "stops": ["SFO", "BOS", "SEA", "ATL"], "start_date": "2026-11-02"}


def planner(**kw):
    req = TripRequest(**{**BODY, **kw})
    return req, Planner(CachedProvider(SyntheticProvider()), req)


def test_best_is_never_worse_than_baseline():
    for prio in ("cost", "balanced", "fast"):
        req, p = planner(priority=prio)
        best = p.optimize()[0]
        assert best.score <= p.score(p.baseline) + 1e-9


def test_optimizer_finds_savings_on_zigzag_trip():
    req, p = planner()
    best = p.optimize()[0]
    s = compute_savings(p.baseline, best)
    assert s.cost > 0 and s.minutes > 0
    assert best.order != req.stops


def test_options_are_distinct_and_sorted():
    _, p = planner()
    opts = p.optimize(3)
    assert len({tuple(o.order) for o in opts}) == 3
    assert [o.score for o in opts] == sorted(o.score for o in opts)


def test_priority_changes_ranking_inputs():
    _, cost_p = planner(priority="cost")
    _, fast_p = planner(priority="fast")
    assert cost_p.optimize()[0].total_cost <= fast_p.optimize()[0].total_cost + 1e-9
    assert fast_p.optimize()[0].total_minutes <= cost_p.optimize()[0].total_minutes


def test_avoid_airline_is_respected():
    _, p = planner(avoid_airlines=["Northline"])
    assert all(l.airline != "Northline" for l in p.optimize()[0].legs)


def test_hotel_cap_flags_violations():
    _, p = planner(hotel_cap=100)
    assert p.baseline.violations == 4


def test_cache_limits_provider_calls():
    prov = CachedProvider(SyntheticProvider())
    Planner(prov, TripRequest(**BODY)).optimize()
    assert prov.calls < 200  # 120 orderings would be 600+ calls uncached


def test_request_validation():
    with pytest.raises(ValidationError):
        TripRequest(origin="XXX", stops=["SFO"], start_date=date(2026, 11, 2))
    with pytest.raises(ValidationError):
        TripRequest(origin="NYC", stops=["NYC"], start_date=date(2026, 11, 2))
    with pytest.raises(ValidationError):
        TripRequest(origin="NYC", stops=["SFO", "SFO"], start_date=date(2026, 11, 2))


def test_ics_and_booking():
    req, p = planner()
    it = p.optimize()[0]
    ics = to_ics(it)
    assert ics.startswith("BEGIN:VCALENDAR") and ics.count("BEGIN:VEVENT") == len(it.legs) + len(it.stays)
    assert to_booking_request(req, it)["estimated_total"] == round(it.total_cost, 2)


def test_explanation_amounts_validated():
    req, p = planner()
    best = p.optimize()[0]
    facts = build_facts(req, p.baseline, best)
    assert _amounts_ok(template_explanation(facts), facts)
    assert not _amounts_ok("This saves $99,999 overall.", facts)


def test_api_optimize_reprice_export():
    r = client.post("/optimize", json=BODY)
    assert r.status_code == 200
    data = r.json()
    assert data["savings"]["cost"] > 0 and len(data["options"]) == 3 and data["explanation"]
    order = data["options"][0]["order"][::-1]
    rp = client.post("/reprice", json={"trip": BODY, "order": order})
    assert rp.status_code == 200 and rp.json()["order"] == order
    assert "BEGIN:VCALENDAR" in client.post("/export/ics", json={"trip": BODY, "order": order}).text
    assert client.post("/export/booking", json={"trip": BODY, "order": order}).json()["flights"]


def test_api_rejects_bad_input():
    assert client.post("/optimize", json={**BODY, "origin": "ZZZ"}).status_code == 422
    assert client.post("/reprice", json={"trip": BODY, "order": ["SFO"]}).status_code == 422


def test_feedback_and_agent_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FEEDBACK_FILE", str(tmp_path / "fb.jsonl"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    assert client.post("/feedback", json={"vote": "up", "order": ["SFO"]}).json() == {"status": "saved"}
    assert (tmp_path / "fb.jsonl").read_text().count("\n") == 1
    assert "API_KEY" in client.post("/agent/chat", json={"message": "plan a trip"}).json()["reply"]
    assert client.get("/health").json()["status"] == "ok"


def test_root_serves_web_app():
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"] and "Itinerary" in r.text
    assert client.get("/docs").status_code == 200


def test_optimize_returns_trip_for_repricing():
    assert client.post("/optimize", json=BODY).json()["trip"]["stops"] == BODY["stops"]
