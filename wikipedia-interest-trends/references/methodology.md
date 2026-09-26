# Methodology

How `wt.py analyze` turns raw pageviews into the numbers in the summary. Everything below is
implemented in `scripts/wikitrends/` (file names in brackets) and covered by tests.

## 1. Data

| What | Source | Notes |
|---|---|---|
| Daily views per article | Analytics API `pageviews/per-article/{project}/all-access/user/{title}/daily` | `agent=user` = human traffic (spiders and heuristically detected bots excluded). Days with 0 views are omitted by the API and filled with 0. |
| Desktop views per article | same, `access=desktop` | Only for main titles; used for platform checks and spike classification. |
| Monthly views of the whole wiki | `pageviews/aggregate/{project}/all-access/user/monthly` | Denominator for "vs wiki" and "per million". |
| Reader countries | `pageviews/top-by-country/{project}/all-access/{year}/{month}` | Privacy-bucketed; only the rank order is used. |
| Article mapping | Wikidata `wbgetentities` sitelinks | The same concept (Q-id) in every language; titles are never machine-translated. |
| Canonical titles, redirects | MediaWiki Action API (`prop=redirects|pageprops|description`) | Redirect views are added to the article so renamed articles keep their history. |

Only complete calendar months are analysed. Data newer than 3 days is refetched on later runs;
everything older is cached permanently in `~/.cache/wikitrends/cache.sqlite` (`cache.py`).
Requests are rate-limited to 2.5/s with a policy-compliant User-Agent and retried with backoff on
429/5xx (`net.py`).

## 2. Cleaning (`series.py`)

* **Spikes.** For every day: a centred 29-day rolling median `m` and MAD. A day is a spike when
  `views > m + 6 * max(1.4826*MAD, sqrt(m), 0.05*m)`, `views >= 2*m` and `views - m >= 20`. Spike days
  are replaced by `m` (the "clean" series). The Poisson floor `sqrt(m)` prevents false alarms on
  small articles; the relative floor on smooth big ones.
* **Spike type.** Consecutive spike days form an event. If the event's desktop share is at least 60 %
  and at least 25 points above the article's normal desktop share, it is labelled *bot-like*
  (typical of undetected crawlers); otherwise *event-like* (news, viral moment).
* **Artefacts.** `late_start`: no views for 30+ days at the start, then real traffic (article created
  or renamed). If that happens after the comparison year starts, the cell becomes `new-article` and
  its growth is not reported. `dropped_to_zero`: traffic stops for the final 30+ days.
  `level_shift`: the median of 3 consecutive months differs from the previous 3 by x2.5 or more
  (rename/merge, main-page feature, tracking change). `new_item`: an article in a basket appeared
  mid-window and carries 10 %+ of recent views.

## 3. Metrics (`analysis.py`)

Let `prev` = the 12 months before the last 12, `last` = the last 12 complete months.

| Metric | Definition |
|---|---|
| YoY growth (headline) | `sum(clean[last]) / sum(clean[prev]) - 1` |
| 90 % CI | Percentile bootstrap (4000 resamples, fixed seed) over the 12 month-pairs (Jan-vs-Jan, ...). |
| months up / down | Month-pairs where the last year is higher / lower. Sign test p-value `sign_p`. |
| Raw YoY | Same on the uncleaned series; a large gap to the clean YoY means spikes drive the change. |
| vs wiki (normalised YoY) | `(sum(clean[last]) / sum(wiki[last])) / (sum(clean[prev]) / sum(wiki[prev])) - 1`, same bootstrap. |
| Project YoY | Growth of the whole language edition. |
| Per million | Topic views per 1M views of the whole wiki (last 12 months): topic salience. |
| Last-3 YoY | Last 3 months vs the same 3 months a year earlier: momentum. |
| Seasonal Kendall p | Hirsch-Slack seasonal Mann-Kendall test on monthly views/day over the full window (matches `pymannkendall.seasonal_test`). |
| Sen annual growth | `exp(seasonal Sen slope of log(views/day+1)) - 1` over the full window. |
| CAGR | Only for windows of 36+ months: first 12 vs last 12 months, annualised. |
| Platform YoY | Desktop and mobile (all minus desktop) YoY for the main titles. |

**Direction** (from the clean YoY):
`growing` = CI above 0 **and** sign test p < 0.10 (`slightly growing` if the whole CI is below +10 %);
`declining` symmetric; `stable` = CI inside ±10 % but not significant;
`likely growing/declining` = only one of the two tests agrees; otherwise `inconclusive`.

## 4. Confidence grade (`assess_confidence`)

Start at 100 and subtract. Every rule leaves a reason code, printed in the caveats.

| Rule | Points |
|---|---|
| Volume < 10 views/day (caps the grade at LOW) / < 50 (caps at MEDIUM) / < 200 | -40 / -20 / -8 |
| Direction inconclusive / only partly supported | -25 / -12 |
| No views in the comparison year (caps at LOW) | -40 |
| 90 % CI wider than 60 points | -10 |
| Raw and clean YoY differ by more than 15 points (spike-driven) | -15 |
| More than 20 % of views come from spikes | -10 |
| Bot-like bursts are more than 3 % of views | -10 |
| Topic and whole-wiki growth point in opposite directions | -5 |
| Whole-wiki traffic unavailable | -5 |
| Desktop and mobile trends disagree (each beyond ±10 %) | -10 |
| Article appeared mid-window (caps at LOW) / traffic stops (caps at LOW) | -35 / -35 |
| Abrupt level shift | -10 |
| Basket article missing in this language | -10 |
| New basket article carries 10 %+ of views (caps at MEDIUM) | -20 |
| Too many redirects to count them all | -5 |
| Some series failed to download | -15 |

HIGH >= 75, MEDIUM 50-74, LOW < 50.

## 5. Comparisons and ranking

* **Pairwise difference** of YoY growth (in percentage points) with a joint bootstrap over the same
  resampled months for both options, so shared calendar effects cancel. "A grew faster" only if the
  90 % CI of the difference excludes 0.
* **Opportunity score** (0-100) = weighted mean of four components on *fixed* scales, so scores are
  comparable between runs and two options do not collapse into 0 vs 100:

  | Component | Input | Scale mapped to 0..1 |
  |---|---|---|
  | reach | log10 average monthly views | 100 .. 1M views/month |
  | momentum | YoY growth vs wiki (plain YoY if unavailable; neutral 0.5 for new articles) | -30 % .. +50 % |
  | intensity | log10 views per million wiki views | 1 .. 1000 |
  | confidence | confidence score / 100 | 0 .. 1 |

  Default weights: reach 0.30, momentum 0.35, intensity 0.20, confidence 0.15. Presets:
  `balanced`, `growth-first`, `size-first`, `niche-first`; or custom `reach=..,momentum=..`.
* **Sensitivity.** The winner is recomputed under all four presets; "robust" means the same winner
  every time. Otherwise the answer depends on the user's priorities; say so.

## 6. Known limitations

* Month-pairs are treated as independent. Real series are autocorrelated, so intervals are
  somewhat optimistic. Treat MEDIUM results as "needs confirmation".
* `agent=user` still contains some undetected automated traffic. Wikimedia reclassified bot traffic
  in 2025, so changes around spring–summer 2025 deserve a second look.
* Pageviews of a language edition come from people reading in that language, wherever they are.
  Many speakers of some languages read English Wikipedia instead.
* The whole-wiki denominator includes all pages (main page, special pages). It is a proxy for
  "overall usage of that Wikipedia", not for internet usage.
* Pageviews measure attention and curiosity, not purchase intent.
