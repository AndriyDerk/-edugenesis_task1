# EduGenesis task 1: Wikipedia interest research skill

The deliverable is the Agent Skill in [`wikipedia-interest-trends/`](wikipedia-interest-trends/).
All code and materials live in that directory:

- [`SKILL.md`](wikipedia-interest-trends/SKILL.md): what the agent reads.
- [`README.md`](wikipedia-interest-trends/README.md): what the skill does, and how to install and test it.
- [`docs/DEVELOPMENT.md`](wikipedia-interest-trends/docs/DEVELOPMENT.md): design decisions, how the
  AI-written code was verified, bugs found, eval results.
- [`docs/ROADMAP.md`](wikipedia-interest-trends/docs/ROADMAP.md): how to grow the skill towards more
  complex research and larger data volumes.
- [`evals/`](wikipedia-interest-trends/evals/): agent-level evaluation with cheap/free models.

Quick start:

```
python3 wikipedia-interest-trends/scripts/wt.py analyze --topic "Intermittent fasting" --langs pl,cs --lang uk --pdf
```
