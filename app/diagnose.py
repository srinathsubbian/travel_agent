"""Setup check. Run from the project root (the folder that contains `app/`):

    python -m app.diagnose
"""
from __future__ import annotations

import importlib
import os
import sys
from datetime import date


def line(ok: bool | None, label: str, detail: str = "") -> None:
    tag = {True: "[ OK ]", False: "[FAIL]", None: "[SKIP]"}[ok]
    print(f"{tag} {label}" + (f" - {detail}" if detail else ""))


def main() -> int:
    failures = 0
    print(f"Python {sys.version.split()[0]} | cwd: {os.getcwd()}\n")

    for pkg in ("fastapi", "uvicorn", "pydantic", "httpx", "openai", "dotenv"):
        try:
            importlib.import_module(pkg)
            line(True, f"package {pkg}")
        except ImportError:
            failures += 1
            line(False, f"package {pkg}", "run: pip install -r requirements.txt")

    from .config import get_settings

    s = get_settings()
    if s.llm_provider == "openai":
        where = s.openai_base_url or "https://api.openai.com/v1 (DEFAULT: OPENAI_BASE_URL is not set)"
        endpoint = f", endpoint={where}, model={s.openai_model}"
    else:
        endpoint = f", model={s.model}"
    line(True, "settings loaded", f"data={s.data_provider}, llm={s.llm_provider}{endpoint}, tools={s.llm_tools}")
    from .llm import generate_text, key_hint, llm_enabled

    # Common mistake: an OpenAI key (sk-...) pasted on the ANTHROPIC_API_KEY line. Anthropic keys start with sk-ant-.
    ak, ok = s.anthropic_api_key, s.openai_api_key
    if ak and not ak.startswith("sk-ant-"):
        failures += 1
        line(False, "ANTHROPIC_API_KEY looks wrong", "it does not start with sk-ant-. If this is your OpenAI key, move it to OPENAI_API_KEY and clear this line")
    if ok and ok.startswith("sk-ant-"):
        failures += 1
        line(False, "OPENAI_API_KEY looks wrong", "it starts with sk-ant-, which is an Anthropic key")
    if os.getenv("LLM_PROVIDER"):
        line(None, "LLM_PROVIDER is set", f"forced to '{os.getenv('LLM_PROVIDER')}' (remove it to auto-detect)")

    line(llm_enabled(s) or None, key_hint(s), "set" if llm_enabled(s) else "not set (template explanations only, chat agent disabled)")
    amadeus_keys = bool(s.amadeus_client_id and s.amadeus_client_secret)
    line(amadeus_keys or None, "Amadeus keys", "set" if amadeus_keys else "not set (synthetic data)")

    try:
        from .models import TripRequest
        from .service import run_optimize

        req = TripRequest(origin="NYC", stops=["SFO", "BOS", "SEA", "ATL"], start_date=date(2026, 11, 2))
        res = run_optimize(req, s)
        line(True, "optimizer", f"best order {res.options[0].order}, saves ${res.savings.cost:,.0f} and {res.savings.minutes} min, source={res.data_source}")
    except Exception as exc:
        failures += 1
        line(False, "optimizer", repr(exc))

    if llm_enabled(s):
        try:
            reply = generate_text(s, "Reply with the single word ok.", "ping", max_tokens=20)
            line(True, f"{s.llm_provider} API call", reply)
        except Exception as exc:
            failures += 1
            line(False, f"{s.llm_provider} API call", repr(exc)[:300])
            if s.llm_provider == "openai" and not s.openai_base_url and "401" in repr(exc):
                print("       HINT: this key was sent to OpenAI's own servers. If your key belongs to your own LLM provider,\n"
                      "             set OPENAI_BASE_URL=<your endpoint, usually ending in /v1> in .env and run this again.")

    if amadeus_keys:
        try:
            from .providers.amadeus import AmadeusProvider

            AmadeusProvider(s)._auth()
            line(True, "Amadeus authentication")
        except Exception as exc:
            failures += 1
            line(False, "Amadeus authentication", repr(exc)[:300])

    print("\nAll checks passed." if not failures else f"\n{failures} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
