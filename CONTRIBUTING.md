# Contributing

The most valuable contribution is an independent reproduction. Run the sealed
battery yourself and tell us when your numbers disagree with ours.

## Rules that are not negotiable

1. **No LLM judges.** Every grader is exact match, regex, schema validation, or
   numeric tolerance. A grading step that itself drifts makes the record
   meaningless.
2. **Never edit a sealed battery.** Publish `v2.json` and dual-run for 14 days.
   Editing v1 invalidates every prior comparison.
3. **Never edit `results/`.** The record is append-only. Corrections are new
   entries with a note.
4. **No runtime dependencies.** Not in the harness, not in the site. If one
   becomes unavoidable, vendor it, pin it, and record it in `NOTICE`.
5. **Never render model output as HTML.** `textContent` only.
6. **No editorialising in published copy.** State what moved; never
   characterise a provider's product. Enforced by `card.py` and the tests.

## Changing detection

Any change to `graders.py` or `stats.py` must be accompanied by the re-measured
false-alarm rate and detection lag from `tests/test_all.py`, and both numbers
must be updated in `METHODOLOGY.md` in the same PR. If a change improves one at
the cost of the other, say so explicitly in the PR description — that trade-off
is the interesting part and it belongs in the public methodology, not in a
commit message.

## Adding a family

New families need at least 30 items so the per-family binomial test has
comparable power, a grader that is deterministic over archived text, and an
entry in the methodology table. Add it as a new battery version.

## Adding a provider

Confirm three things first: that its terms permit publishing comparative
results, that output rights permit republishing the archive, and that the
adapter is deterministic at temperature 0. Then add it to `runner.MODELS`.
