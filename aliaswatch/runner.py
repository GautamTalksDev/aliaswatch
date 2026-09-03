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
import sys
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
MAX_RETRIES = 6
RETRY_BASE = 2.0

# Free tiers rate-limit hard. Without pacing, a 166-item battery trips the
# limit partway through and the day is recorded as a gap - which is honest but
# useless. Each spec carries its own requests-per-minute budget and the runner
# spaces calls to stay under it. A run that takes twenty minutes and completes
# is worth more than one that takes two and leaves a hole in the record.
DEFAULT_RPM = 30


@dataclass
class ModelSpec:
    key: str            # stable slug used in the public record, e.g. "claude-sonnet"
    label: str          # display name
    provider: str       # "anthropic" | "openai" | "google" | "openai_compat"
    alias: str          # the alias string as a user would type it
    base_url: str | None = None
    env_key: str = ""
    supports_tools: bool = True
    rpm: int = DEFAULT_RPM      # requests per minute this provider tolerates
    note: str = ""              # why this alias is in the index
    # Whether results are local-only. Explicit rather than inferred from the
    # provider string: "openai_compat" covers both Ollama on localhost and
    # hosted services like Groq, and guessing wrong would either leak local
    # data into the record or refuse to sign a real measurement.
    local: bool = False


# ---------------------------------------------------------------------------
# The index.
#
# Two kinds of entry, and the distinction is the whole point:
#
#   FLOATING aliases ("*-latest", or a bare product name) are names the
#   provider repoints at will. These are the real subjects - what a user gets
#   when they type that name is not fixed, and nobody publishes when it moves.
#
#   PINNED versions are the control. A pinned name should not move. If it
#   does, that is a much stronger finding than a floating alias moving, and
#   having both in the index is what lets the record tell them apart.
#
# Every entry below is reachable on a free tier. Paid ones are listed further
# down, commented out, so adding them later is one edit rather than research.
# ---------------------------------------------------------------------------

MODELS = [
    # --- Google, free tier at aistudio.google.com/apikey -------------------
    ModelSpec("gemini-flash-latest", "Gemini Flash (latest)", "google",
              "gemini-flash-latest", env_key="GEMINI_API_KEY", rpm=10,
              note="floating alias - repointed by Google without announcement"),
    ModelSpec("gemini-2.5-flash", "Gemini 2.5 Flash", "google",
              "gemini-2.5-flash", env_key="GEMINI_API_KEY", rpm=10,
              note="pinned version - the control for the alias above"),

    # --- Groq, free tier at console.groq.com/keys --------------------------
    ModelSpec("groq-gpt-oss-120b", "GPT-OSS 120B (Groq)", "openai_compat",
              "openai/gpt-oss-120b", base_url="https://api.groq.com/openai/v1",
              env_key="GROQ_API_KEY", rpm=25,
              note="open weights - paired with the Cerebras entry below"),
    ModelSpec("groq-gpt-oss-20b", "GPT-OSS 20B (Groq)", "openai_compat",
              "openai/gpt-oss-20b", base_url="https://api.groq.com/openai/v1",
              env_key="GROQ_API_KEY", rpm=25),
    ModelSpec("groq-qwen3-27b", "Qwen3.8 27B (Groq)", "openai_compat",
              "qwen/qwen3.8-27b", base_url="https://api.groq.com/openai/v1",
              env_key="GROQ_API_KEY", rpm=25),


    # --- Paid. Uncomment when a budget exists. -----------------------------
    # ModelSpec("claude-sonnet", "Claude Sonnet", "anthropic",
    #           "claude-sonnet-4-6", env_key="ANTHROPIC_API_KEY", rpm=50),
    # ModelSpec("gpt", "GPT (current default)", "openai",
    #           "gpt-5.1", env_key="OPENAI_API_KEY", rpm=50),
]


# ---------------------------------------------------------------------------
# Provider adapters. Each returns (text, tool_calls, usage).
#
# We measure the *alias*, not the weights. That distinction is stated on the
# methodology page and must never be blurred: routing changes, system-prompt
# changes, quantisation changes and weight changes all land here and AliasWatch
# cannot tell them apart. It reports that the thing you call changed.
# ---------------------------------------------------------------------------

class _Pacer:
    """Simple per-process request spacer. Not a token bucket: the battery is a
    steady serial stream, so even spacing is both sufficient and gentler on a
    shared free tier than bursting to the limit and backing off."""

    def __init__(self):
        self.last = 0.0
        self.interval = 60.0 / DEFAULT_RPM

    def set_rpm(self, rpm):
        self.interval = 60.0 / max(rpm, 1)

    def wait(self):
        now = time.monotonic()
        gap = self.last + self.interval - now
        if gap > 0:
            time.sleep(gap)
        self.last = time.monotonic()


PACER = _Pacer()


def _http_post(url, headers, payload, timeout=120):
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    # Some providers sit behind bot protection that rejects the default
    # "Python-urllib/x.y" agent outright (Cloudflare error 1010). Identify the
    # client honestly instead of disguising it.
    headers = {"user-agent": "aliaswatch/0.1 (+https://aliaswatch.dev)", **headers}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    last = None
    for attempt in range(MAX_RETRIES):
        PACER.wait()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            last = f"HTTP {e.code}: {body}"
            if e.code in (429, 500, 502, 503, 504, 529):
                # Honour Retry-After when the provider sends it; otherwise back
                # off exponentially with a floor, because retrying a 429 too
                # soon just burns another unit of the quota.
                ra = e.headers.get("Retry-After") if e.headers else None
                try:
                    delay = float(ra) if ra else max(RETRY_BASE ** attempt, 2.0)
                except ValueError:
                    delay = max(RETRY_BASE ** attempt, 2.0)
                time.sleep(min(delay, 90))
                continue
            raise RuntimeError(last)
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(min(RETRY_BASE ** attempt, 30))
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

# Kept for compatibility; authoritative flag is ModelSpec.local.
LOCAL_PROVIDERS = {"mock"}


def is_local_spec(spec) -> bool:
    return bool(getattr(spec, "local", False)) or spec.provider == "mock"


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


def _ckpt_path(spec, date, root):
    return root / date / f".{spec.key}.partial.jsonl"


def _load_checkpoint(path):
    """Return already-graded records keyed by item id."""
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            out[r["id"]] = r
        except (json.JSONDecodeError, KeyError):
            continue
    return out


def run_model(spec: ModelSpec, battery: dict, date: str, dry_run=False,
              drift=None, progress=True, resume=True) -> dict:
    """drift: optional {"family": str, "rate": float} used only by the mock
    provider, to inject a known change and watch the detector find it."""
    is_mock = spec.provider == "mock"
    is_local = is_local_spec(spec)

    key = os.environ.get(spec.env_key, "")
    if not key and not dry_run and not is_local:
        raise SystemExit(f"missing {spec.env_key}")

    if is_mock:
        from .local import call_mock

        def adapter(sp, it, k):
            return call_mock(sp, it, k, date_str=date, drift=drift)
    else:
        adapter = ADAPTERS[spec.provider]

    # Pace to this provider's budget. Without this the run uses the global
    # default, trips the provider's limit, and spends most of its time in
    # backoff - slower than simply going at the allowed rate.
    PACER.set_rpm(9999 if (is_mock or dry_run) else spec.rpm)

    # A 166-item run against a rate-limited free tier takes 15-30 minutes.
    # Writing only at the end means a crash at item 165 discards the whole day,
    # and unattended in CI that silently becomes a gap in the record. Each
    # graded item is appended to a checkpoint immediately, and a re-run of the
    # same date resumes from it instead of paying for those calls twice.
    root = RESULTS_LOCAL if is_local else RESULTS
    ckpt = _ckpt_path(spec, date, root)
    done = {} if (dry_run or not resume) else _load_checkpoint(ckpt)
    if done and progress:
        print(f"  resuming from checkpoint: {len(done)} items already graded")

    items = [i for i in battery["items"]
             if not (i["family"] == "tool_call" and not spec.supports_tools)]
    total = len(items)
    records = []
    errors = 0
    started = time.monotonic()
    if not dry_run:
        ckpt.parent.mkdir(parents=True, exist_ok=True)

    for n, item in enumerate(items, 1):
        if item["id"] in done:
            rec = done[item["id"]]
            records.append(rec)
            if rec.get("error"):
                errors += 1
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
        rec = {
            "id": item["id"],
            "family": item["family"],
            "response": text,
            "tool_calls": calls,
            "passed": g.passed,
            "value": g.value,
            "reason": g.reason,
            "error": err,
            "usage": usage,
        }
        records.append(rec)

        if not dry_run:
            with ckpt.open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        if progress and not dry_run:
            elapsed = time.monotonic() - started
            rate = n / max(elapsed, 1e-6)
            eta = int((total - n) / rate) if rate > 0 else 0
            mark = "!" if err else ("." if g.passed is not False else "x")
            sys.stdout.write(
                f"\r  [{n:3d}/{total}] {mark} {item['family']:<22}"
                f" err={errors:<3} eta={eta // 60}m{eta % 60:02d}s   ")
            sys.stdout.flush()

    if progress and not dry_run:
        sys.stdout.write("\r" + " " * 78 + "\r")
        sys.stdout.flush()

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
    """Write the day and clear the checkpoint: the run completed, so the
    partial file has served its purpose."""
    root = RESULTS_LOCAL if run.get("provenance") == "local" else RESULTS
    d = root / run["date"]
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{run['model']}.json").write_text(json.dumps(run, indent=1, ensure_ascii=False))
    (d / f"{run['model']}.summary.json").write_text(
        json.dumps(summarise(run), indent=1, ensure_ascii=False))
    ck = d / f".{run['model']}.partial.jsonl"
    if ck.exists():
        ck.unlink()


def main():
    import argparse

    # Piping into head/less closes stdout early; that is normal usage, not an
    # error worth a traceback.
    try:
        import signal
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except (ImportError, AttributeError, ValueError):
        pass
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
    ap.add_argument("--no-resume", action="store_true",
                    help="ignore any checkpoint and start the day over")
    ap.add_argument("--quiet", action="store_true", help="no progress line")
    ap.add_argument("--preflight", action="store_true",
                    help="one cheap call per alias to check reachability, then exit")
    a = ap.parse_args()

    from .local import FREE_TIER_NOTES, LOCAL_MODELS, MOCK_MODELS

    if a.free_tiers:
        print(FREE_TIER_NOTES)
        return

    if a.list:
        print(f"{'key':<20}{'alias':<26}{'rpm':<6}{'key env':<20}note")
        print("-" * 104)
        for sp in MODELS:
            print(f"{sp.key:<20}{sp.alias:<26}{sp.rpm:<6}{sp.env_key:<20}{sp.note}")
        for sp in LOCAL_MODELS:
            print(f"{sp.key:<20}{sp.alias:<26}{'-':<6}{'(none)':<20}local via Ollama")
        for sp in MOCK_MODELS:
            print(f"{sp.key:<20}{sp.alias:<26}{'-':<6}{'(none)':<20}mock, no network")
        print("\nLocal and mock runs write to results-local/ and never enter the record.")
        return

    if a.preflight:
        probe = {"prompt": "Compute 4817 + 2996. Reply with only the number.",
                 "id": "preflight", "family": "ground_truth",
                 "grader": "exact_numeric", "expected": "7813"}
        ok = bad = missing = 0
        print(f"{'model':22s}{'alias':28s}status")
        print("-" * 78)
        for spec in MODELS:
            key = os.environ.get(spec.env_key, "")
            if not key:
                print(f"{spec.key:22s}{spec.alias:28s}SKIP  {spec.env_key} not set")
                missing += 1
                continue
            PACER.set_rpm(spec.rpm)
            try:
                text, _, _ = ADAPTERS[spec.provider](spec, probe, key)
                g = graders.grade(probe, text, [])
                mark = "OK" if g.passed else "REACHABLE"
                print(f"{spec.key:22s}{spec.alias:28s}{mark:10s}{text.strip()[:24]!r}")
                ok += 1
            except Exception as e:  # noqa: BLE001
                msg = str(e).replace("\n", " ")
                # Surface the provider's own message, which is usually the
                # actionable part (deprecated alias, quota, wrong region).
                for marker in ('"message":', "message:"):
                    if marker in msg:
                        msg = msg.split(marker, 1)[1].strip().strip('"')
                        break
                print(f"{spec.key:22s}{spec.alias:28s}{'FAIL':10s}{msg[:60]}")
                bad += 1
        print(f"\n{ok} reachable, {bad} failing, {missing} missing a key")
        if bad:
            print("Fix or remove failing aliases before a real run: a day with "
                  ">5% errors is recorded as a gap, not data.")
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
        run = run_model(spec, battery, a.date, dry_run=a.dry_run,
                        progress=not a.quiet, resume=not a.no_resume)
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
