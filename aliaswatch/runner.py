"""Daily runner.

Archives the raw response for every item before grading. That archive is what
makes AliasWatch auditable: the model endpoint is gone tomorrow, so reproducibility
means anyone can re-run the *graders* over the *stored outputs* and get the
same numbers. It does not and cannot mean re-running yesterday's model.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import graders

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
# Local and mock runs are physically separated from the published record.
# A public log whose days were generated locally is worthless, so this is a
# different directory rather than a flag on the same one.
RESULTS_LOCAL = ROOT / "results-local"
MAX_RETRIES = 4
RETRY_BASE = 2.0


@dataclass
class ModelSpec:
    key: str            # stable slug used in the public record, e.g. "claude-sonnet"
    label: str          # display name
    provider: str       # "anthropic" | "openai" | "google" | "openai_compat"
    alias: str          # the alias string as a user would type it
    base_url: str | None = None
    env_key: str = ""
    supports_tools: bool = True


MODELS = [
    ModelSpec("claude-sonnet", "Claude Sonnet", "anthropic", "claude-sonnet-4-6",
              env_key="ANTHROPIC_API_KEY"),
    ModelSpec("gpt", "GPT (current default)", "openai", "gpt-5.1",
              env_key="OPENAI_API_KEY"),
    ModelSpec("gemini", "Gemini Pro", "google", "gemini-2.5-pro",
              env_key="GEMINI_API_KEY"),
]


# ---------------------------------------------------------------------------
# Provider adapters. Each returns (text, tool_calls, usage).
#
# We measure the *alias*, not the weights. That distinction is stated on the
# methodology page and must never be blurred: routing changes, system-prompt
# changes, quantisation changes and weight changes all land here and AliasWatch
# cannot tell them apart. It reports that the thing you call changed.
# ---------------------------------------------------------------------------

def _http_post(url, headers, payload, timeout=120):
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            last = f"HTTP {e.code}: {body}"
            if e.code in (429, 500, 502, 503, 504, 529):
                time.sleep(RETRY_BASE ** attempt)
                continue
            raise RuntimeError(last)
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(RETRY_BASE ** attempt)
    raise RuntimeError(f"exhausted retries: {last}")


def call_anthropic(spec, item, key):
    payload = {
        "model": spec.alias,
        "max_tokens": 1024,
        "temperature": 0,
        "messages": [{"role": "user", "content": item["prompt"]}],
    }
    if item.get("tools"):
        payload["tools"] = item["tools"]
    r = _http_post(
        "https://api.anthropic.com/v1/messages",
        {"content-type": "application/json", "x-api-key": key,
         "anthropic-version": "2023-06-01"},
        payload,
    )
    text = "".join(b.get("text", "") for b in r.get("content", []) if b.get("type") == "text")
    calls = [{"name": b["name"], "input": b.get("input", {})}
             for b in r.get("content", []) if b.get("type") == "tool_use"]
    return text, calls, r.get("usage", {})


def call_openai(spec, item, key, base_url=None):
    payload = {
        "model": spec.alias,
        "temperature": 0,
        "seed": 20260902,
        "messages": [{"role": "user", "content": item["prompt"]}],
    }
    if item.get("tools"):
        payload["tools"] = [
            {"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["input_schema"]}}
            for t in item["tools"]
        ]
    url = (base_url or "https://api.openai.com/v1") + "/chat/completions"
    r = _http_post(url, {"content-type": "application/json",
                         "authorization": f"Bearer {key}"}, payload)
    msg = r["choices"][0]["message"]
    text = msg.get("content") or ""
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append({"name": fn.get("name"), "input": args})
    return text, calls, r.get("usage", {})


def call_google(spec, item, key):
    parts = {"contents": [{"role": "user", "parts": [{"text": item["prompt"]}]}],
             "generationConfig": {"temperature": 0, "maxOutputTokens": 1024}}
    if item.get("tools"):
        parts["tools"] = [{"functionDeclarations": [
            {"name": t["name"], "description": t["description"],
             "parameters": t["input_schema"]} for t in item["tools"]]}]
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{spec.alias}:generateContent?key={key}")
    r = _http_post(url, {"content-type": "application/json"}, parts)
    cand = (r.get("candidates") or [{}])[0]
    segs = cand.get("content", {}).get("parts", [])
    text = "".join(s.get("text", "") for s in segs if "text" in s)
    calls = [{"name": s["functionCall"]["name"],
              "input": s["functionCall"].get("args", {})}
             for s in segs if "functionCall" in s]
    return text, calls, r.get("usageMetadata", {})


ADAPTERS = {
    "anthropic": call_anthropic,
    "openai": lambda s, i, k: call_openai(s, i, k),
    "openai_compat": lambda s, i, k: call_openai(s, i, k, s.base_url),
    "google": call_google,
}

# Providers that never touch the network or a paid account, and whose output
# must never enter the published record.
LOCAL_PROVIDERS = {"mock", "openai_compat"}


def all_models():
    """Hosted models plus the local/free ones."""
    from .local import LOCAL_MODELS, MOCK_MODELS
    return list(MODELS) + list(LOCAL_MODELS) + list(MOCK_MODELS)


# ---------------------------------------------------------------------------

def load_battery(version="v1"):
    p = ROOT / "battery" / f"{version}.json"
    body = json.loads(p.read_text())
    # Verify the seal on every run. A battery that has been edited in place
    # invalidates every comparison against every prior day.
    stated = body.pop("sha256")
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    actual = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    if stated != actual:
        raise SystemExit(
            f"BATTERY SEAL BROKEN for {version}\n"
            f"  stated: {stated}\n  actual: {actual}\n"
            "The battery has been modified in place. Publish v2 instead."
        )
    body["sha256"] = stated
    return body


def run_model(spec: ModelSpec, battery: dict, date: str, dry_run=False,
              drift=None) -> dict:
    """drift: optional {"family": str, "rate": float} used only by the mock
    provider, to inject a known change and watch the detector find it."""
    is_mock = spec.provider == "mock"
    is_local = spec.provider in LOCAL_PROVIDERS

    key = os.environ.get(spec.env_key, "")
    if not key and not dry_run and not is_local:
        raise SystemExit(f"missing {spec.env_key}")

    if is_mock:
        from .local import call_mock

        def adapter(sp, it, k):
            return call_mock(sp, it, k, date_str=date, drift=drift)
    else:
        adapter = ADAPTERS[spec.provider]
    records = []
    errors = 0

    for item in battery["items"]:
        if item["family"] == "tool_call" and not spec.supports_tools:
            continue
        try:
            if dry_run:
                text, calls, usage = "", [], {}
            else:
                text, calls, usage = adapter(spec, item, key)
            err = None
        except Exception as e:  # noqa: BLE001
            text, calls, usage, err = "", [], {}, str(e)[:200]
            errors += 1

        g = graders.grade(item, text, calls)
        records.append({
            "id": item["id"],
            "family": item["family"],
            "response": text,
            "tool_calls": calls,
            "passed": g.passed,
            "value": g.value,
            "reason": g.reason,
            "error": err,
            "usage": usage,
        })

    # A day with too many transport errors is a hole, not a measurement.
    # Publishing it as data would put a fake step in the history.
    err_rate = errors / max(1, len(records))
    incomplete = err_rate > 0.05

    return {
        "model": spec.key,
        "label": spec.label,
        "alias": spec.alias,
        "date": date,
        # Stamped on every record so local data can never be mistaken for a
        # measurement, even if the files are moved by hand.
        "provenance": "local" if is_local else "hosted",
        "battery_version": battery["battery_version"],
        "battery_sha256": battery["sha256"],
        "run_started_utc": datetime.now(timezone.utc).isoformat(),
        "error_rate": round(err_rate, 4),
        "incomplete": incomplete,
        "records": records,
    }


def summarise(run: dict) -> dict:
    """Collapse a run into the per-family counts stats.py consumes."""
    fams: dict[str, dict] = {}
    lengths = []
    for r in run["records"]:
        fam = r["family"]
        if fam in graders.CONTINUOUS_FAMILIES:
            if r["value"] is not None:
                lengths.append(r["value"])
            continue
        d = fams.setdefault(fam, {"n": 0, "fails": 0, "failing_ids": []})
        d["n"] += 1
        if r["passed"] is False:
            d["fails"] += 1
            d["failing_ids"].append(r["id"])

    from .stats import median
    return {
        "date": run["date"],
        "model": run["model"],
        "provenance": run.get("provenance", "hosted"),
        "incomplete": run["incomplete"],
        "families": fams,
        "verbosity": {"n": len(lengths), "median": median(lengths) if lengths else None},
    }


def save(run: dict):
    root = RESULTS_LOCAL if run.get("provenance") == "local" else RESULTS
    d = root / run["date"]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{run['model']}.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))
    (d / f"{run['model']}.summary.json").write_text(
        json.dumps(summarise(run), indent=1, ensure_ascii=False))


def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Run the sealed battery against model aliases.")
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    ap.add_argument("--models", default="")
    ap.add_argument("--battery", default="v1")
    ap.add_argument("--dry-run", action="store_true",
                    help="exercise the pipeline with empty responses; writes nothing")
    ap.add_argument("--mock", action="store_true",
                    help="keyless mock providers, no network (writes to results-local/)")
    ap.add_argument("--local", action="store_true",
                    help="local Ollama models (writes to results-local/)")
    ap.add_argument("--list", action="store_true", help="list available models and exit")
    ap.add_argument("--free-tiers", action="store_true",
                    help="print ways to run against real models for free")
    a = ap.parse_args()

    from .local import FREE_TIER_NOTES, LOCAL_MODELS, MOCK_MODELS

    if a.free_tiers:
        print(FREE_TIER_NOTES)
        return

    if a.list:
        print(f"{'key':<14}{'provider':<15}{'alias':<22}cost")
        print("-" * 74)
        for sp in MODELS:
            print(f"{sp.key:<14}{sp.provider:<15}{sp.alias:<22}needs an API key")
        for sp in LOCAL_MODELS:
            print(f"{sp.key:<14}{sp.provider:<15}{sp.alias:<22}free - Ollama, local")
        for sp in MOCK_MODELS:
            print(f"{sp.key:<14}{sp.provider:<15}{sp.alias:<22}free - no network, no install")
        print("\nLocal and mock runs write to results-local/ and never enter the record.")
        return

    battery = load_battery(a.battery)
    print(f"battery {battery['battery_version']} sealed "
          f"sha256={battery['sha256'][:16]}… ({battery['item_count']} items)")

    pool = MOCK_MODELS if a.mock else (LOCAL_MODELS if a.local else MODELS)
    wanted = set(a.models.split(",")) if a.models else None

    ran = 0
    for spec in pool:
        if wanted and spec.key not in wanted:
            continue
        ran += 1
        print(f"running {spec.key} ({spec.alias})…")
        run = run_model(spec, battery, a.date, dry_run=a.dry_run)
        sm = summarise(run)
        if a.dry_run:
            print(f"  dry run: {len(run['records'])} items graded, families="
                  f"{ {k: v['fails'] for k, v in sm['families'].items()} }")
            continue
        if run["incomplete"]:
            print(f"  INCOMPLETE ({run['error_rate']:.1%} errors) - "
                  "recorded as a gap, not a day")
        save(run)
        where = "results-local" if run["provenance"] == "local" else "results"
        fails = {k: f"{v['fails']}/{v['n']}" for k, v in sorted(sm["families"].items())}
        print(f"  saved {where}/{a.date}/{spec.key}.json")
        print(f"  {fails}  verbosity median "
              f"{sm['verbosity']['median'] and round(sm['verbosity']['median'])} words")

    if not ran:
        print("no models matched - try --list")


if __name__ == "__main__":
    main()
