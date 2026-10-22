"""Agent loop tests with fake OpenAI / Anthropic clients (no network, no API keys)."""
import json
from types import SimpleNamespace as NS

import anthropic
import openai

import app.agent as agent_mod

from app.agent import run_agent
from app.config import Settings

TRIP = {"origin": "NYC", "stops": ["SFO", "BOS", "SEA"], "start_date": "2026-11-02", "priority": "cost"}


def settings(provider):
    return Settings(provider, "sk-test", "gpt-4o-mini", "", "auto", "ant-test", "claude-sonnet-5-5", "synthetic", "", "", "", "data/f.jsonl")


class FakeOpenAI:
    """Turn 1: call the tool. Turn 2: final text. Calls without tools (the explainer) get plain text."""

    def __init__(self, args):
        self.args, self.calls = args, []
        self.chat = NS(completions=self)

    def create(self, **kw):
        if "tools" not in kw:
            return NS(choices=[NS(message=NS(content="Template-checked text.", tool_calls=None))])
        self.calls.append(kw)
        if len(self.calls) == 1:
            tc = NS(id="c1", function=NS(name="optimize_trip", arguments=json.dumps(self.args)))
            return NS(choices=[NS(message=NS(content=None, tool_calls=[tc]))])
        return NS(choices=[NS(message=NS(content="Best order found.", tool_calls=None))])


class FakeAnthropic:
    def __init__(self, args):
        self.args, self.calls = args, []
        self.messages = self

    def create(self, **kw):
        if "tools" not in kw:
            return NS(stop_reason="end_turn", content=[NS(type="text", text="Template-checked text.")])
        self.calls.append(kw)
        if len(self.calls) == 1:
            return NS(stop_reason="tool_use", content=[NS(type="tool_use", id="t1", name="optimize_trip", input=self.args)])
        return NS(stop_reason="end_turn", content=[NS(type="text", text="Best order found.")])


def test_openai_agent_calls_tool_and_returns_result(monkeypatch):
    fake = FakeOpenAI(TRIP)
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake)
    out = run_agent("Plan NYC to SF, Boston and Seattle", settings("openai"))
    assert out["reply"] == "Best order found." and out["result"].savings.cost >= 0
    tool_msg = fake.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "best_option" in tool_msg["content"]


def test_openai_agent_sends_tool_errors_back(monkeypatch):
    fake = FakeOpenAI({**TRIP, "origin": "XXX"})
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: fake)
    out = run_agent("bad trip", settings("openai"))
    assert out["result"] is None and "Unsupported" in fake.calls[1]["messages"][-1]["content"]


def test_anthropic_agent_calls_tool_and_returns_result(monkeypatch):
    fake = FakeAnthropic(TRIP)
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: fake)
    out = run_agent("Plan NYC to SF, Boston and Seattle", settings("anthropic"))
    assert out["reply"] == "Best order found." and out["result"].savings.cost >= 0
    assert fake.calls[1]["messages"][-1]["content"][0]["type"] == "tool_result"


def test_anthropic_agent_reports_tool_errors(monkeypatch):
    fake = FakeAnthropic({**TRIP, "origin": "XXX"})
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: fake)
    out = run_agent("bad trip", settings("anthropic"))
    assert out["result"] is None and fake.calls[1]["messages"][-1]["content"][0]["is_error"] is True


def custom_settings(tools):
    return Settings("openai", "", "my-model", "http://localhost:9999/v1", tools, "", "claude-sonnet-5-5", "synthetic", "", "", "", "data/f.jsonl")


def test_custom_endpoint_json_mode_runs_optimizer(monkeypatch):
    replies = iter([json.dumps(TRIP), "Plan summarized."])
    monkeypatch.setattr(agent_mod, "generate_text", lambda *a, **k: next(replies))
    out = run_agent("Plan NYC to SF, Boston and Seattle", custom_settings("off"))
    assert out["reply"] == "Plan summarized." and out["result"].savings.cost >= 0


def test_json_mode_asks_question_and_handles_bad_output(monkeypatch):
    monkeypatch.setattr(agent_mod, "generate_text", lambda *a, **k: '{"question": "Which date do you leave?"}')
    assert run_agent("plan a trip", custom_settings("off"))["reply"] == "Which date do you leave?"
    monkeypatch.setattr(agent_mod, "generate_text", lambda *a, **k: "sorry I cannot")
    assert run_agent("plan a trip", custom_settings("off"))["result"] is None


def test_auto_mode_falls_back_when_tools_unsupported(monkeypatch):
    class NoTools:
        def __init__(self):
            self.chat = NS(completions=self)

        def create(self, **kw):
            raise openai.BadRequestError("tools not supported", response=NS(request=None, status_code=400, headers={}), body=None)

    monkeypatch.setattr(openai, "OpenAI", lambda **kw: NoTools())
    replies = iter([json.dumps(TRIP), "Fallback worked."])
    monkeypatch.setattr(agent_mod, "generate_text", lambda *a, **k: next(replies))
    assert run_agent("Plan trip", custom_settings("auto"))["reply"] == "Fallback worked."
