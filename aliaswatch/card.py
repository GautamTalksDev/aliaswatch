"""Daily share card.

This is the growth engine, so it has one job: be screenshot-legible at thumbnail
size and be impossible to misread. Two rules it must never break - 

1. It never says "nerfed", "degraded", "worse", or names a cause. The card
   states what moved and links to the raw numbers. The moment the card editorialises,
   it stops being a record anyone can cite and becomes one more opinion.
2. It always carries the date and the battery hash, so a card screenshotted
   months later can still be traced to the exact run that produced it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "cards"

P = {"ground": "#F1F3EF", "ink": "#16191B", "muted": "#5E6660",
     "trace": "#2E5C6E", "stable": "#5C8060", "watch": "#B9852F",
     "changed": "#A8341F", "rule": "#D3D7D0"}

W, H = 1000, 524


# Words that would convert a measurement into an accusation. The legal
# position in legal/LEGAL.md §3 depends on cards never editorialising, so the
# rule is enforced here and asserted in the test suite rather than left to
# reviewer discipline.
FORBIDDEN_CARD_WORDS = [
    "nerf", "nerfed", "degrade", "degraded", "downgrade", "downgraded",
    "worse", "broken", "dumber", "lobotom", "gutted", "crippled",
]


def assert_no_editorialising(text: str) -> None:
    low = text.lower()
    hits = [w for w in FORBIDDEN_CARD_WORDS if w in low]
    if hits:
        raise ValueError(
            "share card copy contains editorialising language "
            f"({', '.join(hits)}). Cards state what moved and link to the raw "
            "numbers; they never characterise a provider's product. "
            "See legal/LEGAL.md section 3."
        )


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def card_svg(model_label, alias, status, day_run, flagged, moved, total,
             date_str, battery_sha, days):
    if status == "changed":
        accent = P["changed"]
        headline = "changed today"
        fams = ", ".join(flagged).replace("_", " ")
        sub = f"{moved} of {total} items moved · {fams}"
    elif status == "watch":
        accent = P["watch"]
        headline = "excursion, unconfirmed"
        sub = "one day beyond the floor · not yet called a change"
    elif status == "baselining":
        accent = P["rule"]
        headline = "collecting baseline"
        sub = "not enough days on record to test yet"
    else:
        accent = P["stable"]
        headline = "no significant change"
        sub = f"day {day_run} within the measured noise floor"

    # trace
    ticks = []
    n = max(len(days), 1)
    tw, th, tx, ty = 900, 92, 50, 300
    step = tw / n
    mid = ty + th / 2
    for i, d in enumerate(days):
        x = tx + i * step + step / 2
        z = min(abs(d.get("z", 0)), 4.0)
        amp = max((z / 4.0) * (th / 2 - 4), 1.5)
        st = d.get("status", "baselining")
        col = {"stable": P["trace"], "changed": P["changed"],
               "watch": P["watch"]}.get(st, P["rule"])
        wd = 4 if st in ("changed", "watch") else 2.4
        op = "1" if st in ("changed", "watch") else ".75"
        ticks.append(f'<line x1="{x:.1f}" y1="{mid-amp:.1f}" x2="{x:.1f}" '
                     f'y2="{mid+amp:.1f}" stroke="{col}" stroke-width="{wd}" '
                     f'opacity="{op}" stroke-linecap="round"/>')

    assert_no_editorialising(" ".join([model_label, headline, sub]))

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
<rect width="{W}" height="{H}" fill="{P['ground']}"/>
<rect x="0" y="0" width="{W}" height="8" fill="{accent}"/>
<text x="50" y="86" font-family="ui-monospace,monospace" font-size="20"
      fill="{P['muted']}" letter-spacing="1">AliasWatch · {esc(date_str)}</text>
<text x="50" y="162" font-family="Georgia,ui-serif,serif" font-size="62"
      fill="{P['ink']}">{esc(model_label)}</text>
<text x="50" y="228" font-family="Georgia,ui-serif,serif" font-size="46"
      fill="{accent}">{esc(headline)}</text>
<text x="50" y="272" font-family="ui-sans-serif,sans-serif" font-size="24"
      fill="{P['muted']}">{esc(sub)}</text>
<line x1="{tx}" y1="{mid}" x2="{tx+tw}" y2="{mid}" stroke="{P['rule']}" stroke-width="1"/>
{''.join(ticks)}
<text x="50" y="{ty+th+46}" font-family="ui-monospace,monospace" font-size="17"
      fill="{P['muted']}">{esc(alias)} · battery v1 {esc(battery_sha[:12])} · {len(days)} days on record</text>
<text x="50" y="{ty+th+76}" font-family="ui-monospace,monospace" font-size="17"
      fill="{P['trace']}">aliaswatch.dev</text>
<text x="{W-50}" y="{ty+th+76}" text-anchor="end" font-family="ui-sans-serif,sans-serif"
      font-size="14" fill="{P['muted']}">Measures the public API alias, not the weights. Not affiliated with any provider.</text>
</svg>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    from .site import build_models, make_demo
    models = make_demo() if a.demo else build_models()
    if not models:
        print("no record yet - no cards generated")
        return

    try:
        sha = json.loads((ROOT / "battery" / "v1.json").read_text())["sha256"]
    except Exception:  # noqa: BLE001
        sha = "unsealed"

    for m in models:
        days = m["days"]
        if not days:
            continue
        last = days[-1]
        run = 0
        for d in reversed(days):
            if d["status"] == "stable":
                run += 1
            else:
                break
        moved = last.get("fails", 0)
        svg = card_svg(m["label"], m["alias"], last["status"], run,
                       last.get("flagged", []),
                       moved if isinstance(moved, int) else 0, 166,
                       last["date"], sha, days)
        p = OUT / f"{m['key']}-{last['date']}.svg"
        p.write_text(svg)
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
