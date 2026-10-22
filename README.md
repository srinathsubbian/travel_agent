# Business Trip Itinerary Optimizer (AI agent)

FastAPI backend for the AI Fridays Season 2 problem: take trip parameters, return ranked multi-city
itineraries with cost and time savings, explain the choice, support live re-pricing after edits, and export
to calendar and booking systems.

**Design rule:** the optimizer decides, the LLM explains. Routes and prices come from a deterministic scoring
function. The LLM (OpenAI by default, Anthropic optional) (a) writes the plain-language explanation, which is
rejected in favour of a template if it contains a dollar amount the optimizer did not produce, and (b) powers a
chat agent that calls the optimizer as a tool (function calling).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # optional: add OPENAI_API_KEY (or ANTHROPIC_API_KEY), Amadeus keys
python -m app.diagnose        # checks packages, keys and the optimizer
pytest                        # 20 tests, no network or keys needed
uvicorn app.main:app --reload # docs at http://localhost:8000/docs
```

Works out of the box with synthetic fares and template explanations. Set `OPENAI_API_KEY` (model via
`OPENAI_MODEL`, default `gpt-4o-mini`) to turn on LLM explanations and the chat agent. With `DATA_PROVIDER=amadeus` plus sandbox keys it uses live data and
falls back to synthetic data per call if the API fails or rate-limits (the response's `data_source` says so).

## Using your own LLM (OpenAI-compatible API)

Any server that speaks the OpenAI chat API works (vLLM, Ollama, LM Studio, LiteLLM, most company gateways).
In `.env`:

```
OPENAI_BASE_URL=http://localhost:11434/v1   # your endpoint, usually ending in /v1
OPENAI_MODEL=your-model-name
OPENAI_API_KEY=                             # leave empty if your server needs none
LLM_TOOLS=auto                              # auto | on | off
```

`LLM_TOOLS=auto` tries function calling and falls back to JSON-extraction mode if the endpoint rejects tools;
use `off` for models without tool support. Run `python -m app.diagnose` to verify the connection.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/optimize` | Best 3 orderings, baseline, savings, explanation |
| POST | `/reprice` | Reprice a user-edited order (drag and drop) |
| POST | `/export/ics` | Calendar file for an order |
| POST | `/export/booking` | Booking or approval request JSON |
| POST | `/feedback` | Thumbs up/down to `data/feedback.jsonl` |
| POST | `/agent/chat` | Natural-language planning through LLM function calling |
| GET | `/cities`, `/health` | Supported cities, status |

```bash
curl -X POST localhost:8000/optimize -H 'content-type: application/json' \
  -d '{"origin":"NYC","stops":["SFO","BOS","SEA","ATL"],"start_date":"2026-11-02","priority":"balanced"}'

curl -X POST localhost:8000/agent/chat -H 'content-type: application/json' \
  -d '{"message":"Plan a trip from NYC to Seattle, Denver and Boston from Nov 2, cheapest, no Northline"}'
```

## Layout

```
app/
  main.py            REST API
  agent.py           Tool-calling loop (OpenAI or Anthropic) around the optimize_trip tool
  optimizer.py       Candidate orderings, leg selection, scoring, savings
  llm.py             OpenAI / Anthropic switch
  explainer.py       LLM explanation with number validation + template fallback
  service.py         Orchestration shared by API and agent
  calendar_export.py .ics and booking payload
  cities.py          Supported cities (add yours here)
  models.py          Pydantic schemas and input validation
  providers/         base + cache, synthetic data, Amadeus adapter with fallback
tests/               optimizer, API and agent tests (LLM clients are mocked)
```

## How the optimizer works

1. For up to 6 stops, price every visiting order (720 max). A per-request cache keeps real API calls low
   because each leg and date is looked up once, not once per ordering.
2. Per leg, choose the airline with the best weighted fare/duration score; the preferred airline gets a small
   boost; avoided airlines and early-departure limits are filters.
3. Score = `w_cost * cost/baseline + w_time * time/baseline + 0.12 * hotel-cap violations`. Weights come from
   `priority` (cost 0.8/0.2, balanced 0.5/0.5, fast 0.2/0.8).
4. The baseline is the order the traveler listed, priced by the same engine, so reported savings come from
   routing only.

## Known limits and next steps

- The Amadeus adapter is written against the documented v2/v3 endpoints but is not covered by tests (needs
  credentials). Verify it against the sandbox and adjust field names if the API version differs.
- Ground transport is a flat estimate per city. Flights are single-leg offers; connections are not modelled.
- Meeting-aware filtering (Microsoft Graph / Google Calendar) is the natural next feature: add busy windows to
  `TripRequest` and filter legs in `Planner.pick_leg`.
- Orderings are exhaustive up to 6 stops; beyond that use nearest-neighbour plus 2-opt.
- `/feedback` writes to a local file; use a database in production and add authentication.
