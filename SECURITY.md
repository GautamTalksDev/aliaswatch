# Security

## Reporting

Report privately to the address in `.well-known/security.txt`, or via GitHub
private vulnerability reporting. Please do not open a public issue for an
unpatched vulnerability.

Acknowledgement within 72 hours. Coordinated disclosure: 90 days, or sooner once
a fix ships. There is no bounty; there is credit in the advisory if you want it.

---

## Threat model

AliasWatch is a static site plus a scheduled job. It has no users, no accounts,
no database, no server-side code and no user input reaching a backend. That
removes most of the usual attack surface by construction. What remains is worth
naming precisely.

### T1 — Falsifying the public record (the real threat)

The record's entire value is that it is believed. The highest-value attack is
altering history: making a past day show a change that did not happen, or hiding
one that did. **The operator is the most capable attacker here**, which is why
the mitigation cannot be "trust the operator."

Mitigations:
- Every day's raw result files are hashed, chained to the previous day, and the
  head is signed with Ed25519. Rewriting any day breaks every subsequent link.
- The public key is committed to the repository; verification runs fully offline
  (`python3 -m aliaswatch.log verify`) and in the browser on `/verify.html`.
- `results/` is append-only by policy; corrections are new entries, never edits.
- Signed heads should be published externally — a signed git tag, a post, an
  archive.org snapshot — so a fork of the chain is provable by any third party
  holding an older head. **A signature alone does not stop the key holder from
  re-signing a rewritten chain; external publication of heads is what closes
  that gap, and it is an operational duty, not a code feature.**
- The battery is sealed with a SHA-256 the runner verifies before every run,
  so the questions cannot be quietly changed to alter the result.

### T2 — Compromise of the signing key or CI

The signing seed lives only in a GitHub Actions secret. Consequences of theft:
an attacker can sign a forged chain.

Mitigations:
- The seed is never committed, never printed in logs, and never passed on a
  command line (environment only).
- Workflow permissions are least-privilege (`contents: write` only on the job
  that needs it); no `pull_request_target`; no untrusted-input workflow triggers.
- All actions are pinned by commit SHA, not by tag, so a retagged action cannot
  silently change what runs.
- Key rotation procedure is documented below and the public key file is
  versioned, so a rotation is visible in history.
- Branch protection with required review on `main`, so a single compromised
  token cannot rewrite the record unobserved.

### T3 — Supply-chain compromise

Mitigations:
- **Zero runtime third-party dependencies.** The harness is standard library
  only; the site ships no external scripts, fonts, styles, analytics or CDN
  assets. There is nothing to poison.
- `cryptography` is optional and outside the verification path.
- Dependabot is enabled for GitHub Actions only, because that is the only
  dependency surface that exists.

### T4 — Malicious content in model outputs

Archived model outputs are attacker-influenceable in principle: a provider (or a
prompt-injection path) could return content designed to attack readers of the
site, e.g. HTML or script in a response body.

Mitigations:
- The site renders **all** data through `textContent`, never `innerHTML`. There
  is no HTML parsing of any model output anywhere in the front end.
- The CSP forbids inline script entirely (`script-src 'self'`, no
  `unsafe-inline`, no `unsafe-eval`), so injected markup cannot execute even if
  a rendering bug were introduced.
- `data.json` contains only numbers, dates, family names and status strings —
  raw response text is never loaded into the page, only linked to on GitHub,
  which renders it as inert plain text.
- Result files are written as JSON with standard escaping; no template
  interpolation of model text into HTML occurs at any point.

### T5 — Provider-side manipulation of the measurement

A provider could in principle detect AliasWatch's traffic and serve it a
stable configuration while other users get something else.

This is **not fully mitigable** and is stated plainly on the methodology page.
Partial mitigations: the battery is public (so any special-casing is itself
discoverable by third parties reproducing it), and independent reproduction is
explicitly invited. This is an inherent limit of black-box measurement, not a
bug to be closed.

### T6 — Denial of service / cost exhaustion

The site is static behind a CDN. The runner is the cost surface: a bug causing
retry storms could burn the API budget.

Mitigations: bounded retries (4) with exponential backoff, per-run item cap
fixed by the sealed battery, a single daily scheduled run with a concurrency
group preventing overlap, and a hard failure that opens an issue rather than
silently retrying.

### Out of scope

Physical access to the operator's machine; compromise of GitHub itself;
compromise of a measured provider's infrastructure; nation-state adversaries.

---

## OWASP alignment

Against the **OWASP Top 10 (2021)** — noting honestly that most categories are
inapplicable to a static site with no backend, rather than claiming defences
that are not needed:

| | Category | Status |
|---|---|---|
| A01 | Broken access control | N/A — no auth, no accounts, no protected resources. Everything published is intended to be public. |
| A02 | Cryptographic failures | Ed25519 for log signing; SHA-256 for chaining and sealing. No secrets in transit or at rest on the site. HSTS with preload; `upgrade-insecure-requests`. No custom crypto except a standards-conformant RFC 8032 implementation, cross-validated in tests against `cryptography`. |
| A03 | Injection | No SQL, no shell interpolation, no server-side templating of untrusted data. Front end uses `textContent` exclusively. CSP forbids inline and `eval`. |
| A04 | Insecure design | Threat model above; the primary risk (record falsification) is addressed structurally by hash-chaining rather than by policy. |
| A05 | Security misconfiguration | Full header set in `web/_headers` plus a meta CSP fallback; `nosniff`, `DENY` framing, COOP/COEP/CORP, a deny-by-default Permissions-Policy, no directory listing, no source maps published. |
| A06 | Vulnerable components | No runtime dependencies. Dependabot on Actions. Actions pinned by SHA. |
| A07 | Auth failures | N/A — no authentication exists. |
| A08 | Software/data integrity failures | The central control: sealed battery, hash-chained signed log, offline and in-browser verification, append-only policy, SHA-pinned CI. |
| A09 | Logging & monitoring failures | CI failure opens a GitHub issue automatically; a failed day is recorded as a visible gap rather than silently skipped. No visitor logging by design. |
| A10 | SSRF | The runner fetches only a fixed, hard-coded list of provider endpoints. No URL is ever taken from input, configuration or model output. |

**OWASP ASVS v5 Level 1** is the target for the web surface. The applicable
controls — V1 (encoding/injection: `textContent` only), V3 (session: none
exists), V6 (crypto: standard primitives), V12 (secure comms: HSTS preload),
V13 (config: full header set, no secrets client-side) — are met. Controls
concerning authentication, session management, access control and file upload
are not applicable because none of those features exist.

---

## Key management

Generate: `python3 -m aliaswatch.log keygen --write-pub`

- The **seed** goes into the GitHub Actions secret `ALIASWATCH_SIGNING_SEED`.
  Never commit it, never echo it, never pass it as a CLI argument.
- The **public key** (`signing-key.pub`) is committed.

**Rotation.** Rotating breaks continuity unless it is announced. Procedure:
publish the final head signed under the old key, commit the new public key with
the old one retained in `signing-key.pub.old`, and record the rotation date in
`VERIFYING.md`. Verifiers must then check pre-rotation entries against the old
key. Rotate immediately on any suspicion of compromise, and say so publicly —
a silent rotation is indistinguishable from an attack.

---

## Operational rules

1. `results/` is append-only. Corrections are new entries with a note, never
   edits to a past day.
2. Publish signed heads externally on a regular cadence.
3. Never merge a change to `graders.py` or `stats.py` without re-running
   `tests/test_all.py`; the daily job runs it before any provider call and
   skips the day rather than recording with an undescribed detector.
4. Never add a runtime dependency to the site. If one becomes unavoidable,
   vendor it, pin it by hash, and record it in `NOTICE`.
5. Never render model output as HTML.
