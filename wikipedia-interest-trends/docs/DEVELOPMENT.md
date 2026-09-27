# Development notes: design, verification, eval results

## Architecture

```
SKILL.md ──(agent reads)──► scripts/wt.py ──► wikitrends.cli
                                               │
           resolve.py  topic -> Wikidata item -> article per language (+ redirects)
           wiki.py     Analytics API / Action API / Wikidata, via net.py (rate limit, retries)
           cache.py    SQLite: per-series covered date ranges + TTL metadata
           series.py   densify, spike detection + classification, artefact detection
           stats.py    Mann-Kendall, seasonal Kendall, Sen slopes, sign test, bootstrap (stdlib)
           analysis.py metrics, confidence, comparisons, ranking  ─► results.json (schema wikitrends/1)
                                               │
           findings.py / i18n.py   data-driven sentences in en/uk (single source of wording)
           render.py   console summary for the agent, summary.md, monthly.csv
           charts.py   trend / growth / opportunity PNGs (matplotlib)
           report.py   one-page PDF (reportlab) + number checker for agent-written text
```

`results.json` is the contract between the data half and the presentation half. `report`,
`rank` and the charts only read it, so follow-ups ("in Ukrainian", "other weights") never refetch.

## Key design decisions

| Decision | Why |
|---|---|
| The CLI computes everything and prints *sentences*, not just numbers | Small models misread tables and do arithmetic badly. `Findings (quote these...)` gives them text they can copy. The eval rounds below show this is what made Haiku reliable. |
| One command answers most questions (`analyze ... --pdf`) | Fewer steps give fewer chances to go wrong and cost fewer tokens: Haiku needed 4-6 tool calls per question. |
| Wikidata sitelinks for cross-language mapping | Translated titles are the classic failure: the tool never guesses titles. |
| Last-12 vs previous-12 months, paired by calendar month | Removes seasonality without a model; easy to explain to founders. |
| Growth also relative to the whole language edition | Most Wikipedias are shrinking (AI answers, 2025 bot reclassification). Without this, "interest fell 5 %" can mean "the topic gained share". |
| Explainable rule-based confidence with hard caps | A founder can see *why* a trend is weak; caps stop consistent-looking noise on tiny articles from getting HIGH. |
| Fixed-scale ranking + preset sensitivity + tie detection | Scores are comparable between runs; "robust" and "practically tied" are stated, not left to the model. |
| Number checker in `report` and in the eval graders | Catches invented or mis-copied figures before a PDF is shared. |
| Stdlib core, deps only for charts/PDF, hash-pinned lock, private install dir | Reproducible, works where pip is restricted, never touches the system Python. |
| Polite client (User-Agent with contact URL, 2.5 req/s, Retry-After) | Wikimedia's 2026 limits throttle unidentified clients to a few requests per minute. |
| Deterministic outputs (seeded bootstrap, `WIKITRENDS_TODAY`) | Tests and evals are reproducible; two runs give identical PDFs. |

## How the AI-written code was verified

The skill was written with an AI coding agent (Claude Code). Nothing was accepted on the
strength of looking plausible; every layer has an independent check:

1. **Statistics against an independent implementation.** Mann-Kendall, seasonal Kendall and
   (seasonal) Sen slopes are compared with `pymannkendall` on random series with and without ties
   (`tests/test_stats.py`). Closed-form cases: exact sign-test p-values, a series growing exactly
   20 %/yr recovers 20 %.
2. **Synthetic world with planted ground truth.** `tests/fake_wikimedia.py` serves the real JSON
   shapes over HTTP with known trends (pl +45 %/yr, cs +3 %), a desktop-only bot burst, a news spike,
   an article created mid-window, an ambiguous title, missing articles. E2E tests assert the tool
   recovers the truth (`tests/test_e2e.py`).
3. **Visual review of rendered PDFs.** Each layout change was rasterised (PyMuPDF) and inspected.
   That surfaced overlapping axis labels, a truncated chart title and a legend with the wrong colour.
4. **Spec validation.** `agentskills validate` (skills-ref reference validator).
5. **Agent-level evals with a cheap model**, graded automatically (see below) *and* read by a person.
   Manual reading found problems the first graders missed, and those checks were added to the graders.
6. **Live smoke tests** (`tests/test_live.py`, `WIKITRENDS_LIVE=1`) pin the production API shapes.
   Run against the real APIs on 2026-09-27: the response shapes match the fake server. The one
   failing assertion was a wrong assumption in the test (Polish Wikipedia has no
   intermittent-fasting article) and was corrected.

### Bugs found this way (and fixed)

| Found by | Problem | Fix |
|---|---|---|
| ground-truth e2e | Monthly wiki totals were requested up to the 1st of the last month, so the last month was undercounted and "vs wiki" growth inflated (+69 % instead of +56 %) | Monthly ranges end on the month's last day. |
| ground-truth e2e | An article created mid-window showed "+411 %, uk grew fastest" | `new-article` direction, excluded from comparisons and the growth score; per-item check for baskets (`new_item`). |
| unit test on noise | Pure noise at 4 views/day produced a "significant" decline graded MEDIUM | Hard caps: under 10 views/day can never exceed LOW. |
| unit test | Level-shift month reported one month early (tie in block medians) | Tie-break by the sharpest single-month step. |
| review | Min-max ranking turned two options into 100 vs 0 | Fixed absolute scales. |
| unit test | "19 pp" matched a percentage elsewhere | Separate pools for percentages and percentage points. |
| eval (Haiku) | Parallel first runs raced while installing dependencies | Per-process temp dir + atomic rename. |
| eval (Haiku) | Ranking #2-#4 were within 2.4 points but read as a clear order; the model invented reasons | Tie detection + "Practically tied" finding; SKILL.md rule against invented causes. |
| eval (Haiku) | Ranking sentence was the 10th finding, cut from the PDF | Decision-relevant findings first. |
| eval (Haiku) | Ambiguous "Mercury" silently analysed as the planet | `!! CHECK TOPIC` line at the top of the output. |
| eval (Haiku) | "vs wiki +8.8 %" read as "Wikipedia fell 8.8 %" | Whole-wiki YoY column + an explicit normalisation sentence. |
| eval (Haiku) | Answers skipped the willingness-to-pay caveat or file paths | Mandatory answer skeleton in SKILL.md + a checklist at the end of the CLI output. |
| eval (Haiku) | `--basket NAME ITEM...`: the model omitted the name, so its first *article* silently became the label and was not analysed | Every `--basket` argument is an article; optional `name=...`; regression test. |
| eval (Haiku) | Translating English findings into Ukrainian produced wrong phrases ("the topic occupies +56 % of traffic") | Findings are printed in the report language (`--lang uk`), so the model copies them verbatim. |
| eval (Haiku) | Recommendations padded with invented reasons ("less competitive / less saturated market") | Data-derived "Why, from the data" line per option; explicit examples in the rule; `hedged_causes` grader. |
| eval (Haiku) | Languages without an article recommended *because* they could not be measured | SKILL.md: unmeasurable is neither zero interest nor a reason to recommend. |
| eval (Haiku) | A heading drifted into Russian inside a Ukrainian answer | `answer_language` grader counts Russian-only letters and words. |
| eval (Haiku) | `rank` follow-up did not show near-ties (uk 76.1 vs es 74.1) | Tie groups anchored on their best member, shown by `analyze` and `rank`. |
| grader review | "ambig" matched inside a *file path*; "90% CI" counted as a claim | Paths stripped before text checks; CI-level detection on both sides of the number. |
| live API | Wikimedia rate-limits shared cloud IPs (HTTP 429, Retry-After ~50 s); 4 threads each hit it separately | Retry-After pauses all threads and slows the pace adaptively; progress message while waiting; optional `WIKITRENDS_API_TOKEN`. |
| live API | Many series show a sudden drop around 2025-05 (Wikimedia's bot-detection update), which biases every YoY comparison across it | Specific `bot_update_2025` caveat and a window-level note pointing to the share-of-wiki metric. |
| live API | `top-by-country` omits some countries for privacy (e.g. rank 1 for tr.wikipedia), so "readers mostly in US, DE" was misleading | Rank gaps are detected and stated. |
| live API | Polish Wikipedia has no article on intermittent fasting (reference question 1) | Handled as designed: "cannot be measured", not zero interest. |

## Eval results (Claude Haiku 4.5, fake world)

The development sandbox could not reach Wikimedia or OpenRouter, so the full scenario was run
with **Claude Haiku 4.5** as a Claude Code subagent (Bash + Read tools) against the fake
Wikimedia server, graded with `evals/grade_workspace.py`: 25 runs over 7 improvement rounds,
including two-turn follow-ups. Summary: tool use and number fidelity were reliable in every run.
The fixed questions have been clean since round 3. The open "which audiences next" question still
occasionally gets an invented market reason or a number copied from another row; the CLI and the
`report` guards catch the latter. Details: `evals/results/haiku-4.5.md`. The OpenRouter harness (`evals/agent_eval.py`) was validated end to end with a
scripted model (`tests/test_eval_harness.py`); run it with a free key as described in `evals/README.md`.

## Running everything

```
uv sync
uv run pytest                                   # unit + e2e + harness (live tests skipped)
WIKITRENDS_LIVE=1 uv run pytest tests/test_live.py
cd .. && uv run --project wikipedia-interest-trends agentskills validate wikipedia-interest-trends
python evals/agent_eval.py --model <id> --fake  # needs OPENROUTER_API_KEY
```
