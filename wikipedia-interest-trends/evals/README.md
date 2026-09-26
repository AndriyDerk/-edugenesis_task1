# Agent evals

Unit tests prove the code is right; these evals prove that a **small model can use the skill**:
it has to notice the skill, open SKILL.md, choose the right command and arguments, read the
output correctly, and answer without inventing numbers.

## Files

| File | Purpose |
|---|---|
| `scenarios.json` | The three reference questions from the task (Ukrainian), follow-up turns, and edge cases (article created mid-window, ambiguous topic, unnamed languages). Each has deterministic checks. |
| `graders.py` | The checks: skill opened, command/languages used, PDF exists and has one page, answer language, required/forbidden phrases, **every % / pp in the answer matches a figure computed by the tool**, tool-call budget. |
| `agent_eval.py` | Minimal skills-capable agent for any OpenAI-compatible API (OpenRouter by default): `<available_skills>` in the system prompt, `bash` + `read_file` tools, multi-turn scenarios, transcripts + grades + summary table. Stdlib only. |
| `grade_workspace.py` | Grades runs made with other front-ends (Claude Code, a subagent...) from a command log, the produced files and the final answer. |
| `results/` | Summaries of runs referenced in `docs/DEVELOPMENT.md`. |

## Running with free models (OpenRouter)

```
export OPENROUTER_API_KEY=sk-or-...
python evals/agent_eval.py --list-models                  # free models that support tool calling
python evals/agent_eval.py --model <id>:free --fake       # synthetic world, no Wikimedia access needed
python evals/agent_eval.py --model <id>:free --only astronomy-uk-trust --turns 1   # save quota
python evals/agent_eval.py --model anthropic/claude-haiku-4.5                       # live data
```

Free tier limits (about 20 requests/min and 50/day without credits) are respected with
`--min-interval 3.5` and retries on 429. A full run is about 40-70 model calls. Use `--only`/`--turns`
to stay within the daily quota, or add $10 of credits for 1000 free-model requests per day.
Any OpenAI-compatible server works: `--base-url http://localhost:11434/v1` (Ollama), etc.

`--fake` starts `tests/fake_wikimedia.py`, a deterministic world with planted ground truth
(pl +45 %/yr with a bot burst, cs +3 %, a Ukrainian article created mid-window, ...), so a run
checks the *agent*, not the day's Wikipedia traffic.

## Grading a run from another agent front-end

Put a logging shim first on `PATH` (it records every `python3` call), let the agent work in a
workspace, save its final answer, then:

```
python evals/grade_workspace.py --scenario fasting-pl-cs --workspace WS --log commands.log \
    --answer WS/answer.md --skill-read
```
