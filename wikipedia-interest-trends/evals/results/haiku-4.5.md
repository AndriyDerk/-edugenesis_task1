# Claude Haiku 4.5: agent-level eval results

**Setup.** Claude Haiku 4.5 ran as a Claude Code subagent (Bash + Read tools, about 30k tokens of
harness system prompt). It saw only the skill's name, description and location, and had to open
SKILL.md itself. Data came from the fake Wikimedia server (`tests/fake_wikimedia.py`), because the
development sandbox had no egress to Wikimedia or OpenRouter. Every `python3` call was logged by a
PATH shim, and each run was graded with `evals/grade_workspace.py` against `evals/scenarios.json`.

All rounds were **re-graded with the final graders**. Checks added later (willingness-to-pay
caveat, hedged causes, number attribution, Russian drift) therefore also apply to early rounds.
Every answer was also read by a person. Where a heuristic check misfired on an early version, the
check was fixed, not the verdict.

| round | what changed before the round | runs | checks passed | fully clean runs |
|---|---|---|---|---|
| 1 | first SKILL.md | 2 (+1 lost to a sandbox path typo) | 15/17 | 0/2 |
| 2 | answer skeleton, tie detection, decision-first findings | 4 | 25/27 | 2/4 |
| 3 | `!! CHECK TOPIC` banner, whole-wiki column, answer checklist | 4 (2 two-turn) | 37/37 | 4/4 |
| 4 (RC) | slightly-growing labels, request budget, all 6 scenarios | 6 (2 two-turn) | 48/49 | 5/6 |
| 5 | findings printed in the user's language | 3 | 22/24 | 1/3 |
| 6 | explicit "no competition/saturation" rule | 3 | 24/25 | 2/3 |
| 7 | `--basket` items + `name=`, data-derived "why" line | 3 | 22/23 | 2/3 |

## Per run (final graders)

| round | scenario | checks | failed check |
|---|---|---|---|
| 1 | fasting-pl-cs | 7/8 | no willingness-to-pay caveat |
| 1 | english-audiences-report | 8/9 | invented cause ("economic incentives") |
| 2 | astronomy-uk-trust | 8/9 | misread "vs wiki +8.8 %" as "Wikipedia fell 8.8 %" |
| 2 | english-audiences-open | 7/7 | - |
| 2 | fasting-new-article | 5/5 | - |
| 2 | mercury-ambiguous | 5/6 | did not tell the user "Mercury" is ambiguous |
| 3 | astronomy-uk-trust | 9/9 | - |
| 3 | mercury-ambiguous | 6/6 | - |
| 3 | fasting-pl-cs (2 turns: +Slovak, 36 months) | 11/11 | - |
| 3 | english-audiences-report (2 turns: +size priority) | 11/11 | - |
| 4 | fasting-pl-cs (2 turns) | 11/11 | - |
| 4 | astronomy-uk-trust | 9/9 | - |
| 4 | english-audiences-report (2 turns) | 11/11 | - |
| 4 | english-audiences-open | 6/7 | invented cause ("less saturated with competitors") |
| 4 | fasting-new-article | 5/5 | - |
| 4 | mercury-ambiguous | 6/6 | - |
| 5 | english-audiences-open | 6/7 | invented "competitive advantage"; analysed one article only (basket-name trap, fixed in round 7) |
| 5 | english-audiences-report | 8/9 | invented "less saturated markets" |
| 5 | fasting-pl-cs | 8/8 | - |
| 6 | english-audiences-open | 6/7 | invented "less competitive conditions" |
| 6 | english-audiences-report (a) | 9/9 | - (a Russian heading slipped in; check added afterwards) |
| 6 | english-audiences-report (b) | 9/9 | - |
| 7 | english-audiences-open (a) | 6/7 | 98k views attributed to pt (they are es) |
| 7 | english-audiences-open (b) | 7/7 | - |
| 7 | english-audiences-report | 9/9 | - |

## What this shows

* **Tool use is reliable.** In every run Haiku opened SKILL.md, chose the right command and
  languages, and used `--months 36`, `rank --weights size-first` and `report` correctly in
  follow-ups. It needed 4-11 tool calls and 35-180 s per question. Across all runs, not a single
  percentage in an answer was missing from the analysis (`numbers_verified`).
* **The fixed questions are solved.** Comparing two languages, "is it growing, can we trust it?",
  new-article and ambiguous-topic cases have been clean since round 3.
* **Open-ended "which audiences next and why" is the weak spot.** A small model still sometimes
  justifies a recommendation with market facts that are not in the data (competition, saturation),
  or copies a number from the neighbouring row. Each fix lowered the rate but did not remove it.
  That is why the skill does not rely on the model alone:
  * the CLI prints decision sentences and a data-derived "why" line in the user's language;
  * `report` refuses (`--strict`) or warns on numbers that do not match, or that belong to another
    language (`ATTRIBUTION CHECK`);
  * the graders track both failure modes, so regressions are visible.

Next steps for this failure mode are in `docs/ROADMAP.md` (MCP tools returning structured data,
and a `draft` command that writes the recommendation paragraph from the ranking).


## Live Wikimedia data (2026-09-27)

After network access was granted, Haiku 4.5 ran the three reference questions on **real**
Wikipedia data (same subagent setup, no mirror):

| question | checks | notes |
|---|---|---|
| intermittent fasting, pl vs cs | 7/8 | Correct and honest. Polish Wikipedia has **no** article on intermittent fasting (not linked to Q1666254, not found by search), so pl cannot be measured. Czech −42.6 % with LOW confidence (6 views/day). The failed check expects the synthetic ground truth ("Polish grows faster") and does not apply to real data. |
| astronomy in Ukrainian Wikipedia | 9/9 | Reports −60.1 % YoY but explains the MEDIUM grade: a ×0.3 level shift in 2025-05 coinciding with Wikimedia's bot-detection update. Points to the share-of-wiki metric (−47.0 %). |
| learning English, 6 languages | 9/9 | PDF built. Interest in the basket falls in all six editions; tr ≈ de on top (tie). Two small slips that no check catches: "Turkish has the smallest decline" (German does) and "German has the largest audience" (Spanish does). |
