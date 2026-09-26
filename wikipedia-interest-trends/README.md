# wikipedia-interest-trends

An [Agent Skill](https://agentskills.io/specification) that lets an AI agent, including a small,
cheap one such as Claude Haiku 4.5, answer product questions with Wikipedia pageview data:

* *"Compare the growth of interest in intermittent fasting in Polish and Czech Wikipedia over two years."*
* *"We are thinking about an astronomy course. Is interest growing in Ukrainian Wikipedia, and how far can we trust it?"*
* *"Compare interest in learning English across our language editions: which audiences should we research next, and why?"*

The agent runs one command; the bundled CLI does the data work and statistics and returns a
compact, pre-interpreted summary, PNG charts, a Markdown summary and a one-page PDF (English or
Ukrainian).

```
python3 scripts/wt.py analyze --topic "Intermittent fasting" --langs pl,cs --lang uk --pdf
```

## What it does

| Step | Detail |
|---|---|
| Topic -> articles | Free text / Wikidata id / `lang:Title` -> Wikidata item -> the same article in every language (never machine-translated titles). Baskets of several articles per topic. Redirects are added (renamed articles keep their history). Ambiguity and missing articles are reported. |
| Data | Wikimedia Analytics API (human traffic, daily), whole-wiki monthly totals, desktop split, reader countries. Polite client (User-Agent policy, 2.5 req/s, retries). SQLite range cache: follow-ups only fetch what is missing. |
| Cleaning | Rolling-median spike detection; spikes labelled bot-like (desktop surge) or event-like; detection of new articles, dying articles, level shifts, new basket items. |
| Statistics | Last 12 vs previous 12 months (seasonality-safe) with a paired bootstrap CI; sign test; seasonal Mann-Kendall and seasonal Sen slope (verified against `pymannkendall`); growth relative to the whole language edition; CAGR for long windows; platform agreement. |
| Judgement | Explainable 0-100 confidence score with reasons and hard caps; pairwise comparisons with CIs; opportunity ranking on fixed scales with user-adjustable weights, sensitivity across 4 presets and near-tie detection. |
| Output | ~40-line summary with "Findings (quote these)", `results.json`, CSV, charts, `summary.md`, one-page PDF (A4, guaranteed to fit), and a number checker that flags figures in agent-written text that do not match the analysis. |

## Layout

```
SKILL.md                 instructions the agent reads (about 2k tokens)
scripts/wt.py            entry point; bootstraps pinned deps on first use
scripts/wikitrends/      the package (core is stdlib only)
references/              methodology, interpretation guide, CLI reference (loaded on demand)
assets/                  language and country names
requirements.lock        hash-pinned runtime deps (exported from uv.lock)
pyproject.toml, uv.lock  dev environment (pytest, pypdf, pymannkendall, skills-ref)
tests/                   unit tests, fake Wikimedia server, e2e tests, live smoke tests
evals/                   agent-level evaluation: scenarios, graders, OpenRouter harness
docs/                    development notes and roadmap
```

## Install / reproduce

Runtime: Python 3.10+. Nothing to install manually: the first `analyze`/`report` (or
`python3 scripts/wt.py setup`) installs matplotlib + reportlab from `requirements.lock` with
`--require-hashes`, using `uv` if present or `pip`, into `~/.cache/wikitrends/site-<py>-<lockhash>/`.
It never touches the system Python. Without them, the text analysis still works.

Development:

```
uv sync                                    # dev environment from uv.lock
uv run pytest                              # 80+ tests; no network needed
WIKITRENDS_LIVE=1 uv run pytest tests/test_live.py   # against the real APIs
uv run agentskills validate .              # spec check (run from the parent folder)
```

Agent evals with free OpenRouter models (see `evals/README.md`):

```
export OPENROUTER_API_KEY=...
python evals/agent_eval.py --list-models
python evals/agent_eval.py --model <free-model-id> --fake
```

Network hosts needed at runtime: `wikimedia.org`, `*.wikipedia.org`, `www.wikidata.org`
(and `pypi.org` once for dependencies).

See `docs/DEVELOPMENT.md` for design decisions and verification, and `docs/ROADMAP.md` for the plan
to handle more complex research and larger data volumes.
