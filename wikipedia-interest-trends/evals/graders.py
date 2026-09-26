"""Deterministic graders for agent transcripts (shared by agent_eval.py and
manual runs). A transcript is::

    {"workspace": "/abs/path",
     "turns": [{"user": str, "answer": str,
                "tool_calls": [{"name": "bash"|"read_file", "args": {...}, "output": str}]}]}
"""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path
from typing import Any

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "scripts"))

from wikitrends.report import PCT_RE, _num, is_ci_level, known_values  # noqa: E402

ANALYZE_RE = re.compile(r"wt\.py\s+(?:--\S+\s+)*analyze\b")
LANGS_RE = re.compile(r"--langs[=\s]+[\"']?([a-zA-Z,\- ]+?)[\"']?(?:\s+--|\s*$|\s*[;&|]|\s+\S+=)")


def _turns(tr: dict[str, Any], turn: int | None) -> list[dict[str, Any]]:
    return tr["turns"] if turn is None else [tr["turns"][turn - 1]]


def _commands(tr: dict[str, Any], turn: int | None) -> list[str]:
    out = []
    for t in _turns(tr, turn):
        for call in t["tool_calls"]:
            if call["name"] == "bash":
                out.append(call["args"].get("command", ""))
    return out


def _answer(tr: dict[str, Any], turn: int | None, keep_paths: bool = False) -> str:
    text = (tr["turns"][-1] if turn is None else tr["turns"][turn - 1])["answer"] or ""
    if keep_paths:
        return text
    # file paths contain words like 'ambiguous' or 'report'; they must not satisfy text checks
    return re.sub(r"(?:[A-Za-z]:)?[\w.~-]*(?:/[\w.@%+~-]+){2,}/?", " ", text)


def _langs_in(cmd: str) -> set[str]:
    langs: set[str] = set()
    for m in LANGS_RE.finditer(cmd + " "):
        langs.update(x.strip().lower() for x in re.split(r"[,\s]+", m.group(1)) if x.strip())
    return langs


def _results_files(workspace: str, transcript: dict[str, Any] | None = None) -> list[Path]:
    """results.json files in the workspace plus any the tool printed (agents may use --out)."""
    files = {Path(p) for p in glob.glob(f"{workspace}/**/results.json", recursive=True)}
    for t in (transcript or {}).get("turns", []):
        for call in t["tool_calls"]:
            for m in re.finditer(r"(/\S+?/results\.json)", call.get("output", "")):
                files.add(Path(m.group(1)))
    return [f for f in files if f.exists()]


def numbers_problems(answer: str, workspace: str, extra_ok: str = "",
                     transcript: dict[str, Any] | None = None) -> list[str]:
    """Percentages / pp in the answer that match no figure of any analysis the agent ran."""
    pct: list[float] = []
    pp: list[float] = []
    for f in _results_files(workspace, transcript):
        try:
            res = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        a, b = known_values(res)
        pct += [v for v, _ in a]
        pp += [v for v, _ in b]
    allowed_text = set()
    for m in PCT_RE.finditer(extra_ok):
        allowed_text.add(abs(_num(m.group(1))))
    problems = []
    for m in PCT_RE.finditer(answer):
        try:
            v = abs(_num(m.group(1)))
        except ValueError:
            continue
        if is_ci_level(v, answer, m.start(), m.end()):
            continue
        if v in allowed_text or v == 100.0:
            continue
        pool = pp if m.group(2).strip().lower() != "%" else pct + pp
        if not any(abs(v - abs(k)) <= max(1.05, 0.03 * abs(k)) for k in pool):
            problems.append(m.group(0).strip())
    return problems


def _cyrillic_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "Ѐ" <= c <= "ӿ") / len(letters)


def _pdf_pages(path: Path) -> int:
    try:
        import pypdf
        return len(pypdf.PdfReader(str(path)).pages)
    except ImportError:
        return len(re.findall(rb"/Type\s*/Page[^s]", path.read_bytes()))


def run_check(check: dict[str, Any], tr: dict[str, Any]) -> tuple[bool, str]:
    kind = check["type"]
    turn = check.get("turn")
    if kind == "read_skill":
        for t in tr["turns"]:
            for call in t["tool_calls"]:
                blob = json.dumps(call["args"], ensure_ascii=False)
                if "SKILL.md" in blob:
                    return True, "SKILL.md was read"
        return False, "SKILL.md never opened"
    if kind == "command":
        rx = re.compile(check["pattern"])
        hits = [c for c in _commands(tr, turn) if rx.search(c)]
        return bool(hits), (hits[0][:160] if hits else f"no command matching {check['pattern']}")
    if kind == "command_langs":
        want = {l.lower() for l in check["langs"]}
        for c in _commands(tr, turn):
            if ANALYZE_RE.search(c) and want <= _langs_in(c):
                return True, c[:160]
        seen = [sorted(_langs_in(c)) for c in _commands(tr, turn) if ANALYZE_RE.search(c)]
        return False, f"no analyze with langs {sorted(want)}; saw {seen}"
    if kind == "command_min_langs":
        best = max((len(_langs_in(c)) for c in _commands(tr, turn) if ANALYZE_RE.search(c)), default=0)
        return best >= check["n"], f"max languages in one analyze: {best}"
    if kind == "file":
        files = sorted(glob.glob(f"{tr['workspace']}/{check['glob']}"))
        if not files:
            return False, f"no file {check['glob']}"
        if "pages" in check:
            pages = _pdf_pages(Path(files[-1]))
            return pages == check["pages"], f"{files[-1]} has {pages} page(s)"
        return True, files[-1]
    if kind == "answer_regex":
        text = _answer(tr, turn, keep_paths=check.get("keep_paths", False))
        ok = re.search(check["pattern"], text, re.IGNORECASE | re.DOTALL) is not None
        return ok, ("matched" if ok else f"answer lacks /{check['pattern']}/")
    if kind == "answer_not_regex":
        m = re.search(check["pattern"], _answer(tr, turn), re.IGNORECASE | re.DOTALL)
        return m is None, ("ok" if m is None else f"forbidden text: {m.group(0)[:80]}")
    if kind == "answer_language":
        share = _cyrillic_share(_answer(tr, turn))
        ok = share > 0.5 if check["lang"] == "uk" else share < 0.2
        return ok, f"cyrillic share {share:.2f}"
    if kind == "numbers_verified":
        ans = _answer(tr, turn)
        prompt = " ".join(t["user"] for t in tr["turns"])
        bad = numbers_problems(ans, tr["workspace"], extra_ok=prompt, transcript=tr)
        n = len(PCT_RE.findall(ans))
        return not bad, (f"{n} figure(s), all match the analysis" if not bad else f"unverified: {bad}")
    if kind == "hedged_causes":
        # causal claims about markets must be marked as hypotheses: the data shows what, not why
        causes = re.compile(r"конкурент|насичен|економі|міграц|емігр|культур|менталіт|competit|saturat|econom|"
                            r"migrat|cultur|because of", re.IGNORECASE)
        hedge = re.compile(r"може|можлив|гіпотез|припущ|перевір|імовірн|ймовірн|might|may |possib|hypothes|"
                           r"check|perhaps|likely", re.IGNORECASE)
        text = _answer(tr, turn)
        bad = [s_.strip()[:90] for s_ in re.split(r"(?<=[.!?])\s+|\n", text)
               if causes.search(s_) and not hedge.search(s_)]
        return not bad, ("ok" if not bad else f"unhedged cause: {bad[0]}")
    if kind == "max_tool_calls":
        n = sum(len(t["tool_calls"]) for t in tr["turns"])
        return n <= check["n"], f"{n} tool calls (limit {check['n']})"
    return False, f"unknown check type {kind}"


def grade(scenario: dict[str, Any], transcript: dict[str, Any]) -> dict[str, Any]:
    results = []
    for check in scenario["checks"]:
        try:
            ok, detail = run_check(check, transcript)
        except Exception as exc:  # noqa: BLE001 - a broken check must not hide others
            ok, detail = False, f"grader error: {exc!r}"
        results.append({"check": check, "passed": ok, "detail": detail})
    passed = sum(r["passed"] for r in results)
    return {"id": scenario["id"], "passed": passed, "total": len(results), "checks": results}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Grade a saved transcript JSON against a scenario.")
    ap.add_argument("transcript")
    ap.add_argument("--scenario", required=True)
    args = ap.parse_args()
    scenarios = {s["id"]: s for s in json.loads((Path(__file__).parent / "scenarios.json").read_text())["scenarios"]}
    tr = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    report = grade(scenarios[args.scenario], tr)
    for r in report["checks"]:
        print(("PASS " if r["passed"] else "FAIL ") + r["check"]["type"].ljust(18) + r["detail"])
    print(f"{report['passed']}/{report['total']} checks passed")
