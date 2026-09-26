---
name: wikipedia-interest-trends
description: Research public interest in topics across Wikipedia language editions with Wikimedia pageview data. Use when someone asks whether interest in a topic is growing, wants to compare interest between languages or between topics, asks how far a trend can be trusted, needs to pick which languages/markets or course topics to prioritise (localisation, new course, content strategy), or wants charts or a short shareable PDF report. The bundled CLI maps articles across languages via Wikidata, removes bot spikes, handles seasonality, normalises by overall Wikipedia traffic, grades confidence, ranks options with adjustable criteria, caches data for cheap follow-ups, and writes reports in English or Ukrainian.
license: MIT
compatibility: Python 3.10+. Network access to wikimedia.org, *.wikipedia.org and www.wikidata.org; pypi.org once, for chart/PDF dependencies.
metadata:
  version: "1.0.0"
  entrypoint: scripts/wt.py
---

# Wikipedia interest trends

Answers product questions ("which language next?", "is interest in X growing, can we trust it?")
with Wikipedia pageviews. **The CLI does all data work and statistics. Your job: pick the right
command, check the topic mapping, and explain the tool's findings faithfully.**

Run every command as `python3 <skill-dir>/scripts/wt.py ...`, where `<skill-dir>` is the folder
containing this file (on Windows use `python`). The first `analyze` installs matplotlib and
reportlab automatically (about 1 minute); if it times out, run `python3 <skill-dir>/scripts/wt.py setup`
once, then retry.

## Step 1: map the request to one command

| The user wants... | Command (add `--lang uk` when the user writes Ukrainian) |
|---|---|
| Compare growth of a topic in languages A and B | `analyze --topic "Intermittent fasting" --langs pl,cs` |
| Know if interest grows in one language + how reliable | `analyze --topic "Astronomy" --langs uk` |
| Choose which audiences/languages to explore next | `analyze --basket "Learning English" "English language" "English as a second or foreign language" --langs de,pl,uk,es,tr,pt` |
| Choose between topics / courses in one language | `analyze --topic "Astronomy" --topic "Chemistry" --topic "Biology" --langs uk` |
| A shareable report / PDF | add `--pdf` to analyze, **or** run `report` afterwards (Step 4) |
| A longer or specific period | add `--months 36` or `--start 2023-01 --end 2025-12` |
| Re-rank with other priorities (no refetch) | `rank <result-folder> --weights growth-first` |
| Raw monthly numbers for one article | `views uk:Астрономія --months 24` |
| "What did we analyse before?" | `history` |

Rules for the arguments:

- **Topic**: give the English name (e.g. "Intermittent fasting"), a Wikidata id (`Q11412`) or an exact
  article (`uk:Астрономія`). The tool finds the same article in every language through Wikidata.
  **Never translate article titles yourself.**
- **Basket** (`--basket NAME ITEM ITEM...`): use when the interest is spread over several articles.
  Use 2-5 closely related articles about the same intent, e.g. learning English = "English language",
  "English as a second or foreign language", "IELTS", "TOEFL". Do not mix unrelated concepts.
- **Languages** are Wikipedia codes: `uk` Ukrainian, `pl` Polish, `cs` Czech, `de` German, `es` Spanish,
  `pt` Portuguese, `tr` Turkish, `fr` French, `it` Italian, `ro` Romanian, `ja` Japanese, `zh` Chinese.
  If the user asks "which audiences" without naming languages, choose 5-8 plausible candidates and say which.
- **Period**: default is the last 24 complete months. Growth always compares the latest 12 months with
  the 12 before (same calendar months, so seasonality cancels out). "Last 2 years" = default;
  "last 3 years" = `--months 36`.

## Step 2: run it and check the mapping

`analyze` prints a compact summary (about 40 lines). Before answering, check the first lines:

- `Topic "...": Q... "label" (description) via exact title | top search result`. If the chosen
  article is not what the user meant (see `other candidates`), re-run with the right `Q...` id.
  Use `resolve --topic X --langs ...` to preview mappings without downloading pageviews.
- `Articles:` shows the article used per language. `NO ARTICLE` / `missing:` means the language
  cannot be measured (fully or partly) for that topic. Say so; do not treat it as zero interest.

## Step 3: answer from the output

The output contains a table, `Comparisons`, `Ranking`, `Findings (quote these...)` and `Caveats`.
Write the answer in the user's language with exactly these parts, briefly:

1. **Verdict**: one or two sentences that answer the question (which language/topic; growing or not).
2. **Evidence**: 2-5 bullets with numbers **copied from `Findings` or the table**. Do not compute
   new numbers, ratios or averages yourself.
3. **Confidence**: the grade and its main reason. For rankings, say whether the top pick is robust
   ("same under all 4 weighting presets") and name options the output marks as tied.
4. **Next step**: one concrete way to validate (landing page, ad test, keyword volumes) and one
   sentence that pageviews show curiosity, not willingness to pay.
5. **Files**: paths to the PDF / charts / summary.md that were produced.

- Recommend options in the order of the tool's `Ranking`. If the user states other priorities,
  re-rank with `rank <folder> --weights ...` instead of reordering by hand.
- Do not invent causes (economy, migration, culture, marketing...). The data shows *what* changed,
  not *why*. If you mention a cause, label it as a hypothesis to check.

How to read the key fields:

| Field | Meaning |
|---|---|
| `YoY w/o spikes [90% CI]` | Growth of the last 12 months vs the previous 12, after removing short bursts. The range is the 90% uncertainty interval. |
| `months up` | In how many of the 12 months views were higher than a year earlier (consistency). |
| `vs wiki` | Growth relative to all traffic of that Wikipedia. Most Wikipedias are shrinking, so use this to separate topic interest from platform decline. |
| `trend` | growing / likely growing / stable / inconclusive / likely declining / declining / new-article |
| `confidence` | HIGH / MEDIUM / LOW with a 0-100 score; the reasons are printed under Caveats. |
| Ranking `score` | 0-100 on fixed scales for audience size, growth vs wiki, topic salience and data reliability. |

Hard rules:

- `new-article` means the article appeared during the period. Never present its growth as real.
- LOW confidence: say the trend is not reliable and why (low volume, spikes, artefacts).
- `stable` is a finding (no meaningful change), not a failure.
- A language is not a country. Use the `Readers of xx.wikipedia are mostly in:` line when it matters.
- If a follow-up changes the period, languages or topic, just re-run `analyze`: cached data makes it
  fast. If it only changes the ranking priorities, use `rank`.

## Step 4: shareable report (one-page PDF)

Write a 2-4 sentence summary from the findings (in the user's language) and optionally 2-4
recommendation bullets. Then run:

```
python3 <skill-dir>/scripts/wt.py report <result-folder> --lang uk \
  --title "Short title" --question "The user's question" \
  --summary "Your 2-4 sentences." --recommendation "- step one
- step two"
```

The command checks every percentage in your text against the analysis. If it prints
`NUMBER CHECK`, fix those numbers (use the exact figures from the findings) and run it again.
The PDF (A4, always one page), `report.md` and PNG charts are written into the result folder.

## When something fails

| Message | Do |
|---|---|
| `nothing found for '...'` | Use the English Wikipedia title, a `Q...` id, or `--search-lang uk` for a Ukrainian query. |
| `ambiguous ... picked ...` | Check `other candidates`; re-run with the right `Q...` id. |
| `not a Wikipedia language code` | Use codes like `uk`, `pl`, `cs` (not country codes or names). |
| `NETWORK ERROR ... blocked` | Tell the user which host must be allowed; `doctor` diagnoses connectivity. |
| `HTTP 429` | Wait a minute and retry; data already downloaded stays cached. |
| charts/PDF `skipped` | Run `setup`, then `report <folder>`. |

## References (read only when needed)

- `references/methodology.md`: exact metric definitions, confidence rules, statistical tests.
  Read it when the user asks how numbers are computed or why a grade was given.
- `references/interpretation.md`: turning results into recommendations, language-specific
  caveats (English as a global language, Spanish/Portuguese across countries, Chinese, Russian vs
  Ukrainian, Korean...), topic-basket ideas, answer templates.
- `references/cli.md`: every command, option, output file, environment variable and exit code.
