"""Build the published site.

Copies the static shell from web/, then emits the data the front end reads:

  data.json  — per-model day series with per-family detail
  log.json   — the signed chain, for in-browser verification

The renderer never invents a value. If there is no record, the site says so
rather than showing an estimate. `--demo` writes synthetic data into a separate
directory behind a permanent banner and never touches the published output.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
from datetime import date, timedelta
from pathlib import Path

from . import stats
from .graders import CONTINUOUS_FAMILIES

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
WEB = ROOT / "web"
DIST = ROOT / "dist"

REPO = "https://github.com/GautamTalksDev/aliaswatch"


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ---------------------------------------------------------------------------
# Day series
# ---------------------------------------------------------------------------

def build_models() -> list[dict]:
    if not RESULTS.exists():
        return []
    dates = sorted(d.name for d in RESULTS.iterdir() if d.is_dir())
    raw: dict[str, list] = {}
    for ds in dates:
        for f in sorted((RESULTS / ds).glob("*.summary.json")):
            s = json.loads(f.read_text())
            raw.setdefault(s["model"], []).append(s)

    from .runner import MODELS
    out = []
    for key, series in raw.items():
        history, flagged_dates, recent, days = [], set(), [], []
        for s in series:
            if s.get("incomplete"):
                days.append({"date": s["date"], "status": "baselining",
                             "flagged": [], "z": 0.0, "incomplete": True,
                             "families": {},
                             "note": "incomplete run — recorded as a gap, not data"})
                continue

            today = {
                "families": {k: {**v, "newly_failing": v.get("failing_ids", [])}
                             for k, v in s["families"].items()},
                "verbosity": s.get("verbosity", {}),
            }
            v = stats.evaluate_day(key, s["date"], today, history, flagged_dates, recent)
            exc = bool(v.flagged_families)
            recent.append(exc)
            if exc:
                flagged_dates.add(s["date"])

            fam_detail, zmax = {}, 0.0
            for r in v.families:
                if r.family in CONTINUOUS_FAMILIES:
                    fam_detail[r.family] = {
                        "n": r.n_items, "value": r.fail_rate,
                        "baseline": r.baseline_mean, "z": 0.0,
                    }
                    continue
                z = 0.0
                if r.baseline_mean is not None:
                    se = max((r.baseline_mean * (1 - r.baseline_mean)
                              / max(r.n_items, 1)) ** .5, 1e-6)
                    z = abs(r.fail_rate - r.baseline_mean) / se
                    zmax = max(zmax, z)
                fam_detail[r.family] = {
                    "n": r.n_items,
                    "fails": int(round(r.fail_rate * r.n_items)),
                    "baseline": r.baseline_mean,
                    "p": r.p_value, "z": round(z, 3),
                }

            days.append({"date": s["date"], "status": v.status,
                         "flagged": v.flagged_families, "z": round(zmax, 3),
                         "families": fam_detail, "note": v.note})
            history.append({"date": s["date"],
                            "families": {k: {"n": x["n"], "fails": x["fails"]}
                                         for k, x in s["families"].items()},
                            "verbosity": s.get("verbosity", {})})

        spec = next((x for x in MODELS if x.key == key), None)
        out.append({"key": key,
                    "label": spec.label if spec else key,
                    "alias": spec.alias if spec else key,
                    "days": days})
    return out


def make_demo() -> list[dict]:
    """Synthetic. Rendered only into dist/demo/ behind a banner."""
    rng = random.Random(3)
    start = date(2026, 7, 15)
    specs = [("claude-sonnet", "Claude Sonnet", "claude-sonnet-4-6", None, None),
             ("gpt", "GPT (current default)", "gpt-5.1", 34, "refusal_rate"),
             ("gemini", "Gemini Pro", "gemini-2.5-pro", 12, "format_compliance")]
    fam_base = {"ground_truth": (30, .02), "format_compliance": (30, .10),
                "constraint_adherence": (30, .35), "refusal_rate": (30, .05),
                "tool_call": (30, .08)}
    models = []
    for key, label, alias, shift, shift_fam in specs:
        days = []
        for i in range(50):
            d = (start + timedelta(days=i)).isoformat()
            if i < 7:
                days.append({"date": d, "status": "baselining", "flagged": [],
                             "z": 0.0, "families": {}, "note": ""})
                continue
            hot = shift is not None and shift <= i <= shift + 2
            fam, zmax = {}, 0.0
            for f, (n, p) in fam_base.items():
                eff = .28 if (hot and f == shift_fam) else p
                fails = sum(1 for _ in range(n) if rng.random() < eff)
                se = max((p * (1 - p) / n) ** .5, 1e-6)
                z = abs(fails / n - p) / se
                zmax = max(zmax, z)
                fam[f] = {"n": n, "fails": fails, "baseline": p, "z": round(z, 2)}
            fam["verbosity"] = {"n": 16, "value": 118 + rng.gauss(0, 7),
                                "baseline": 120, "z": 0}
            status, flagged = "stable", []
            if hot:
                status = "changed" if i > shift else "watch"
                flagged = [shift_fam]
            days.append({"date": d, "status": status, "flagged": flagged,
                         "z": round(zmax, 2), "families": fam, "note": ""})
        models.append({"key": key, "label": label, "alias": alias, "days": days})
    return models


# ---------------------------------------------------------------------------
# Prose pages
# ---------------------------------------------------------------------------

SHELL = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'">
<meta name="referrer" content="strict-origin-when-cross-origin">
<meta name="color-scheme" content="light dark">
<link rel="stylesheet" href="styles.css">
</head><body>
<a class="skip" href="#main">Skip to content</a>
<div class="wrap">
<div class="masthead">
  <a class="brand" href="./"><b>AliasWatch</b></a>
  <nav class="mastnav" aria-label="Primary">
    <a href="index.html">Record</a>
    <a href="methodology.html">Methodology</a>
    <a href="verify.html">Verify</a>
    <a href="legal.html">Legal</a>
  </nav>
</div>
<main id="main">
{body}
</main>
<footer>
<nav aria-label="Footer">
  <a href="index.html">Record</a><a href="methodology.html">Methodology</a>
  <a href="verify.html">Verify</a><a href="legal.html">Legal &amp; attribution</a>
  <a href="privacy.html">Privacy</a>
</nav>
<p>Code MIT. The record is CC0. Model and company names are the trademarks of
their respective owners and are used only to identify the services measured.
AliasWatch is not affiliated with, endorsed by, or sponsored by any of them.</p>
</footer>
</div></body></html>
"""


def md_to_html(md: str) -> str:
    """Small deliberate Markdown subset. Vendored rather than depending on a
    library, because the build must introduce no third-party code."""
    lines = md.split("\n")
    out, i = [], 0

    def inline(t):
        t = esc(t)
        t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", t)
        t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r'<a href="\2">\1</a>', t)
        return t

    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        if ln.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith("```"):
                buf.append(lines[i]); i += 1
            i += 1
            out.append("<pre class=\"vout\">" + esc("\n".join(buf)) + "</pre>")
            continue
        if set(ln.strip()) == {"-"} and len(ln.strip()) >= 3:
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", ln)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            i += 1
            continue
        if ln.lstrip().startswith("|"):
            tbl = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                tbl.append(lines[i]); i += 1
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in tbl]
            if not cells:
                continue
            rows = cells[1:]
            if len(cells) > 1 and all(set(c) <= set("-: ") for c in cells[1] if c):
                rows = cells[2:]
            out.append("<table><thead><tr>" +
                       "".join(f"<th>{inline(c)}</th>" for c in cells[0]) +
                       "</tr></thead><tbody>")
            for r in rows:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            out.append("</tbody></table>")
            continue
        if re.match(r"^\s*[-*]\s+", ln) or re.match(r"^\s*\d+\.\s+", ln):
            ordered = bool(re.match(r"^\s*\d+\.\s+", ln))
            items = []
            while i < len(lines) and (re.match(r"^\s*[-*]\s+", lines[i])
                                      or re.match(r"^\s*\d+\.\s+", lines[i])):
                items.append(re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", lines[i])); i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")
            continue
        para = []
        while (i < len(lines) and lines[i].strip()
               and not lines[i].lstrip().startswith("|")
               and not lines[i].startswith("```")
               and not re.match(r"^#{1,4}\s", lines[i])
               and not re.match(r"^\s*(?:[-*]|\d+\.)\s+", lines[i])):
            para.append(lines[i]); i += 1
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
    return "\n".join(out)


VERIFY_MD = """# Verify the record

Everything AliasWatch publishes can be checked without trusting AliasWatch.
That is the point of the project, so this page is written to be followed, not
to be reassuring.

## Check the chain in your browser

The [record page](index.html) recomputes every day's hash and every link
between days, locally. Nothing is sent anywhere. If you saved a head hash from
this site weeks ago, paste it in: if it is not in today's chain, the record has
been rewritten and you can prove it.

## Check the signatures offline

```
git clone https://github.com/GautamTalksDev/aliaswatch
cd aliaswatch
python3 -m aliaswatch.log verify
```

This recomputes every day digest from the archived response files, checks that
each day links to the one before, and verifies each signed head against the
published `signing-key.pub`. It needs no network and no dependencies.

## Re-grade the archive yourself

The strongest check. Every raw model response is archived under `results/`.
Re-running the published graders over them reproduces the published numbers
exactly, on any machine, at any future date:

```
python3 tests/test_all.py
```

This also re-measures the detector's own false-alarm rate by simulation and
fails if it has regressed.

## Reproduce a fresh day

You cannot re-run yesterday's model — that endpoint is gone, and no honest
project will tell you otherwise. What you can do is run the same sealed battery
against the same alias today and compare:

```
export ANTHROPIC_API_KEY=...
python3 -m aliaswatch.runner --models claude-sonnet
```

The battery's SHA-256 is verified before the run starts, so you know you are
asking exactly the same questions.

## What a failed check means

A chain break means a past day's files no longer hash to what was signed. That
is either an accident or an alteration. Either way it should be reported
publicly as an issue — including when the operator is the one who caused it. A
project that asks to be trusted has to make its own misbehaviour detectable by
strangers, or the request is empty.
"""

PRIVACY_MD = """# Privacy

AliasWatch collects nothing about you.

- No accounts, no sign-in, no email capture.
- No cookies.
- No analytics, no tag managers, no pixels, no session recording.
- No third-party requests of any kind. The page loads no external scripts,
  stylesheets, fonts, images or embeds. Everything comes from this origin, and
  that is enforced by a Content-Security-Policy of `default-src 'none'` which
  permits only `'self'`.
- No advertising. No data is sold, shared or brokered, because none is gathered.

The one piece of browser storage is your colour-theme preference, kept in
`localStorage` under the key `aw-theme`. It never leaves your device. Clearing
site data removes it.

The static host serving this site may keep standard request logs — IP address,
user agent, requested path — for operational and abuse-prevention purposes, as
any web server does. AliasWatch does not query, export, analyse or retain those
logs, and they are not linked to any identity.

Because AliasWatch collects and processes no personal data, there is nothing to
request, export or erase. If you have a question anyway, the contact address is
in the security policy.

If analytics are ever introduced, this page will be updated before deployment,
the change will be visible in the repository history, and a consent mechanism
will be added if the tooling requires one.
"""


def render_prose(title, md):
    return SHELL.format(title=esc(title), desc=esc(title), body=md_to_html(md))


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()

    out = DIST / "demo" if a.demo else DIST
    out.mkdir(parents=True, exist_ok=True)

    for f in ("index.html", "styles.css", "app.js", "robots.txt",
              "sitemap.xml", "_headers"):
        src = WEB / f
        if src.exists():
            shutil.copy2(src, out / f)
    wk = WEB / ".well-known"
    if wk.exists():
        shutil.copytree(wk, out / ".well-known", dirs_exist_ok=True)

    if a.demo:
        p = out / "index.html"
        p.write_text(p.read_text().replace(
            '<a class="skip" href="#main">',
            '<div class="banner"><b>Demo data.</b> These numbers are synthetic, '
            'generated to exercise the interface. They are not a record of any '
            "model's behaviour.</div>\n<a class=\"skip\" href=\"#main\">", 1))

    models = make_demo() if a.demo else build_models()

    try:
        seal = json.loads((ROOT / "battery" / "v1.json").read_text())["sha256"]
    except Exception:  # noqa: BLE001
        seal = ""

    last_run = models[0]["days"][-1]["date"] if models and models[0]["days"] else ""

    (out / "data.json").write_text(json.dumps({
        "generated": last_run, "last_run": last_run,
        "battery_version": "v1", "battery_sha256": seal,
        "repo": REPO, "demo": bool(a.demo), "models": models,
    }, indent=1))

    log_path = RESULTS / "log.jsonl"
    entries = []
    if log_path.exists():
        entries = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
    (out / "log.json").write_text(json.dumps(entries, indent=1))

    meth = ROOT / "METHODOLOGY.md"
    legal = ROOT / "legal" / "LEGAL.md"
    (out / "methodology.html").write_text(render_prose(
        "AliasWatch — methodology",
        meth.read_text() if meth.exists() else "# Methodology\n\nNot yet written."))
    (out / "verify.html").write_text(render_prose(
        "AliasWatch — verify the record", VERIFY_MD))
    (out / "privacy.html").write_text(render_prose(
        "AliasWatch — privacy", PRIVACY_MD))
    (out / "legal.html").write_text(render_prose(
        "AliasWatch — legal and attribution",
        legal.read_text() if legal.exists() else "# Legal\n\nNot yet written."))

    n = sum(len(m["days"]) for m in models)
    print(f"built {out} — {len(models)} models, {n} model-days, "
          f"{len(entries)} signed log entries")
    if not models:
        print("  (no record yet: the site renders an explicit empty state, "
              "not an estimate)")


if __name__ == "__main__":
    main()
