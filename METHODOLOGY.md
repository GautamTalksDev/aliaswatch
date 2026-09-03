# Methodology

Written before the first flag was ever published. If AliasWatch's numbers are going
to be cited, this page has to survive being read adversarially by a provider's
communications team.

## What is measured

A sealed battery of 166 prompts across six families, run once daily against each
model alias at temperature 0 with seeds pinned where the provider supports them.

The battery is published with a SHA-256 over its canonical (RFC 8785-style)
serialisation. The runner verifies the seal on every run and refuses to start if
it fails. A revision means publishing `v2.json` and running both batteries in
parallel for fourteen days - never editing `v1`, which would invalidate every
comparison against every prior day.

## No model judges another model

Every grader is exact match, regex, JSON-schema validation, or a numeric
tolerance. The refusal detector is an explicit published list of refusal phrases,
stored inside the sealed battery artifact so it cannot be quietly tuned to make a
provider look better or worse.

A grading step that itself drifts would make the entire record meaningless. This
is the single most important design constraint and it is not negotiable for a
convenience gain.

Two details worth stating because they affect the numbers:

- **Word counting.** Hyphenated compounds count as one word. "Exactly five words"
  is only meaningful with a stated tokenizer.
- **Hedge versus refusal.** A refusal phrase inside a long substantive answer
  ("I can't give medical advice, but the mechanism is…") is recorded as a hedge,
  not a decline. Only short responses, or refusal phrases in the opening 320
  characters of a response under 90 words, count as refusals.

## The noise floor

The same prompt at temperature 0 does not return the same answer twice. That
noise is measured per model per family, not assumed.

1. Each family's floor comes from a trailing 28-day window of that model's own
   history, with a minimum of 7 days.
2. **Days that showed an excursion are excluded from the window, including
   unconfirmed ones.** Without this, elevated days fold into the definition of
   normal, the floor rises to meet the change, and the detector goes blind to the
   very shift it is watching. This was a real bug caught in simulation before
   launch: with contaminated baselines, a 5% → 25% refusal shift went undetected
   for thirty days.
3. Exact two-sided binomial test per family. Two-sided because a family can drift
   *better*, and a sudden improvement is just as much a change worth recording.
4. Six p-values corrected with Benjamini - Hochberg at q = 0.05. Testing six
   families daily is six chances a day to be wrong; uncorrected, AliasWatch would
   flag something roughly every three days by accident alone.

### Why families are tested separately

Real regressions are concentrated: refusals move while tool calls do not. Pooling
all 166 items into one flip count dilutes a sharp 30-item move below the floor,
and the site reports "stable" while users are complaining. The worked example:
one family moving 5% → 25% shifts the aggregate from 18/150 to 24/150 - a 4%
change in the total, well inside ordinary variation. Per-family, it is
overwhelming.

## Confirmation

One excursion publishes as `watch`, never as a change. A `changed` verdict
requires two excursions within a three-day window. Providers have transient
incidents; a public record that cries wolf on those is worth nothing.

Confirmation is 2-of-3 rather than 2-consecutive because with n = 30 per family,
a genuine shift does not clear the bar every single day.

## How often AliasWatch is wrong

Measured by Monte Carlo under the null hypothesis that nothing ever changes - 
every item an independent Bernoulli draw at its family's true rate, across 6,780
model-days.

| Quantity | Rate |
|---|---:|
| False `changed` verdicts | **0.71%** of model-days |
| False `watch` verdicts | 2.49% of model-days |
| Detection lag, one family 5% → 25% | **3 days** |

At three models that is roughly one false alarm every seven weeks across the
whole site.

**The trade, stated plainly.** An earlier rule requiring two strictly consecutive
excursions scored a far better false-alarm rate of 0.015% - and failed to detect
the same 5% → 25% shift at all within thirty days. Sensitivity was bought with
specificity, deliberately. Both numbers are published because the trade is the
interesting part, and because a detector that only reports its best-looking
statistic is not a detector anyone should cite.

These figures are re-measured whenever detection code changes, by a test that
fails the build if either regresses. The daily CI job runs that test *before* any
provider call: if detection has regressed, the day is skipped rather than
recorded with a detector that can no longer be described honestly.

## What AliasWatch cannot tell you

**It measures the alias, not the weights.** A change in routing, in a hidden
system prompt, in serving quantisation, or in the weights themselves all land
identically here. AliasWatch reports that the thing you call by that name behaves
differently. It does not and cannot say why, and it never asserts that a provider
swapped a model.

**It is not reproducible by re-running the model.** Yesterday's endpoint is gone.
Reproducibility here means: every raw response is archived, and re-running the
published graders over those archives returns these exact numbers on any machine,
at any future date. That is the only reproducibility claim AliasWatch makes, and it
is the one that matters for an audit.

**Gaps are gaps.** A day with more than 5% transport errors is recorded as a gap,
not as data. A hole in the record is honest; an incomplete day published as a
measurement is a fabricated step in a public log.

**Small n.** Thirty items per family bounds the resolution. A shift smaller than
roughly 10 percentage points within a single family will not be reliably detected.
AliasWatch is an instrument for step changes, not for slow gradual erosion. Detecting
gradual drift would need either a larger battery or explicit trend testing across
weeks, and neither is claimed today.

## Corrections

Errors in the record are corrected in place with the correction logged here and in
the commit history, never silently. The commit history of the public repository is
the audit trail; `results/` is never rewritten.
