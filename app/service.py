"""Orchestration shared by the REST API and the agent."""
from __future__ import annotations

from .config import Settings
from .explainer import explain
from .models import Itinerary, OptimizeResult, RepriceRequest, TripRequest
from .optimizer import Planner, compute_savings
from .providers import get_provider


def run_optimize(req: TripRequest, settings: Settings, top_k: int = 3) -> OptimizeResult:
    provider = get_provider(settings)
    planner = Planner(provider, req)
    options = planner.optimize(top_k)
    baseline, best = planner.baseline, options[0]
    baseline.score = planner.score(baseline)
    return OptimizeResult(
        trip=req, baseline=baseline, options=options, savings=compute_savings(baseline, best),
        explanation=explain(req, baseline, best, settings), data_source=provider.name,
    )


def run_reprice(body: RepriceRequest, settings: Settings) -> Itinerary:
    """Reprice a user-edited order (drag and drop) without re-running the search."""
    planner = Planner(get_provider(settings), body.trip)
    it = planner.build(body.order)
    it.score = planner.score(it)
    return it
