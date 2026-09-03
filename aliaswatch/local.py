"""Local and free-tier providers.

Two reasons this module exists.

**Cost.** Nothing in the pipeline should require a paid key to develop against.
Ollama runs open-weight models on your own machine for nothing, and it speaks
the OpenAI chat-completions shape, so the existing adapter works unchanged.

**Integrity.** Local and mock runs must never contaminate the published record.
Everything here writes to `results-local/`, never `results/`, and every file it
produces carries `"provenance": "local"`. The site refuses to render local data
except in demo mode, behind the banner. A public log with locally-generated
early days is worth exactly nothing, so the separation is enforced in code
rather than left to memory.

Local models are for exercising the harness - the graders, the statistics, the
site, the signing chain. They are NOT a measurement of anything: a model on
your laptop has no alias that can silently change underneath you, which is the
entire phenomenon AliasWatch exists to record.
"""

from __future__ import annotations

import hashlib
import json
import random
import re

from .runner import ModelSpec

# ---------------------------------------------------------------------------
# Ollama - free, local, no key. `ollama serve` then `ollama pull qwen3:8b`.
# ---------------------------------------------------------------------------

OLLAMA_BASE = "http://localhost:11434/v1"

LOCAL_MODELS = [
    ModelSpec("qwen3-8b", "Qwen3 8B (local)", "openai_compat", "qwen3:8b",
              base_url=OLLAMA_BASE, env_key="OLLAMA_UNUSED", local=True),
    ModelSpec("gemma3-4b", "Gemma 3 4B (local)", "openai_compat", "gemma3:4b",
              base_url=OLLAMA_BASE, env_key="OLLAMA_UNUSED", local=True),
    ModelSpec("llama32-3b", "Llama 3.2 3B (local)", "openai_compat", "llama3.2:3b",
              base_url=OLLAMA_BASE, env_key="OLLAMA_UNUSED", local=True),
]

# Free hosted tiers. Still need a key, but no card. Listed so the choice is
# visible rather than something you have to go research.
FREE_TIER_NOTES = """
Free ways to run this against real hosted models:

  Google Gemini   aistudio.google.com/apikey    generous free tier, no card
  Groq            console.groq.com/keys         free tier, open-weight models
  NVIDIA NIM      build.nvidia.com              free credits, no card
  Cerebras        cloud.cerebras.ai             free tier

Set GEMINI_API_KEY and run:  aliaswatch run --models gemini

Anthropic and OpenAI both require payment. They can be added later; the
harness does not care which providers are present.
"""


# ---------------------------------------------------------------------------
# Mock provider - no network, no install, no key.
#
# Produces deterministic, seeded responses that are *plausibly shaped* for each
# grader, with a controllable failure rate per family. This exercises every
# grader branch, the statistics, the chain and the site without touching
# anything external. It is a test fixture, not a model.
# ---------------------------------------------------------------------------

MOCK_MODELS = [
    ModelSpec("mock-a", "Mock Model A", "mock", "mock-a-v1", env_key="MOCK", local=True),
    ModelSpec("mock-b", "Mock Model B", "mock", "mock-b-v1", env_key="MOCK", local=True),
]

# Roughly the failure rates a competent model shows on this battery, so the
# simulated record looks like the real thing rather than all-zeros.
MOCK_BASE_RATES = {
    "ground_truth": 0.03,
    "format_compliance": 0.12,
    "constraint_adherence": 0.38,
    "refusal_rate": 0.06,
    "tool_call": 0.10,
    "verbosity": 0.0,
}

REFUSAL_TEXT = "I'm sorry, but I can't help with that request."


def _rng_for(model_key: str, date_str: str, item_id: str, salt: str = "") -> random.Random:
    """Deterministic per (model, day, item). Same inputs always give the same
    mock response, so a mock run is reproducible like a real one."""
    h = hashlib.sha256(f"{model_key}|{date_str}|{item_id}|{salt}".encode()).digest()
    return random.Random(int.from_bytes(h[:8], "big"))


def _passing_response(item):
    """A response the item's grader will accept."""
    g = item["grader"]

    if g == "exact_numeric":
        return str(item["expected"]), []
    if g == "exact_text":
        return str(item["expected"]), []
    if g == "json_schema":
        return json.dumps(_sample_for_schema(item["schema"])), []
    if g == "regex_full":
        return _sample_for_pattern(item["pattern"]), []
    if g == "no_fence":
        return "s[::-1]", []
    if g == "no_preamble":
        return "101", []
    if g == "word_count":
        return " ".join(["word"] * item["count"]), []
    if g == "lipogram":
        bad = item["forbidden"].lower()
        pool = [w for w in ["cold", "dark", "wind", "ship", "stone", "night", "grey"]
                if bad not in w]
        return " ".join(pool[:6]) + ".", []
    if g == "sentence_start":
        L = item["letter"]
        return " ".join([f"{L}inter came slowly." for _ in range(item["count"])]), []
    if g == "line_word_grid":
        line = " ".join(["word"] * item["words_per_line"])
        return "\n".join([line] * item["lines"]), []
    if g == "max_chars":
        return "short"[: max(item["limit"] - 1, 1)], []
    if g == "forbidden_words":
        return "A process converts energy into stored chemical bonds.", []
    if g == "refusal_detect":
        return ("The mechanism is well documented and worth understanding. " * 14), []
    if g == "tool_selection":
        want = item["expected_tool"]
        if want is None:
            return "Here is a plain answer with no tool needed.", []
        return "", [{"name": want, "input": dict(item["expected_args"])}]
    if g == "length_distribution":
        return " ".join(["word"] * 120), []
    return "ok", []


def _failing_response(item, rng):
    """A response the grader will reject, in a realistic way."""
    g = item["grader"]

    if g in ("exact_numeric",):
        return "0", []
    if g in ("exact_text",):
        return "something else entirely", []
    if g == "json_schema":
        return "```json\n" + json.dumps(_sample_for_schema(item["schema"])) + "\n```", []
    if g == "regex_full":
        return "Sure! Here you go: something", []
    if g == "no_fence":
        return "```python\ns[::-1]\n```", []
    if g == "no_preamble":
        return "Sure! The answer is 101. Let me know if you need anything else!", []
    if g == "word_count":
        return " ".join(["word"] * (item["count"] + rng.choice([-1, 1, 2]))), []
    if g == "lipogram":
        return f"The {item['forbidden']}vening settled over the harbour.", []
    if g == "sentence_start":
        return "This does not start correctly. Neither does this one.", []
    if g == "line_word_grid":
        return "too few words\nand another line", []
    if g == "max_chars":
        return "x" * (item["limit"] + 25), []
    if g == "forbidden_words":
        return f"It clearly involves {item['forbidden'][0]} in the usual way.", []
    if g == "refusal_detect":
        return REFUSAL_TEXT, []
    if g == "tool_selection":
        want = item["expected_tool"]
        if want is None:
            t = item["tools"][0]
            return "", [{"name": t["name"], "input": {}}]
        return "I'd be happy to help with that.", []
    if g == "length_distribution":
        return " ".join(["word"] * 120), []
    return "", []


def _sample_for_schema(schema):
    t = schema.get("type")
    if t == "object":
        out = {}
        for k, sub in schema.get("properties", {}).items():
            if k in schema.get("required", []) or True:
                out[k] = _sample_for_schema(sub)
        return out
    if t == "array":
        n = schema.get("minItems", 1)
        return [_sample_for_schema(schema.get("items", {})) for _ in range(n)]
    if t == "integer":
        return 7
    if t == "number":
        return 7.0
    return "sample"


def _sample_for_pattern(pattern):
    """Hand-mapped samples for the sealed battery's regex items. A general
    regex generator would be a dependency and a source of flakiness."""
    table = {
        r"^acknowledged$": "acknowledged",
        r"^[0-9a-f]{2}$": "3f",
        r"^Wednesday$": "Wednesday",
        r"^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$": "10.0.0.1",
        r"^FALSE$": "FALSE",
        r"^2,3,5,7,11$": "2,3,5,7,11",
        r"^[a-z]+;[a-z]+;[a-z]+$": "red;blue;green",
        r"^id,name\n[^\n]+$": "id,name\n1,alice",
        r"^2027-01-01T00:00:00(Z|\+00:00)$": "2027-01-01T00:00:00Z",
    }
    if pattern in table:
        return table[pattern]
    if "uuid" in pattern.lower() or "4[0-9a-fA-F]{3}" in pattern:
        return "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    return "sample"


def call_mock(spec, item, key, date_str="", drift=None):
    """Deterministic fake. `drift` optionally raises one family's failure rate,
    so a change can be injected and the detector watched from the outside."""
    fam = item["family"]
    rng = _rng_for(spec.key, date_str, item["id"])
    rate = MOCK_BASE_RATES.get(fam, 0.1)
    if drift and drift.get("family") == fam:
        rate = drift.get("rate", rate)

    if fam == "verbosity":
        base = 118 if spec.key == "mock-a" else 96
        if drift and drift.get("family") == "verbosity":
            base = int(base * drift.get("multiplier", 1.0))
        n = max(int(rng.gauss(base, 12)), 5)
        return " ".join(["word"] * n), [], {}

    if rng.random() < rate:
        text, calls = _failing_response(item, rng)
    else:
        text, calls = _passing_response(item)
    return text, calls, {}


# ---------------------------------------------------------------------------
# Simulate a stretch of days, optionally injecting a real change partway
# through, so the whole pipeline can be watched end to end without a key.
# ---------------------------------------------------------------------------

def main():
    import argparse
    from datetime import date as _date, timedelta

    ap = argparse.ArgumentParser(
        description="Generate a local mock record so you can see the whole "
                    "pipeline work. Writes to results-local/ only.")
    ap.add_argument("--days", type=int, default=40)
    ap.add_argument("--start", default="",
                    help="YYYY-MM-DD; defaults to --days ago")
    ap.add_argument("--inject-on", type=int, default=25,
                    help="day index on which to inject a change (-1 for none)")
    ap.add_argument("--inject-family", default="refusal_rate")
    ap.add_argument("--inject-rate", type=float, default=0.30)
    ap.add_argument("--inject-model", default="mock-b")
    ap.add_argument("--clean", action="store_true",
                    help="wipe results-local/ first")
    a = ap.parse_args()

    from .runner import RESULTS_LOCAL, load_battery, run_model, save
    import shutil

    if a.clean and RESULTS_LOCAL.exists():
        shutil.rmtree(RESULTS_LOCAL)

    battery = load_battery("v1")
    start = (_date.fromisoformat(a.start) if a.start
             else _date.today() - timedelta(days=a.days - 1))

    print(f"simulating {a.days} days from {start} into results-local/")
    if a.inject_on >= 0:
        print(f"injecting: {a.inject_model} {a.inject_family} "
              f"-> {a.inject_rate:.0%} from day {a.inject_on}")

    for i in range(a.days):
        d = (start + timedelta(days=i)).isoformat()
        for spec in MOCK_MODELS:
            drift = None
            if (a.inject_on >= 0 and i >= a.inject_on
                    and spec.key == a.inject_model):
                drift = {"family": a.inject_family, "rate": a.inject_rate}
            run = run_model(spec, battery, d, drift=drift)
            save(run)
        if (i + 1) % 10 == 0 or i == a.days - 1:
            print(f"  {i + 1}/{a.days} days")

    print("\nNow build the site from the local record:")
    print("  python3 -m aliaswatch.site --local")
    print("  python3 -m http.server 8080 --directory dist/local")


if __name__ == "__main__":
    main()
