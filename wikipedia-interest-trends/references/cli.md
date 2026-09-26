# CLI reference

`python3 <skill-dir>/scripts/wt.py [--quiet] [--no-cache] <command> [options]`

Global flags may also be given after the command. Progress messages go to stderr; results to stdout.

## analyze

Resolve topics, download pageviews (cached), compute metrics, write charts and summaries.

| Option | Meaning |
|---|---|
| `--topic TEXT` | Free text (English preferred), `Q123` Wikidata id, or `lang:Title`. Repeat to compare topics. |
| `--basket ITEM [ITEM...] [name=LABEL]` | One topic made of several articles; items as for `--topic`; `name=` labels it (default: first item + count). Repeatable. |
| `--langs pl,cs,uk` | Wikipedia language codes (required). Common mistakes are corrected (`ua` -> `uk`, `cz` -> `cs`). Max 25. |
| `--months N` | Last N complete months (default 24; shorter windows are extended to 24). |
| `--start YYYY-MM` / `--end YYYY-MM` | Explicit window (overrides `--months`). |
| `--search-lang en` | Wikipedia used to search free-text topics. Use `uk` for Ukrainian queries. |
| `--agent user` | `user` (humans, default), `all-agents`, `automated`, `spider`. |
| `--no-redirects` | Count only the main titles (default: add redirects, oldest first, up to `--max-redirects 10`). |
| `--max-requests 400` | Upper bound on downloaded series per run (about 2.5 per second); redirects are trimmed to fit and a warning says so. |
| `--no-platform` | Skip the desktop/mobile split (fewer requests; no bot-like spike labels). |
| `--no-geo` | Skip reader-country lookup. |
| `--weights` | `balanced` (default), `growth-first`, `size-first`, `niche-first`, or `reach=0.3,momentum=0.4,intensity=0.2,confidence=0.1`. |
| `--lang en|uk` | Language of charts, `summary.md` and the PDF. |
| `--pdf` | Also build the one-page PDF (auto findings, no custom summary). |
| `--title`, `--question` | Printed in summary/PDF. |
| `--out DIR` | Output folder (default `./wikitrends-out/<topic>_<langs>_<period>/`). |
| `--no-charts` | Skip PNG charts. |
| `--json` | Print only `{"results": path, "files": {...}}`. |

Limits: at most 60 topic x language combinations per run.

Output folder:

| File | Content |
|---|---|
| `results.json` | Everything: parameters, resolved articles, monthly series, metrics, confidence reasons, comparisons, ranking, reader countries. Schema `wikitrends/1`. |
| `monthly.csv` | topic, lang, month, days, raw/clean views, whole-wiki views, per-million, main-title all/desktop views. |
| `summary.md` | Markdown summary with findings and table. |
| `trend.png`, `growth.png`, `opportunity.png` | Charts (opportunity only with 3+ options). |
| `report.pdf`, `report.md` | With `--pdf` or after `report`. |

A line per run is appended to `./wikitrends-out/history.jsonl` (see `history`).

## report

`report <folder-or-results.json> [--lang uk] [--title T] [--question Q] [--summary TEXT | --summary-file F]
[--recommendation TEXT | --recommendation-file F] [--strict]`

Builds `report.pdf` (A4, always exactly one page: content is compacted and scaled to fit) and
`report.md`, regenerating charts in the chosen language. Summary/recommendation accept simple
Markdown (`**bold**`, `- bullets`). Every percentage and "pp" figure in the text is checked against
the analysis; mismatches are printed under `NUMBER CHECK`. With `--strict` nothing is written until
they are fixed (exit code 2).

## rank

`rank <folder> --weights PRESET|k=v,...` re-scores options from `results.json` without network
access and saves the new ranking into it.

## resolve

`resolve --topic X [--basket ...] --langs ... [--json]` shows the chosen Wikidata item, alternatives,
and the article + redirects per language, without downloading pageviews.

## views

`views lang:Title [--months N | --start --end] [--granularity monthly|daily] [--access ...] [--agent ...]`
prints raw CSV for one article (redirects resolved to the canonical title, not summed).

## history, cache, doctor, setup

* `history [--limit 10]`: previous analyses with their folders.
* `cache info` / `cache clear [--metadata-only]`: SQLite cache at `~/.cache/wikitrends/cache.sqlite`.
* `doctor`: checks Python, dependencies, cache and connectivity to the three APIs.
* `setup`: installs pinned matplotlib/reportlab (hash-checked, from `requirements.lock`) into
  `~/.cache/wikitrends/site-<python>-<lockhash>/`. Runs automatically on first `analyze`/`report`.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `WIKITRENDS_HOME` | `~/.cache/wikitrends` | Cache and dependency folder. |
| `WIKITRENDS_OUT` | `./wikitrends-out` | Default output root. |
| `WIKITRENDS_CONTACT` | - | Contact (email/URL) appended to the User-Agent, as Wikimedia's policy asks. |
| `WIKITRENDS_MAX_RPS` | `2.5` | Request rate limit across all hosts. |
| `WIKITRENDS_WORKERS` | `4` | Parallel downloads. |
| `WIKITRENDS_OFFLINE` | - | `1` = use cached data only. |
| `WIKITRENDS_TODAY` | today | Pin "today" (reproducible runs, tests). |
| `WIKITRENDS_NO_INSTALL` | - | Never auto-install dependencies. |
| `WIKITRENDS_REST_BASE`, `WIKITRENDS_WIKI_API`, `WIKITRENDS_WIKIDATA_API` | Wikimedia URLs | Point to mirrors or the test server. |

## Exit codes

`0` ok, `1` doctor found problems, `2` bad input (message explains), `3` network error,
`4` dependencies could not be installed (`setup`).
