#!/usr/bin/env python3
"""Grade a run made by any agent front-end (Claude Code, Cursor, a subagent...)
from its side effects: a log of the commands it executed, the files it produced
and its final answer.

The command log comes from a tiny `python3` shim placed first on PATH:

    printf '%s\\t%s\\t%s\\n' "$(date +%s)" "$PWD" "python3 $*" >> "$HAIKU_LOG"
    exec /usr/bin/python3 "$@"

    python evals/grade_workspace.py --scenario fasting-pl-cs --workspace WS --log commands.log \\
        --answer WS/answer.md [--answer2 WS/answer2.md --split-at <unix-ts>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graders import grade  # noqa: E402


def load_calls(log: Path, workspace: str) -> list[tuple[int, str]]:
    calls = []
    for line in log.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3 and parts[1].startswith(workspace):
            calls.append((int(parts[0]), parts[2]))
    return calls


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--answer", required=True, type=Path)
    ap.add_argument("--answer2", type=Path, help="answer to the second user turn")
    ap.add_argument("--split-at", type=int, help="unix time separating turn 1 and turn 2 commands")
    ap.add_argument("--skill-read", action="store_true",
                    help="the front-end's own log confirms SKILL.md was opened (file reads are not shell commands)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    scenarios = {s["id"]: s for s in json.loads((Path(__file__).parent / "scenarios.json").read_text())["scenarios"]}
    sc = scenarios[args.scenario]
    ws = str(Path(args.workspace).resolve())
    calls = load_calls(args.log, ws)
    turns = []
    split = args.split_at or 10**12
    texts = [args.answer.read_text(encoding="utf-8")]
    if args.answer2:
        texts.append(args.answer2.read_text(encoding="utf-8"))
    for i, answer in enumerate(texts):
        mine = [c for t, c in calls if (t < split if i == 0 else t >= split)]
        tool_calls = [{"name": "bash", "args": {"command": c}, "output": ""} for c in mine]
        if i == 0 and args.skill_read:
            tool_calls.insert(0, {"name": "read_file", "args": {"path": "SKILL.md"}, "output": ""})
        turns.append({"user": sc["turns"][i], "answer": answer, "tool_calls": tool_calls})
    checks = [c for c in sc["checks"] if c.get("turn", 1) <= len(turns) and c["type"] != "max_tool_calls"]
    report = grade(dict(sc, checks=checks), {"workspace": ws, "turns": turns})
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1))
    else:
        for r in report["checks"]:
            print(("PASS " if r["passed"] else "FAIL ") + r["check"]["type"].ljust(18) + " " + r["detail"])
        print(f"{report['passed']}/{report['total']} checks passed ({len(calls)} python3 invocations logged)")
    return 0 if report["passed"] == report["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
