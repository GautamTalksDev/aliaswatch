"""Change detection.

Three properties the naive design lacked:

1. **Per-family detection, not one aggregate number.** A real regression is
   usually concentrated (refusals up, tool-calls unchanged). An aggregate flip
   count across 166 items dilutes a concentrated 30-item move below the floor
   and AliasWatch says "stable" while users are complaining. Every family is
   tested separately and the results are combined with a false-discovery-rate
   correction, so the headline stays honest without going deaf.

2. **Rolling baseline with changepoint exclusion.** A fixed 14-day opening
   window bakes any change that happens during it into the definition of
   normal, permanently inflating that model's floor. The baseline is a
   trailing window that excludes days already flagged as changed, and
   re-anchors after a confirmed change.

3. **Two-day confirmation.** A single day's excursion is provisional. It is
   published as 'watch', not 'changed'. Providers have transient incidents;
   a public record that cries wolf on those is worth nothing. Confirmation
   costs one day of latency and buys the credibility that is the entire asset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

MIN_BASELINE_DAYS = 7
BASELINE_WINDOW = 28
FDR_Q = 0.05                 # Benjamini - Hochberg level across families
CONFIRM_DAYS = 2             # consecutive excursions required to call 'changed'
VERBOSITY_EFFECT_MIN = 0.15  # 15% median shift before verbosity is reportable


@dataclass
class FamilyResult:
    family: str
    n_items: int
    fail_rate: float
    baseline_mean: float | None
    baseline_days: int
    p_value: float | None
    excursion: bool
    detail: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class DayVerdict:
    model: str
    date: str
    status: str                # "baselining" | "stable" | "watch" | "changed"
    families: list = field(default_factory=list)
    flagged_families: list = field(default_factory=list)
    changed_items: list = field(default_factory=list)
    note: str = ""

    def to_dict(self):
        d = asdict(self)
        d["families"] = [f.to_dict() if hasattr(f, "to_dict") else f for f in self.families]
        return d


# ---------------------------------------------------------------------------
# Binomial tail, exact. No scipy dependency: a stats library that changes its
# implementation would silently change AliasWatch's published history.
# ---------------------------------------------------------------------------

def _log_choose(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p). Upper tail, inclusive."""
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    p = min(max(p, 1e-9), 1 - 1e-9)
    total = 0.0
    for i in range(k, n + 1):
        total += math.exp(_log_choose(n, i) + i * math.log(p) + (n - i) * math.log(1 - p))
    return min(1.0, total)


def binom_two_sided(k: int, n: int, p: float) -> float:
    """Two-sided: a family can drift better as well as worse, and a sudden
    improvement is just as much a change worth recording."""
    if n == 0:
        return 1.0
    mean = n * p
    if k >= mean:
        tail = binom_sf(k, n, p)
    else:
        tail = 1.0 - binom_sf(k + 1, n, p)
    return min(1.0, 2.0 * tail)


def benjamini_hochberg(pvals: list[float], q: float = FDR_Q) -> list[bool]:
    """Which of these p-values survive at FDR q. Six families tested daily is
    six chances a day to be wrong; without correction AliasWatch would flag
    something roughly every three days by accident alone."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    keep = [False] * m
    cutoff = -1
    for rank, idx in enumerate(order, start=1):
        if pvals[idx] <= q * rank / m:
            cutoff = rank
    for rank, idx in enumerate(order, start=1):
        if rank <= cutoff:
            keep[idx] = True
    return keep


def median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


# ---------------------------------------------------------------------------
# Baseline construction
# ---------------------------------------------------------------------------

def build_baseline(history: list[dict], family: str, exclude_dates: set[str]) -> tuple[float | None, int]:
    """Trailing per-family failure rate over days not already flagged.

    `history` is oldest-first, each entry {date, families: {fam: {fails, n}}}.
    Days on which this model was flagged as changed are excluded: after a real
    change the old baseline is invalid, so the window re-anchors on post-change
    days only.
    """
    usable = [h for h in history if h["date"] not in exclude_dates]
    window = usable[-BASELINE_WINDOW:]
    fails = 0
    total = 0
    days = 0
    for h in window:
        f = h["families"].get(family)
        if not f or not f["n"]:
            continue
        fails += f["fails"]
        total += f["n"]
        days += 1
    if days < MIN_BASELINE_DAYS or total == 0:
        return None, days
    return fails / total, days


# ---------------------------------------------------------------------------
# The daily verdict
# ---------------------------------------------------------------------------

def evaluate_day(
    model: str,
    date: str,
    today: dict,
    history: list[dict],
    flagged_dates: set[str],
    recent_excursions: list[bool] | None = None,
) -> DayVerdict:
    """`flagged_dates` must contain every day that showed an excursion - 
    including unconfirmed 'watch' days, not only confirmed changes. Excluding
    only confirmed days lets the elevated days fold into the trailing window,
    which raises the baseline until the detector goes blind to the very shift
    it is watching.

    `recent_excursions` is the excursion flag for the previous two days, most
    recent last. Confirmation is 2 excursions within a 3-day window rather than
    2 strictly consecutive: with n=30 per family, a real shift does not clear
    the bar every single day, so strict consecutiveness misses genuine changes
    while buying almost nothing against transients.
    """
    """today: {families: {fam: {fails, n, items: [...]}}, verbosity: {...}}"""

    results: list[FamilyResult] = []
    pvals: list[float] = []
    testable: list[int] = []

    for fam, obs in sorted(today["families"].items()):
        n = obs["n"]
        fails = obs["fails"]
        rate = fails / n if n else 0.0
        base, days = build_baseline(history, fam, flagged_dates)

        if base is None:
            results.append(FamilyResult(fam, n, rate, None, days, None, False,
                                        "baselining"))
            continue

        p = binom_two_sided(fails, n, base)
        results.append(FamilyResult(fam, n, rate, base, days, p, False))
        pvals.append(p)
        testable.append(len(results) - 1)

    # Verbosity: continuous, tested separately, never contributes a flip count.
    vb = today.get("verbosity")
    if vb and vb.get("median") is not None:
        vb_hist = [h["verbosity"]["median"] for h in history[-BASELINE_WINDOW:]
                   if h.get("verbosity", {}).get("median") is not None
                   and h["date"] not in flagged_dates]
        if len(vb_hist) >= MIN_BASELINE_DAYS:
            base_med = median(vb_hist)
            if base_med > 0:
                shift = abs(vb["median"] - base_med) / base_med
                exc = shift >= VERBOSITY_EFFECT_MIN
                direction = "longer" if vb["median"] > base_med else "shorter"
                results.append(FamilyResult(
                    "verbosity", vb["n"], vb["median"], base_med, len(vb_hist),
                    None, exc,
                    f"median {vb['median']:.0f} vs {base_med:.0f} words ({direction}, {shift:.0%})",
                ))
        else:
            results.append(FamilyResult("verbosity", vb["n"], vb["median"], None,
                                        len(vb_hist), None, False, "baselining"))

    if not testable:
        return DayVerdict(model, date, "baselining", results, [], [],
                          "collecting baseline days")

    keep = benjamini_hochberg(pvals, FDR_Q)
    for slot, survives in zip(testable, keep):
        results[slot].excursion = survives

    flagged = [r.family for r in results if r.excursion]

    recent = list(recent_excursions or [])[-2:]
    if not flagged:
        status = "stable"
    elif any(recent):
        status = "changed"
    else:
        status = "watch"

    changed_items = []
    if flagged:
        for fam in flagged:
            obs = today["families"].get(fam)
            if obs:
                changed_items.extend(obs.get("newly_failing", []))

    note = ""
    if status == "watch":
        note = "excursion today; needs a second excursion within three days to be called a change"
    elif status == "changed":
        note = "confirmed: two excursions within a three-day window"

    return DayVerdict(model, date, status, results, flagged, changed_items, note)
