# Setup - from this folder to a running project

Order matters: the name has to be claimed before anything is pushed publicly.

## 0. Where this should live

**Ubuntu under WSL is the right place.** Reasons that actually matter here:
the daily job runs on `ubuntu-latest` in GitHub Actions, so developing on the
same OS removes an entire class of "works on my machine" differences - 
line endings, path casing, and `python3` vs `python` in particular. Cursor
connects to WSL over the Remote-WSL extension and behaves normally.

Put the repo on the **Linux filesystem**, not under `/mnt/c/`:

```
mkdir -p ~/projects && cd ~/projects
# copy this folder in as ~/projects/aliaswatch
```

Files under `/mnt/c/` are served through a translation layer; git and Python
both get noticeably slower, and file-watching is unreliable. `~/projects` is
native ext4 and avoids all of it.

## 1. Claim the name

Checked on 2 September 2026:

| Registry | `aliaswatch` |
|---|---|
| npm | free |
| PyPI | free |
| crates.io | free |
| GitHub org | free |
| aliaswatch.dev | no DNS record |
| aliaswatch.com | **taken** (parked) |

Claim in this order - registry names are the ones that get sniped:

```bash
# npm (reserves the name immediately)
npm login
npm publish --access public --dry-run   # check the file list first
npm publish --access public

# PyPI
python3 -m pip install --user build twine
python3 -m build
python3 -m twine upload dist/*
```

Then the GitHub org `aliaswatch`, then `aliaswatch.dev`.

**Publishing a v0.1.0 placeholder is a real decision, not a formality.** It
reserves the name but also means the first thing anyone installing it gets is
an unfinished tool. Ship it with the README as-is - the README states the kill
test and the limitations on its first screen, which is an honest thing to have
published.

## 2. Generate the signing key

```bash
python3 -m aliaswatch.log keygen --write-pub
```

This prints a seed and writes `signing-key.pub`. Commit the **public key**.
Put the seed in the GitHub Actions secret `ALIASWATCH_SIGNING_SEED`. Never
commit it, never paste it into a chat, never echo it in a shell that logs.

## 2a. Before you pay for anything

Nothing here requires a paid key to develop against. Prove the pipeline works
on your own machine first:

```bash
python3 tests/test_all.py                        # 70 tests, no network
python3 -m aliaswatch.local --days 40 --clean    # simulate a record
python3 -m aliaswatch.site --local
python3 -m http.server 8080 --directory dist/local
```

When you do want real measurements, start with the free tiers
(`python3 -m aliaswatch.runner --free-tiers`). Gemini's needs no card. A
single-provider index is still a real index - it is better to launch measuring
one model honestly than to wait until you can afford three.

## 3. Repository secrets

| Secret | Purpose |
|---|---|
| `ALIASWATCH_SIGNING_SEED` | signs the daily log head |
| `ANTHROPIC_API_KEY` | provider access |
| `OPENAI_API_KEY` | provider access |
| `GEMINI_API_KEY` | provider access |

## 4. Repository settings

- Branch protection on `main`: require PR review, require the `ci` check.
- Actions → Workflow permissions → read-only default.
- Enable private vulnerability reporting.
- Enable Dependabot (config is already committed).

## 5. Deploy the site

Cloudflare Pages, build output directory `dist`, build command
`python3 -m aliaswatch.site`. `_headers` is picked up automatically and carries
the CSP, HSTS and the rest. Verify after the first deploy:

```bash
curl -sI https://aliaswatch.dev | grep -iE 'content-security|strict-transport|x-content-type|permissions-policy'
```

## 6. Before the first public run

**Read the terms of service of every provider you intend to measure**, looking
specifically for clauses on benchmarking, comparative publication, and
publishing outputs. Where a provider's terms prohibit publishing comparative
results, remove that provider from the public index rather than measure it in
violation. This is a launch blocker (`legal/LEGAL.md` §5), not a nicety, and it
is the one item in this whole project that no amount of engineering resolves.

## 7. First fourteen days

The site cannot say anything until each model has at least seven days of
baseline. Run privately, publish nothing, and let the floors establish. The
first public page should already have history on it - an empty instrument is
not a launch.

## Daily commands

```bash
aliaswatch test     # before touching graders or statistics
aliaswatch run      # the day's measurement
aliaswatch log append $(date -u +%Y-%m-%d)
aliaswatch log verify
aliaswatch build
```
