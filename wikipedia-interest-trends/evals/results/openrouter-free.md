# Free OpenRouter models: agent-level eval (fake Wikimedia data)

`python evals/agent_eval.py --model <id> --fake --turns 1` with a free-tier key (about 50 requests/day).
Graded by `evals/graders.py` (final version).

| model | scenario | checks | tool calls | note |
|---|---|---|---|---|
| qwen/qwen3.8-27b:free | fasting-pl-cs | 9/9 | 2 | the other 5 scenarios got `429 temporarily rate-limited upstream` from the free provider: an availability problem, not a skill failure |
| nvidia/nemotron-3-super-120b-a12b:free | astronomy-uk-trust | 9/10 | 2 | no willingness-to-pay caveat |
| nvidia/nemotron-3-super-120b-a12b:free | english-audiences-report | 9/10 | 3 | no willingness-to-pay caveat |
| nvidia/nemotron-3-super-120b-a12b:free | english-audiences-open | 7/8 | 2 | no willingness-to-pay caveat |
| nvidia/nemotron-3-super-120b-a12b:free | fasting-new-article | 5/5 | 2 | - |
| nvidia/nemotron-3-super-120b-a12b:free | mercury-ambiguous | 6/6 | 2 | - |

**Total: 45/48 checks.** Both models found the skill, opened SKILL.md, used the right command and
languages in 2-3 tool calls, and quoted only numbers the tool computed. The only systematic miss
is the curiosity-vs-willingness-to-pay caveat. On 2026-09-27 most free models (Gemma 4, Qwen 3.8,
Laguna) were rate-limited upstream, so re-run with `--only` on another day for broader coverage.

Grader fixes found while grading these runs: accept "впевненість" as a confidence word; find
results and PDFs in directories the agent `cd`-ed into (Nemotron ran the CLI from the skill folder),
but only analyses referenced by that transcript; skip turn-2 checks for single-turn runs.
