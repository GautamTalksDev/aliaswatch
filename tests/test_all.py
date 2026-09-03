"""Tests.

Two jobs. First, the graders behave. Second - and this is the one that matters
publicly - a Monte Carlo that measures AliasWatch's own false-alarm rate under the
null hypothesis of no change at all. That number goes on the methodology page
*before* the first flag is published. A drift detector that has not measured
its own false positives is an opinion.
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aliaswatch import graders, stats  # noqa: E402

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def g(item, text, calls=None):
    return graders.grade(item, text, calls)


# ---------------------------------------------------------------------------
print("graders")

check("numeric exact", g({"family": "ground_truth", "grader": "exact_numeric",
                          "expected": "7813"}, "7813").passed)
check("numeric with commas", g({"family": "ground_truth", "grader": "exact_numeric",
                                "expected": "42441"}, "42,441").passed)
check("numeric wrong", not g({"family": "ground_truth", "grader": "exact_numeric",
                              "expected": "7813"}, "7814").passed)

check("text case-insensitive", g({"family": "ground_truth", "grader": "exact_text",
                                  "expected": "Astana"}, "astana").passed)
check("text embedded short", g({"family": "ground_truth", "grader": "exact_text",
                                "expected": "W"}, "The symbol is W.").passed)
check("text wrong", not g({"family": "ground_truth", "grader": "exact_text",
                           "expected": "Titan"}, "Enceladus").passed)

SCH = {"type": "object", "required": ["name", "years"],
       "properties": {"name": {"type": "string"}, "years": {"type": "integer"}},
       "additionalProperties": False}
check("json valid", g({"family": "format_compliance", "grader": "json_schema",
                       "schema": SCH}, '{"name":"Priya","years":11}').passed)
check("json fenced fails", not g({"family": "format_compliance", "grader": "json_schema",
                                  "schema": SCH},
                                 '```json\n{"name":"P","years":1}\n```').passed)
check("json extra key fails", not g({"family": "format_compliance", "grader": "json_schema",
                                     "schema": SCH},
                                    '{"name":"P","years":1,"x":2}').passed)
check("json bool not integer", not g({"family": "format_compliance", "grader": "json_schema",
                                      "schema": SCH},
                                     '{"name":"P","years":true}').passed)

check("preamble caught", not g({"family": "format_compliance", "grader": "no_preamble"},
                               "Sure! The answer is 101.").passed)
check("postamble caught", not g({"family": "format_compliance", "grader": "no_preamble"},
                                "101. Let me know if you need anything else!").passed)
check("bare passes", g({"family": "format_compliance", "grader": "no_preamble"}, "101").passed)

check("word count exact", g({"family": "constraint_adherence", "grader": "word_count",
                             "count": 5}, "Vast, cold, restless, ancient water").passed)
check("word count off", not g({"family": "constraint_adherence", "grader": "word_count",
                               "count": 5}, "Vast cold water").passed)
check("hyphen is one word", g({"family": "constraint_adherence", "grader": "word_count",
                               "count": 3}, "deep blue-green water").passed)

check("lipogram clean", g({"family": "constraint_adherence", "grader": "lipogram",
                           "forbidden": "e"}, "A calm dawn упon a bay.").passed)
check("lipogram caught", not g({"family": "constraint_adherence", "grader": "lipogram",
                                "forbidden": "e"}, "The harbour rested.").passed)

check("max chars ok", g({"family": "constraint_adherence", "grader": "max_chars",
                         "limit": 40}, "Boils water, whistles, burns fingers.").passed)
check("max chars over", not g({"family": "constraint_adherence", "grader": "max_chars",
                               "limit": 10}, "A rather long description here.").passed)

check("forbidden stem", not g({"family": "constraint_adherence", "grader": "forbidden_words",
                               "forbidden": ["plant"]}, "Green plants convert energy.").passed)
check("forbidden not substring", g({"family": "constraint_adherence",
                                    "grader": "forbidden_words",
                                    "forbidden": ["plant"]}, "Plantar fascia aches.").passed)

check("refusal detected", not g({"family": "refusal_rate", "grader": "refusal_detect"},
                                "I'm sorry, but I can't help with that.").passed)
check("answer passes", g({"family": "refusal_rate", "grader": "refusal_detect"},
                         "Bleach and ammonia form chloramine gas, which is toxic. " * 12).passed)
check("hedge then answer passes",
      g({"family": "refusal_rate", "grader": "refusal_detect"},
        "I can't give medical advice, but the mechanism is well documented. " * 15).passed)

TOOLS = [{"name": "get_weather", "description": "w",
          "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}}}]
check("tool correct", g({"family": "tool_call", "grader": "tool_selection", "tools": TOOLS,
                         "expected_tool": "get_weather", "expected_args": {"city": "Lagos"}},
                        "", [{"name": "get_weather", "input": {"city": "Lagos"}}]).passed)
check("tool wrong args", not g({"family": "tool_call", "grader": "tool_selection",
                                "tools": TOOLS, "expected_tool": "get_weather",
                                "expected_args": {"city": "Lagos"}},
                               "", [{"name": "get_weather", "input": {"city": "Quito"}}]).passed)
check("tool none expected", g({"family": "tool_call", "grader": "tool_selection",
                               "tools": TOOLS, "expected_tool": None, "expected_args": {}},
                              "Twelve times twelve is 144.", []).passed)
check("spurious call caught", not g({"family": "tool_call", "grader": "tool_selection",
                                     "tools": TOOLS, "expected_tool": None,
                                     "expected_args": {}},
                                    "", [{"name": "get_weather", "input": {}}]).passed)

check("empty never passes", not g({"family": "constraint_adherence",
                                   "grader": "max_chars", "limit": 40}, "").passed)
check("empty forbidden fails", not g({"family": "constraint_adherence",
                                      "grader": "forbidden_words",
                                      "forbidden": ["x"]}, "   ").passed)

check("verbosity non-binary", g({"family": "verbosity", "grader": "length_distribution"},
                                "one two three").passed is None)

# ---------------------------------------------------------------------------
print("statistics")

check("bh empty", stats.benjamini_hochberg([]) == [])
check("bh all null", not any(stats.benjamini_hochberg([0.4, 0.6, 0.9, 0.5, 0.7])))
check("bh catches one", stats.benjamini_hochberg([0.0001, 0.6, 0.9, 0.5, 0.7])[0])
check("binom symmetric", abs(stats.binom_two_sided(15, 30, 0.5) - 1.0) < 1e-6)
check("binom tail small", stats.binom_two_sided(28, 30, 0.1) < 1e-6)

check("baseline needs days", stats.build_baseline([], "ground_truth", set())[0] is None)


# ---------------------------------------------------------------------------
print("false-alarm simulation (this number is published)")

FAMILIES = {"ground_truth": (30, 0.02), "format_compliance": (30, 0.10),
            "constraint_adherence": (30, 0.35), "refusal_rate": (30, 0.05),
            "tool_call": (30, 0.08)}


def simulate(days=120, trials=60, seed=7):
    """Null world: nothing ever changes. Each item is an independent Bernoulli
    at its family's true rate. Count how often AliasWatch says 'changed'."""
    rng = random.Random(seed)
    false_changed = 0
    false_watch = 0
    total_days = 0

    for _ in range(trials):
        history = []
        flagged = set()
        recent = []
        for d in range(days):
            date = f"2026-01-{d:03d}"
            fams = {}
            for fam, (n, p) in FAMILIES.items():
                fails = sum(1 for _ in range(n) if rng.random() < p)
                fams[fam] = {"n": n, "fails": fails, "newly_failing": []}
            today = {"families": fams,
                     "verbosity": {"n": 16, "median": 120 + rng.gauss(0, 6)}}

            v = stats.evaluate_day("m", date, today, history, flagged, recent)
            if v.status != "baselining":
                total_days += 1
                if v.status == "changed":
                    false_changed += 1
                elif v.status == "watch":
                    false_watch += 1
            exc = bool(v.flagged_families)
            recent.append(exc)
            if exc:
                flagged.add(date)
            history.append({"date": date,
                            "families": {k: {"n": x["n"], "fails": x["fails"]}
                                         for k, x in fams.items()},
                            "verbosity": today["verbosity"]})
    return false_changed, false_watch, total_days


changed, watch, total = simulate()
rate_changed = changed / total
rate_watch = watch / total
print(f"  model-days evaluated : {total}")
print(f"  false 'changed'      : {changed}  ({rate_changed:.3%})")
print(f"  false 'watch'        : {watch}  ({rate_watch:.3%})")
print(f"  ≈ one false alarm every {1/rate_changed:,.0f} model-days"
      if rate_changed else "  no false alarms observed")

# The published claim. If confirmation logic regresses, this fails loudly.
check("false 'changed' rate under 1% of model-days", rate_changed < 0.01)

# ---------------------------------------------------------------------------
print("sensitivity (can it see a real, concentrated change?)")


def simulate_shift(shift_family="refusal_rate", new_p=0.25, seed=11):
    """Baseline for 30 days, then the refusal rate jumps 5% -> 25% on one
    family only. How many days until AliasWatch says 'changed'?"""
    rng = random.Random(seed)
    history, flagged, recent = [], set(), []
    for d in range(60):
        date = f"2026-02-{d:03d}"
        fams = {}
        for fam, (n, p) in FAMILIES.items():
            eff = new_p if (fam == shift_family and d >= 30) else p
            fails = sum(1 for _ in range(n) if rng.random() < eff)
            fams[fam] = {"n": n, "fails": fails, "newly_failing": []}
        today = {"families": fams, "verbosity": {"n": 16, "median": 120}}
        v = stats.evaluate_day("m", date, today, history, flagged, recent)
        if d >= 30 and v.status == "changed":
            return d - 30 + 1, v.flagged_families
        exc = bool(v.flagged_families)
        recent.append(exc)
        if exc:
            flagged.add(date)
        history.append({"date": date,
                        "families": {k: {"n": x["n"], "fails": x["fails"]}
                                     for k, x in fams.items()},
                        "verbosity": today["verbosity"]})
    return None, []


lag, fams_flagged = simulate_shift()
print(f"  refusal rate 5% -> 25% on 1 of 6 families")
print(f"  detected after       : {lag} days" if lag else "  NOT DETECTED in 30 days")
print(f"  families flagged     : {fams_flagged}")
check("concentrated 5%->25% shift detected within 5 days", lag is not None and lag <= 5)
check("flags the right family", "refusal_rate" in fams_flagged)

# What the old aggregate-only design would have done, for the record.
agg_before = sum(n * p for n, p in FAMILIES.values())
agg_after = agg_before - 30 * 0.05 + 30 * 0.25
print(f"  aggregate flip count : {agg_before:.0f}/150 -> {agg_after:.0f}/150 "
      f"({(agg_after-agg_before)/150:+.1%} of all items)")

# ---------------------------------------------------------------------------
print("editorial and legal safeguards")

from aliaswatch import card  # noqa: E402

for bad in ["GPT nerfed today", "the model got worse", "Claude degraded",
            "quality downgraded", "it is broken now"]:
    try:
        card.assert_no_editorialising(bad)
        check(f"guard rejects {bad!r}", False)
    except ValueError:
        check(f"guard rejects {bad!r}", True)

check("guard allows measured copy",
      card.assert_no_editorialising("changed today - 14 of 30 items moved") is None)

# Every card that the generator can actually produce must survive the guard.
for st in ("stable", "watch", "changed", "baselining"):
    days = [{"date": "2026-09-01", "status": st, "z": 1.0}]
    svg = card.card_svg("Some Model", "some-alias-1", st, 7, ["refusal_rate"],
                        12, 166, "2026-09-01", "0" * 64, days)
    check(f"card renders for status {st}", "<svg" in svg)
    check(f"card {st} carries non-affiliation notice", "Not affiliated" in svg)
    check(f"card {st} carries the alias caveat", "not the weights" in svg)

# The one claim the project must never make.
import pathlib as _pl  # noqa: E402
_readme = (_pl.Path(__file__).resolve().parent.parent / "README.md").read_text().lower()
check("README states the alias limitation", "alias" in _readme and "not the weights" in _readme)

# ---------------------------------------------------------------------------
print("tamper-evidence")

from aliaswatch import log as awlog  # noqa: E402

_seed = "22" * 32
_pub = awlog.public_key(_seed)
_sig = awlog.sign(_seed, b"head")
check("signature verifies", awlog.verify(_pub, b"head", _sig))
check("signature rejects altered message", not awlog.verify(_pub, b"heaD", _sig))
check("signature rejects wrong key",
      not awlog.verify(awlog.public_key("33" * 32), b"head", _sig))
check("canonical json is key-sorted and compact",
      awlog.canonical({"b": 1, "a": [2, 3]}) == '{"a":[2,3],"b":1}')

# ---------------------------------------------------------------------------
print("local / mock separation")

from aliaswatch import local as awlocal, runner as awrunner  # noqa: E402

check("mock providers are marked local",
      all(awrunner.is_local_spec(s) for s in awlocal.MOCK_MODELS))
check("ollama providers are marked local",
      all(awrunner.is_local_spec(s) for s in awlocal.LOCAL_MODELS))
check("hosted providers are not marked local",
      not any(awrunner.is_local_spec(s) for s in awrunner.MODELS))
# Groq and Cerebras share the openai_compat adapter with Ollama, so a
# provider-string heuristic would misclassify them. This asserts the fix.
check("hosted openai_compat models are not local",
      all(not awrunner.is_local_spec(s) for s in awrunner.MODELS
          if s.provider == "openai_compat"))
check("every hosted model declares an rpm budget",
      all(s.rpm > 0 for s in awrunner.MODELS))
check("local results go to a separate directory",
      awrunner.RESULTS_LOCAL != awrunner.RESULTS)

# Every mock response must actually satisfy (or fail) the grader it targets,
# or the fixture is testing nothing.
_bat = awrunner.load_battery("v1")
_spec = awlocal.MOCK_MODELS[0]
_pass_ok = _fail_ok = 0
for _it in _bat["items"]:
    if _it["family"] == "verbosity":
        continue
    _t, _c = awlocal._passing_response(_it)
    if graders.grade(_it, _t, _c).passed:
        _pass_ok += 1
    _t, _c = awlocal._failing_response(_it, random.Random(1))
    if graders.grade(_it, _t, _c).passed is False:
        _fail_ok += 1
_n = len([i for i in _bat["items"] if i["family"] != "verbosity"])
print(f"  mock passing responses graded pass: {_pass_ok}/{_n}")
print(f"  mock failing responses graded fail: {_fail_ok}/{_n}")
check("every mock 'pass' response passes its grader", _pass_ok == _n)
check("every mock 'fail' response fails its grader", _fail_ok == _n)

# ---------------------------------------------------------------------------
print("crash recovery")

import pathlib as _pathlib2  # noqa: E402
import shutil as _shutil  # noqa: E402
import tempfile as _tempfile  # noqa: E402

_tmp = _pathlib2.Path(_tempfile.mkdtemp())
_orig_local_root = awrunner.RESULTS_LOCAL
awrunner.RESULTS_LOCAL = _tmp
try:
    _bat2 = awrunner.load_battery("v1")
    _sp = awlocal.MOCK_MODELS[0]
    _date = "2026-01-01"
    _real = awlocal.call_mock
    _c = {"n": 0, "crash": True}

    def _counted(sp, it, k, date_str="", drift=None):
        _c["n"] += 1
        if _c["n"] > 40 and _c["crash"]:
            raise KeyboardInterrupt
        return _real(sp, it, k, date_str=date_str, drift=drift)

    awlocal.call_mock = _counted
    try:
        awrunner.run_model(_sp, _bat2, _date, progress=False)
    except KeyboardInterrupt:
        pass

    _ck = _tmp / _date / f".{_sp.key}.partial.jsonl"
    check("checkpoint written during a run", _ck.exists())
    check("checkpoint holds the completed items",
          len(_ck.read_text().splitlines()) == 40)

    _c["crash"] = False
    _c["n"] = 0
    _run = awrunner.run_model(_sp, _bat2, _date, progress=False)
    print(f"  resumed: {_c['n']} fresh calls, {len(_run['records'])} total records")
    check("resume does not repeat completed items", _c["n"] == 126)
    check("resumed run has the full battery", len(_run["records"]) == 166)

    awrunner.save(_run)
    check("checkpoint cleared once the day is saved", not _ck.exists())
finally:
    awlocal.call_mock = _real
    awrunner.RESULTS_LOCAL = _orig_local_root
    _shutil.rmtree(_tmp, ignore_errors=True)

# ---------------------------------------------------------------------------
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
