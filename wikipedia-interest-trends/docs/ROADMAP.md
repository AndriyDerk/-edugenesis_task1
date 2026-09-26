# Roadmap: growing the skill iteratively

The first version answers the three reference questions reliably with a cheap model. It is built
so that each next step is an increment, not a rewrite: a stable `results.json` schema between
data work and presentation, a single analysis entry point (`analysis.run`), and an eval harness
that shows whether a change helped.

## How every iteration is run

1. **Collect real questions.** Add each new request type (and every failure seen in use) to
   `evals/scenarios.json` with deterministic checks: right command, right languages, verified
   numbers, required caveats.
2. **Measure before changing.** Run `evals/agent_eval.py` on the cheapest target model (free
   OpenRouter models, Claude Haiku) against the fake world (`--fake`, deterministic) and against
   live data. Keep the summary table in `evals/runs/`.
3. **Fix at the lowest layer that removes the failure.** If the model misreads output, change the
   output (clearer wording, precomputed sentence) before changing SKILL.md; if it picks wrong
   arguments, add a recipe to SKILL.md; if numbers are wrong, fix code and add a unit test with a
   known answer.
4. **Guard.** Unit tests for the new logic, an e2e test on the fake server with a planted ground
   truth, and a live smoke test (`WIKITRENDS_LIVE=1`) for new API shapes.
5. **Re-run evals.** Ship only if pass-rate and token cost do not regress.

## Iteration 2: deeper answers for the same questions (small, high value)

| Feature | Why | How |
|---|---|---|
| Topic suggestions | Users under-specify topics ("interest in learning English") | `suggest` command: Wikidata "facet of" / "subclass of" / "see also" links and search hits, returned as candidate basket items with their size in the target languages. |
| Content-gap signal | A missing or stub article in a language is itself a localisation opportunity | Page length/quality via `prop=info|pageassessments`, sitelink presence matrix. |
| Seasonality profile | "When should we launch the course?" | Average month-of-year index from 3+ years, peaks per language. |
| Change-point view | "When did it start growing?" | PELT/binary segmentation on log monthly views; report the break month with CI. |
| Automated-traffic share | Stronger bot diagnostics | Fetch `agent=automated` for main titles; flag articles where it is large or rising. |
| Reader-country weighting | Language != market | Use top-by-country ranks (and population data) to express reach per country. |
| Diff between runs | Follow-ups like "what changed since last month?" | `compare <old> <new>` over two `results.json` files. |
| `draft` command | Evals show small models still pad "which audience next" answers with invented market reasons | Generate the recommendation paragraph (order, ties, data-derived reasons, validation step) in the user's language; the agent only edits it. |

## Iteration 3: more complex research

* **Topic families instead of single articles.** Expand a topic to all Wikidata items of a class
  (SPARQL on query.wikidata.org, for example all programming languages) or to a category tree,
  then analyse hundreds of articles per language and aggregate.
* **Macro-topic discovery.** Classify articles with Wikimedia's article-topic model (Lift Wing
  `outlink-topic-model`) and answer "which subject areas grow fastest in Ukrainian Wikipedia?"
  without the user naming topics.
* **Traffic sources.** Monthly clickstream dumps (en, de, fr, es, ru, ja, it, pl, pt, zh, fa, ...)
  show whether readers arrive from search, from other articles or directly. This helps
  separate search-driven demand from browsing.
* **Better statistics for many small series.** Empirical-Bayes shrinkage of growth rates across
  languages or topics, a block bootstrap for autocorrelation, false-discovery-rate control when
  scanning hundreds of topics, and short-term forecasts with prediction intervals.
* **Cross-source triangulation.** Plug-in sources behind the same `results.json` cells (search
  keyword volumes, app-store keyword data, Google Trends exports that the user provides), and
  flag agreement or disagreement.

## Iteration 4: larger data volumes

| Scale | Approach |
|---|---|
| < 1k series | Current per-article API + SQLite range cache (about 2.5 req/s, polite). |
| 1k-100k series | Request planner (estimate the calls, confirm above a budget), resumable job queue, and optional authenticated API access for higher limits. |
| Whole wikis / years | Switch the source to the bulk *pageview complete* dumps (dumps.wikimedia.org/other/pageview_complete, daily/monthly files). Stream-parse and filter to the needed projects, then store as Parquet partitioned by project and month, queried with DuckDB. Precompute monthly article x project tables once, then run every question against them locally. |
| Continuous monitoring | A scheduled job appends new days, recomputes trends for watchlists, and alerts on change-points. |

The analysis layer already works on monthly arrays per cell, so these are new *data providers*
behind `wiki.fetch_series`; metrics, confidence, ranking and reports do not change.

## Agent integration

* **MCP server** exposing `resolve`, `analyze`, `rank`, `report` as typed tools with JSON I/O,
  so agents without a shell can use the skill, and so outputs arrive as structured data.
* **Token budget.** The summary is about 40 lines by design. For very large studies, add
  `--top N` and paging so a small model never has to read hundreds of rows.
* **Memory.** `history.jsonl` already lists previous runs; the next step is a `recall` command that
  returns the last results for a topic so follow-ups can refer to "the previous analysis".

## Quality gates to add in CI

* `pytest` (unit + fake e2e), `agentskills validate`, and a lint step on every change.
* Nightly: agent evals on 2-3 cheap models (fake data), weekly: live smoke tests and one live eval.
* A regression budget: an eval pass-rate drop or a token-cost increase above 15 % fails the build.
