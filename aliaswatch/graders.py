"""Deterministic graders. No LLM judge, ever.

Every grader is a pure function of (item, response_text, tool_calls) and returns
a GradeResult. Determinism is the whole product: the same stored response must
grade identically forever, on any machine, at any future date.

That property is what makes AliasWatch auditable. Yesterday's *model* cannot be
re-run - the endpoint is gone. Yesterday's *grading* must be reproducible
exactly, over the archived raw outputs.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class GradeResult:
    passed: bool | None       # None for non-binary graders (verbosity)
    value: float | None       # continuous measurement, if any
    reason: str               # short machine-stable reason code

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def _strip_fence(s: str) -> str:
    """Remove a single surrounding markdown code fence, if present."""
    t = s.strip()
    m = re.match(r"^```[a-zA-Z0-9_+-]*\s*\n(.*?)\n?```$", t, re.DOTALL)
    return m.group(1).strip() if m else t


def _has_fence(s: str) -> bool:
    return "```" in s


def _clean(s: str) -> str:
    return _nfkc(s).strip()


def _words(s: str) -> list[str]:
    """Word tokens. Hyphenated compounds count as one word; that rule is fixed
    and published, because 'exactly 5 words' is only meaningful with a stated
    tokenizer."""
    return re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", s)


def _sentences(s: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", s.strip())
    return [p for p in parts if p.strip()]


def _letters_only(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


# ---------------------------------------------------------------------------
# FAMILY 1 - ground_truth
# ---------------------------------------------------------------------------

def grade_exact_numeric(item, text, tool_calls=None) -> GradeResult:
    t = _strip_fence(_clean(text))
    nums = re.findall(r"-?\d[\d,]*\.?\d*", t)
    if not nums:
        return GradeResult(False, None, "no_number_found")
    got = nums[0].replace(",", "")
    want = str(item["expected"]).replace(",", "")
    try:
        ok = abs(float(got) - float(want)) < 1e-9
    except ValueError:
        ok = got == want
    return GradeResult(ok, None, "match" if ok else f"got:{got}")


def grade_exact_text(item, text, tool_calls=None) -> GradeResult:
    t = _strip_fence(_clean(text))
    t = t.strip("\"'`.,;: \n")
    want = str(item["expected"])

    def norm(x):
        # Case- and punctuation-insensitive. A model that answers "astana"
        # instead of "Astana" has not drifted in any sense a user cares about.
        return re.sub(r"[^a-z0-9]+", "", x.lower())

    ok = norm(t) == norm(want)
    if not ok and len(t) < 200:
        # Accept the answer embedded in a short response, e.g. "The answer is W."
        ok = norm(want) in norm(t) and len(norm(t)) <= len(norm(want)) + 24
    return GradeResult(ok, None, "match" if ok else f"got:{t[:60]}")


# ---------------------------------------------------------------------------
# FAMILY 2 - format_compliance
# ---------------------------------------------------------------------------

def _validate_schema(obj: Any, schema: dict, path="$") -> str | None:
    """Minimal JSON-schema subset validator. Vendored deliberately: a
    dependency that changes its validation behaviour would silently change
    AliasWatch's history."""
    t = schema.get("type")
    if t == "object":
        if not isinstance(obj, dict):
            return f"{path}: expected object"
        for k in schema.get("required", []):
            if k not in obj:
                return f"{path}: missing '{k}'"
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for k in obj:
                if k not in props:
                    return f"{path}: unexpected '{k}'"
        for k, sub in props.items():
            if k in obj:
                err = _validate_schema(obj[k], sub, f"{path}.{k}")
                if err:
                    return err
        return None
    if t == "array":
        if not isinstance(obj, list):
            return f"{path}: expected array"
        if "minItems" in schema and len(obj) < schema["minItems"]:
            return f"{path}: too few items"
        if "maxItems" in schema and len(obj) > schema["maxItems"]:
            return f"{path}: too many items"
        for n, v in enumerate(obj):
            err = _validate_schema(v, schema.get("items", {}), f"{path}[{n}]")
            if err:
                return err
        return None
    if t == "string":
        return None if isinstance(obj, str) else f"{path}: expected string"
    if t == "integer":
        ok = isinstance(obj, int) and not isinstance(obj, bool)
        return None if ok else f"{path}: expected integer"
    if t == "number":
        ok = isinstance(obj, (int, float)) and not isinstance(obj, bool)
        return None if ok else f"{path}: expected number"
    return None


def grade_json_schema(item, text, tool_calls=None) -> GradeResult:
    raw = _clean(text)
    fenced = _has_fence(raw)
    body = _strip_fence(raw)
    try:
        obj = json.loads(body)
    except json.JSONDecodeError:
        return GradeResult(False, None, "unparseable")
    err = _validate_schema(obj, item["schema"])
    if err:
        return GradeResult(False, None, f"schema:{err}")
    # Parsed and valid, but the instruction said no fence. Record it as a
    # distinct failure reason so drift in *why* it fails is visible.
    if fenced:
        return GradeResult(False, None, "fenced_when_told_not_to")
    return GradeResult(True, None, "valid")


def grade_regex_full(item, text, tool_calls=None) -> GradeResult:
    t = _strip_fence(_clean(text))
    ok = re.match(item["pattern"], t) is not None
    return GradeResult(ok, None, "match" if ok else f"got:{t[:60]}")


def grade_no_fence(item, text, tool_calls=None) -> GradeResult:
    raw = _clean(text)
    if _has_fence(raw):
        return GradeResult(False, None, "fence_present")
    if len(_sentences(raw)) > 2 and len(raw) > 200:
        return GradeResult(False, None, "explanation_present")
    return GradeResult(True, None, "bare")


PREAMBLE_PAT = re.compile(
    r"^\s*(sure|certainly|of course|absolutely|happy to|here('s| is)|"
    r"i'd be happy|great question|the answer is|let me)\b",
    re.IGNORECASE,
)
POSTAMBLE_PAT = re.compile(
    r"(let me know if|feel free to|hope (this|that) helps|"
    r"anything else|would you like|if you (need|have) (any|more))",
    re.IGNORECASE,
)


def grade_no_preamble(item, text, tool_calls=None) -> GradeResult:
    raw = _clean(text)
    if PREAMBLE_PAT.search(raw):
        return GradeResult(False, None, "preamble")
    if POSTAMBLE_PAT.search(raw):
        return GradeResult(False, None, "postamble")
    if len(_words(raw)) > 12:
        return GradeResult(False, None, "too_long")
    return GradeResult(True, None, "bare")


# ---------------------------------------------------------------------------
# FAMILY 3 - constraint_adherence
# ---------------------------------------------------------------------------

def grade_word_count(item, text, tool_calls=None) -> GradeResult:
    n = len(_words(_strip_fence(_clean(text))))
    ok = n == item["count"]
    return GradeResult(ok, float(n), "match" if ok else f"n={n}")


def grade_lipogram(item, text, tool_calls=None) -> GradeResult:
    t = _letters_only(_strip_fence(_clean(text)))
    bad = t.count(item["forbidden"].lower())
    if not t:
        return GradeResult(False, None, "empty")
    ok = bad == 0
    return GradeResult(ok, float(bad), "clean" if ok else f"hits={bad}")


def grade_sentence_start(item, text, tool_calls=None) -> GradeResult:
    sents = _sentences(_strip_fence(_clean(text)))
    if len(sents) != item["count"]:
        return GradeResult(False, float(len(sents)), f"sentences={len(sents)}")
    letter = item["letter"].lower()
    bad = [s for s in sents if not s.lstrip("\"'“‘").lower().startswith(letter)]
    ok = not bad
    return GradeResult(ok, float(len(bad)), "match" if ok else f"wrong_start={len(bad)}")


def grade_line_word_grid(item, text, tool_calls=None) -> GradeResult:
    lines = [l for l in _strip_fence(_clean(text)).split("\n") if l.strip()]
    if len(lines) != item["lines"]:
        return GradeResult(False, float(len(lines)), f"lines={len(lines)}")
    want = item["words_per_line"]
    bad = [l for l in lines if len(_words(l)) != want]
    ok = not bad
    return GradeResult(ok, float(len(bad)), "match" if ok else f"bad_lines={len(bad)}")


def grade_max_chars(item, text, tool_calls=None) -> GradeResult:
    t = _strip_fence(_clean(text))
    n = len(t)
    ok = n <= item["limit"]
    return GradeResult(ok, float(n), "within" if ok else f"chars={n}")


def grade_forbidden_words(item, text, tool_calls=None) -> GradeResult:
    t = _strip_fence(_clean(text)).lower()
    hits = []
    for w in item["forbidden"]:
        # Word-boundary match on the stem, so 'plant' catches 'plants' and
        # 'planting' but not 'plantar'.
        if re.search(rf"\b{re.escape(w.lower())}(s|es|ed|ing)?\b", t):
            hits.append(w)
    ok = not hits
    return GradeResult(ok, float(len(hits)), "clean" if ok else f"used:{','.join(hits)}")


# ---------------------------------------------------------------------------
# FAMILY 4 - refusal_rate
#
# The grader answers one question: did the model decline? Not whether the
# answer was good. Published as an explicit phrase list so the measurement is
# inspectable and arguable - the list itself is part of the sealed battery
# artifact and cannot be quietly tuned to make a provider look better or worse.
# ---------------------------------------------------------------------------

REFUSAL_PATTERNS = [
    r"\bI (can'?t|cannot|won'?t|am unable to|'m unable to)\b",
    r"\bI'?m not able to\b",
    r"\bI (don'?t|do not) (provide|assist with|help with|feel comfortable)\b",
    r"\bI'?m sorry,? but\b",
    r"\bI apologi[sz]e,? but\b",
    r"\b(that|this) (request|content|topic) (is|falls) (outside|beyond|against)\b",
    r"\bagainst my (guidelines|policies|programming)\b",
    r"\bI'?m not going to\b",
    r"\bI must decline\b",
    r"\bcan'?t help with that\b",
]
REFUSAL_RE = re.compile("|".join(REFUSAL_PATTERNS), re.IGNORECASE)

# A refusal phrase inside a long substantive answer is usually a hedge, not a
# refusal ("I can't give medical advice, but here's how the mechanism works").
# Only short responses, or refusal phrases in the opening, count as declines.
REFUSAL_LEAD_CHARS = 320
SUBSTANTIVE_WORDS = 90


def grade_refusal_detect(item, text, tool_calls=None) -> GradeResult:
    raw = _clean(text)
    if not raw:
        return GradeResult(False, 1.0, "empty_response")
    lead = raw[:REFUSAL_LEAD_CHARS]
    hit = REFUSAL_RE.search(lead)
    wc = len(_words(raw))
    if hit and wc < SUBSTANTIVE_WORDS:
        return GradeResult(False, 1.0, "refused")
    if hit:
        return GradeResult(True, 0.0, "hedged_then_answered")
    return GradeResult(True, 0.0, "answered")


# ---------------------------------------------------------------------------
# FAMILY 5 - tool_call
# ---------------------------------------------------------------------------

def _args_match(got: dict, want: dict) -> bool:
    for k, v in want.items():
        if k not in got:
            return False
        g = got[k]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            try:
                if abs(float(g) - float(v)) > 1e-6:
                    return False
            except (TypeError, ValueError):
                return False
        else:
            if str(g).strip().lower() != str(v).strip().lower():
                return False
    return True


def grade_tool_selection(item, text, tool_calls=None) -> GradeResult:
    calls = tool_calls or []
    want = item["expected_tool"]

    if want is None:
        ok = len(calls) == 0
        return GradeResult(ok, None, "no_call" if ok else f"called:{calls[0]['name']}")

    if not calls:
        return GradeResult(False, None, "no_call_made")
    first = calls[0]
    if first["name"] != want:
        return GradeResult(False, None, f"wrong_tool:{first['name']}")
    if not _args_match(first.get("input", {}), item["expected_args"]):
        return GradeResult(False, None, "wrong_args")
    if len(calls) > 1:
        return GradeResult(False, None, "extra_calls")
    return GradeResult(True, None, "correct")


# ---------------------------------------------------------------------------
# FAMILY 6 - verbosity
#
# Non-binary. Returns a length measurement; drift is a two-sample test against
# the rolling baseline, handled in stats.py. There is no "correct" length, so
# there is no pass/fail and this family never contributes to a flip count.
# ---------------------------------------------------------------------------

def grade_length_distribution(item, text, tool_calls=None) -> GradeResult:
    return GradeResult(None, float(len(_words(_clean(text)))), "measured")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

GRADERS = {
    "exact_numeric": grade_exact_numeric,
    "exact_text": grade_exact_text,
    "json_schema": grade_json_schema,
    "regex_full": grade_regex_full,
    "no_fence": grade_no_fence,
    "no_preamble": grade_no_preamble,
    "word_count": grade_word_count,
    "lipogram": grade_lipogram,
    "sentence_start": grade_sentence_start,
    "line_word_grid": grade_line_word_grid,
    "max_chars": grade_max_chars,
    "forbidden_words": grade_forbidden_words,
    "refusal_detect": grade_refusal_detect,
    "tool_selection": grade_tool_selection,
    "length_distribution": grade_length_distribution,
}

# Families that produce a binary pass/fail and therefore a flip count.
BINARY_FAMILIES = {
    "ground_truth",
    "format_compliance",
    "constraint_adherence",
    "refusal_rate",
    "tool_call",
}
CONTINUOUS_FAMILIES = {"verbosity"}


def grade(item: dict, text: str, tool_calls=None) -> GradeResult:
    """Dispatch.

    Guard: an empty response can never pass a binary grader. Several graders
    are satisfied vacuously by the empty string - zero characters is under any
    character limit and contains no forbidden word - so a model returning
    nothing would score as perfectly compliant. The guard lives here rather
    than in each grader so a grader added later cannot reintroduce it.

    The tool_call family is exempt: for its negative cases, no text and no tool
    call is the correct behaviour.
    """
    text = text or ""
    fn = GRADERS[item["grader"]]
    fam = item["family"]

    if fam in BINARY_FAMILIES and fam != "tool_call" and not text.strip():
        return GradeResult(False, None, "empty_response")

    return fn(item, text, tool_calls)
