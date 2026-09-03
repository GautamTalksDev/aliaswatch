# Legal, licensing and attribution

Nothing here is legal advice. It is a plain description of how this project is
licensed, what it claims, and what it deliberately does not claim. If AliasWatch
ever earns revenue or receives a legal complaint, a qualified lawyer in the
operator's jurisdiction should review this page.

---

## 1. Licensing

| Component | Licence |
|---|---|
| Source code (`aliaswatch/`, `web/`, `tests/`, `build_battery.py`) | MIT — see `LICENSE` |
| The prompt battery (`battery/v1.json`) | CC0 1.0 — see `LICENSE-DATA` |
| The published record (`results/`, `log.jsonl`) | CC0 1.0 — see `LICENSE-DATA` |
| Documentation (`*.md`, site prose) | CC BY 4.0 |

The record is CC0 deliberately. A public measurement that people are asked to
cite must be free to copy, quote, re-host and build on without asking. Placing
any restriction on it would defeat its only purpose.

### Third-party code

The runtime has **no third-party dependencies**. The harness uses only the
Python standard library. The website ships no external scripts, stylesheets,
fonts, analytics or trackers.

`cryptography` is an optional accelerator for Ed25519 signing; when it is
absent, a vendored pure-Python implementation is used instead. Nothing in the
verification path requires it. `playwright` is a development-only tool for
screenshot review and is not needed to run or verify anything.

Because there are no bundled third-party components, there is no third-party
licence text to reproduce. If a dependency is ever added, its licence must be
recorded in `NOTICE` before the commit that adds it.

---

## 2. Trademarks and nominative use

AliasWatch measures commercial services. It names them because a measurement
that will not say what it measured is useless.

Model names, product names and company names are the trademarks or registered
trademarks of their respective owners. They are used here solely to identify
the services being measured — nominative fair use. Specifically:

- AliasWatch is **not affiliated with, endorsed by, sponsored by, or connected
  to** any AI provider.
- No provider's logo, wordmark, brand colour, typeface or other brand asset is
  reproduced anywhere in this project. Providers are referred to in plain text
  only.
- Share cards and pages carry a visible statement of non-affiliation.
- The project name and domain do not incorporate any provider's mark, and no
  provider's mark appears in any package name, repository name, or social
  handle used by this project.

### Our own name

"AliasWatch" was chosen after checking npm, PyPI, crates.io and GitHub for
collisions, and after rejecting an earlier working name ("Tremor") on
discovering it is a CNCF project whose trademarks are held by the Linux
Foundation. That check should be repeated before any commercial launch, and a
proper trademark search (USPTO/EUIPO/UKIPO, as applicable) should be run before
any paid tier opens.

---

## 3. What AliasWatch asserts, and what it does not

This section is the substance of the legal position, not boilerplate. The
project's exposure is almost entirely defamation-shaped: publishing that a
company's product got worse.

**AliasWatch asserts only this:** on a given date, a fixed and publicly
published set of prompts, sent to a named public API endpoint under stated
parameters, produced outputs that a fixed and publicly published set of
deterministic graders scored differently than on prior dates, by a margin
exceeding a pre-registered and publicly documented threshold.

That is a statement of measured fact, and every input to it is published so that
anyone can check it.

**AliasWatch does not assert, and must never be worded to imply:**

- that a provider replaced, downgraded, quantised, or "nerfed" a model;
- that any change was intentional, concealed, or deceptive;
- that a provider misrepresented its product;
- that a model is worse, degraded, or of lower quality;
- any explanation whatsoever of *why* a measurement moved.

**Why the distinction is load-bearing.** AliasWatch measures an *alias* — a
name pointing at a serving stack. A routing change, an infrastructure change, a
hidden system-prompt change, a serving-quantisation change and a weight change
all produce identical evidence here. Claiming to know which occurred would be an
assertion of fact the project cannot support, and it would be the sentence a
lawsuit is built on.

### Editorial rules enforced in code and review

1. Share cards never contain the words *nerfed*, *degraded*, *worse*,
   *downgraded*, or *broken*. This is stated in `aliaswatch/card.py` and is
   checked by the test suite.
2. Site copy states changes in the measured voice: "14 of 30 items in
   `refusal_rate` moved beyond the floor," never "the model got worse."
3. Any published flag links to the raw archived outputs for that day.
4. Corrections are published in place, logged, and never made silently.
5. Providers may request the raw data for any flagged day and receive it
   immediately; it is already public.

---

## 4. Terms of use (the site)

The site is provided **as is, without warranty of any kind**, express or
implied, including but not limited to warranties of merchantability, fitness for
a particular purpose, accuracy, or non-infringement. To the maximum extent
permitted by applicable law, the operator is not liable for any direct,
indirect, incidental, special, consequential or exemplary damages arising from
use of, or reliance on, this site or its data.

The measurements are a research and transparency artifact. They are **not**
advice — not procurement advice, not investment advice, not a certification, not
a benchmark of model quality, and not a service-level guarantee. Do not make
purchasing, financial, safety-critical or clinical decisions on the basis of
this record.

Statistical detection produces false positives at a measured, published rate.
That rate is on the methodology page and is not hidden.

---

## 5. Provider terms of service

AliasWatch calls provider APIs under paid or free accounts held by the operator,
in the ordinary documented manner, at low volume (roughly 166 short requests per
model per day). It does not scrape, does not circumvent rate limits, does not
attempt to extract weights or training data, does not use undocumented
endpoints, and does not evade any technical protection measure.

Provider terms change. Before launch and periodically after, the operator must
re-read the terms of every measured provider for clauses covering benchmarking,
comparative publication, and publication of outputs. Some providers have
historically restricted publishing comparative benchmarks. **Where a provider's
terms prohibit publishing comparative results, that provider must be removed
from the public index rather than measured in violation of its terms.** This is
a launch blocker, not a nicety.

Model outputs are archived and republished as evidence. Providers generally
assign output rights to the user; that assignment is what makes the archive
publishable. This must be confirmed per provider before that provider is added.

---

## 6. Privacy

AliasWatch collects nothing. See `PRIVACY.md`. In summary: no accounts, no
cookies, no analytics, no trackers, no third-party requests, no server-side
logging of visitors beyond whatever the static host records by default. The one
piece of browser storage is a colour-theme preference held in `localStorage`,
which never leaves the device.

Because no personal data is collected or processed, GDPR/UK-GDPR data-subject
obligations do not arise for site visitors. If analytics are ever added, this
page and `PRIVACY.md` must be updated *before* deployment, and a cookie/consent
mechanism added if the tooling requires one.

---

## 7. Contact

Security reports: see `SECURITY.md`.
Corrections, disputes, and takedown requests: open a public issue, or email the
address in `.well-known/security.txt`. Disputes about a specific day's numbers
are handled by publishing the dispute alongside the data, not by removing the
data.
