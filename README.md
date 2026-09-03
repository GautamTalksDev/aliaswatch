# AliasWatch

**A daily public record of whether the major AI model aliases changed.**

The same sealed battery of 166 deterministic prompts, run every day against
every major model alias, graded by machine against a published noise floor,
and written to a signed, append-only log that anyone can verify offline.

No model judges another model. Nothing is estimated. Gaps are shown as gaps.

"The model got nerfed" is one of the most repeated complaints in AI, and there
is no neutral public record to point at. This is that record.

---

## Kill test

Pre-registered. Resolves on the date, by the numbers, with no argument and no
extension.

> **By 15 November 2026**, either
> **(a)** an AliasWatch card is cited by ≥3 people the author does not know, or
> **(b)** the site has ≥1,000 unique visitors in a single week.
>
> If neither: freeze the harness (it costs almost nothing to keep running),
> stop building features, publish the numbers in one paragraph, and put all
> remaining hours into the other project.

Criterion (a) is the real test. (b) is one lucky link away from being noise - 
it is listed second on purpose and is not a pass on its own.

---

## What it measures

| Family | Items | Catches |
|---|---:|---|
| `ground_truth` | 30 | Arithmetic, extraction, closed-book facts. The control group - these should not move. |
| `format_compliance` | 30 | Instruction-following decay: preamble creeping back, unrequested code fences, sign-offs. |
| `constraint_adherence` | 30 | Exact word counts, lipograms, forbidden words, character limits. |
| `refusal_rate` | 30 | Benign prompts near a policy boundary. Most-complained-about axis, least measured. |
| `tool_call` | 30 | Right tool, right arguments, and *no* call when none is warranted. |
| `verbosity` | 16 | Length as a distribution. Never pass/fail, never part of a flip count. |

Families are tested **separately**. A single aggregate count across 166 items
dilutes a sharp 30-item move below the floor, and the site would report
"stable" while users are complaining.

## How it decides something changed

1. Each family gets its own floor from a trailing 28-day window of that model's
   own history (minimum 7 days).
2. Days that showed an excursion are **excluded from that window** - including
   unconfirmed ones. Without this, elevated days fold into "normal" and the
   detector goes blind to the change it is watching.
3. Exact two-sided binomial test per family; the six p-values are corrected
   with Benjamini - Hochberg at q = 0.05.
4. One excursion publishes as `watch`. A `changed` verdict needs two
   excursions within three days.

Measured false-alarm rate: **0.71% of model-days**. Detection lag for one
family moving 5% → 25%: **3 days**. Both are produced by a Monte Carlo in
`tests/test_all.py` that fails the build if either regresses. See
[METHODOLOGY.md](METHODOLOGY.md).

## Tamper-evidence

A public JSON file in a git repo is trustworthy only as far as the repo owner
is trusted - and the repo owner is the party with the motive to rewrite a day.

Every day's raw files are hashed, chained to the previous day, and the head is
signed with Ed25519. Rewriting any past day breaks every link after it.

```
python3 -m aliaswatch.log verify     # offline, no dependencies, no network
```

The record page also recomputes the whole chain in your browser. If you saved a
head hash weeks ago and it is not in today's chain, you can prove the record
was rewritten. See [SECURITY.md](SECURITY.md) for what this does and does not
guarantee.

## What it cannot tell you

It measures the **alias**, not the weights. Routing changes, hidden
system-prompt changes, serving quantisation and actual weight swaps all land
identically here. AliasWatch reports that the thing you call by that name
behaves differently. It never asserts a provider swapped a model, and the share
cards never say "nerfed" - a rule enforced in `card.py` and asserted in the
tests, not left to discipline.

It is **not** reproducible by re-running yesterday's model; that endpoint is
gone. It is reproducible in the way that matters: every raw response is
archived, and re-running the published graders over them returns the same
numbers on any machine, forever.

A day with >5% transport errors is recorded as a **gap**. A hole in the record
is honest; an incomplete day published as a measurement is fabricated.

## Run it with no API keys

You can exercise the entire pipeline - graders, statistics, detection, the
site, the signing chain - without a key, an install, or a network connection:

```bash
python3 -m aliaswatch.local --days 40 --clean   # simulate a record
python3 -m aliaswatch.site --local              # build the site from it
python3 -m http.server 8080 --directory dist/local
```

The simulator injects a real change partway through so you can watch the
detector find it. `--inject-family`, `--inject-rate` and `--inject-on` let you
move it around and see where detection starts to fail.

For real models at no cost, `aliaswatch run --free-tiers` lists the providers
with free API tiers. Gemini's is the most generous and needs no card. Ollama
runs open-weight models locally:

```bash
ollama serve && ollama pull qwen3:8b
python3 -m aliaswatch.runner --local --models qwen3-8b
```

**Local and mock runs write to `results-local/`, never `results/`.** They carry
`"provenance": "local"`, the site labels them with a banner, and
`aliaswatch log append` refuses to sign them. A local model has no alias that
can change underneath you, which is the entire phenomenon this project exists
to record - so local runs test the harness and measure nothing.

## Run it

```bash
aliaswatch test                 # graders, statistics, false-alarm simulation
aliaswatch run --dry-run        # exercise the pipeline, no API calls
aliaswatch run --models claude-sonnet
aliaswatch log keygen --write-pub
aliaswatch log append 2026-09-02
aliaswatch log verify
aliaswatch build                # static site into dist/
aliaswatch card                 # share cards
```

Every command also works as `python3 -m aliaswatch.<module>`.

`--demo` on `build` renders **synthetic** data into `dist/demo/` behind a
permanent banner. It never touches `results/`. A public log whose early days
were invented is worth nothing, so the two paths are physically separate.

## The battery is sealed

`battery/v1.json` carries a SHA-256 over its canonical serialisation. The
runner verifies it before every run and refuses to start if it was edited in
place. Changing the battery means publishing `v2.json` and dual-running for 14
days - never editing v1, which would invalidate every prior comparison.

Current seal: `5b8bb0f80228337da160b9720bd00738c64d7680f818e41faef39e0c44e1ce60`

## Security and privacy

Zero runtime dependencies. The site loads no external scripts, styles, fonts,
analytics or trackers, ships a `default-src 'none'` CSP with no
`unsafe-inline`, and renders every value through `textContent` - model output
is never parsed as HTML. Details and threat model in [SECURITY.md](SECURITY.md);
data practices in the privacy page.

## Cost

166 prompts × models × short outputs. Budget **$150/mo** and expect real spend
above the naive estimate once retries and per-provider failures are counted. A
skipped day is a hole in the product, so the budget exists to make skipping
unnecessary.

## Licence

Code MIT (`LICENSE`). Battery and record CC0 (`LICENSE-DATA`). Docs CC BY 4.0.
Model and company names are the trademarks of their owners, used only to
identify the services measured. AliasWatch is not affiliated with, endorsed by,
or sponsored by any provider. See [legal/LEGAL.md](legal/LEGAL.md).
