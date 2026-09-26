#!/usr/bin/env python3
"""Run the skill end to end with a cheap or free LLM and grade the result.

A minimal skills-capable agent: the model sees the skill's name + description
(<available_skills>, as agents do at start-up), must decide to open SKILL.md,
then works only through a `bash` and a `read_file` tool. Any OpenAI-compatible
chat endpoint works; OpenRouter is the default.

    export OPENROUTER_API_KEY=sk-or-...
    python evals/agent_eval.py --list-models                       # free models with tool calling
    python evals/agent_eval.py --model <id>:free --fake            # synthetic Wikimedia (no network needed)
    python evals/agent_eval.py --model anthropic/claude-haiku-4.5  # real Wikimedia data
    python evals/agent_eval.py --model <id> --only astronomy-uk-trust --turns 1

Transcripts, grades and a summary table are written to evals/runs/<timestamp>-<model>/.
Stdlib only.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

EVALS = Path(__file__).resolve().parent
SKILL = EVALS.parent
sys.path.insert(0, str(EVALS))
sys.path.insert(0, str(SKILL / "tests"))

from graders import grade  # noqa: E402

TOOLS = [
    {"type": "function", "function": {
        "name": "bash",
        "description": "Run a bash command in the working directory and return stdout+stderr (long output is "
                       "truncated). Commands may take a few minutes.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a UTF-8 text file (absolute path or relative to the working directory).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]


def skill_prompt(workspace: Path) -> str:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    front = text.split("---", 2)[1]
    name = re.search(r"^name:\s*(.+)$", front, re.M).group(1).strip()
    desc = re.search(r"^description:\s*(.+)$", front, re.M).group(1).strip()
    return (
        "You are a helpful assistant working in a sandbox with a bash tool and a read_file tool.\n"
        f"Working directory: {workspace}\n"
        "Skills extend what you can do. When a user request matches a skill's description, read its SKILL.md "
        "with read_file first and follow its instructions. Reply in the user's language.\n\n"
        "<available_skills>\n<skill>\n"
        f"<name>\n{html.escape(name)}\n</name>\n<description>\n{html.escape(desc)}\n</description>\n"
        f"<location>\n{SKILL / 'SKILL.md'}\n</location>\n</skill>\n</available_skills>"
    )


def _truncate(text: str, limit: int = 9000) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit * 2 // 3]
    tail = text[-limit // 3:]
    return f"{head}\n... [{len(text) - limit} characters truncated] ...\n{tail}"


def run_tool(name: str, args: dict[str, Any], workspace: Path, env: dict[str, str], timeout: int) -> str:
    if name == "bash":
        cmd = args.get("command", "")
        try:
            proc = subprocess.run(["bash", "-lc", cmd], cwd=workspace, env=env, capture_output=True, text=True,
                                  timeout=timeout)
            out = proc.stdout + (("\n[stderr]\n" + proc.stderr) if proc.stderr.strip() else "")
            return _truncate(out + f"\n[exit code {proc.returncode}]")
        except subprocess.TimeoutExpired:
            return f"[command timed out after {timeout}s]"
    if name == "read_file":
        path = Path(args.get("path", ""))
        if not path.is_absolute():
            path = workspace / path
        try:
            return _truncate(path.read_text(encoding="utf-8"))
        except OSError as exc:
            return f"[error] {exc}"
    return f"[error] unknown tool {name}"


class Chat:
    def __init__(self, base_url: str, api_key: str, model: str, min_interval: float, temperature: float):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.key = api_key
        self.model = model
        self.min_interval = min_interval
        self.temperature = temperature
        self._last = 0.0
        self.usage = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}

    def __call__(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        body = json.dumps({"model": self.model, "messages": messages, "tools": TOOLS, "tool_choice": "auto",
                           "temperature": self.temperature, "max_tokens": 2500}).encode()
        for attempt in range(8):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            req = urllib.request.Request(self.url, data=body, headers={
                "Authorization": f"Bearer {self.key}", "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/AndriyDerk/-edugenesis_task1",
                "X-Title": "wikipedia-interest-trends eval"})
            try:
                with urllib.request.urlopen(req, timeout=240) as resp:
                    data = json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:300]
                if exc.code in (429, 500, 502, 503, 504) and attempt < 7:
                    delay = float(exc.headers.get("Retry-After") or 0) or min(90, 5 * 2 ** attempt)
                    print(f"  [api {exc.code}] retry in {delay:.0f}s: {detail[:120]}", file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"API error {exc.code}: {detail}") from None
            if "error" in data:
                if attempt < 7:
                    print(f"  [api error] {str(data['error'])[:160]}; retrying", file=sys.stderr)
                    time.sleep(min(90, 5 * 2 ** attempt))
                    continue
                raise RuntimeError(str(data["error"]))
            u = data.get("usage") or {}
            self.usage["prompt_tokens"] += u.get("prompt_tokens", 0)
            self.usage["completion_tokens"] += u.get("completion_tokens", 0)
            self.usage["calls"] += 1
            return data["choices"][0]["message"]
        raise RuntimeError("API retries exhausted")


def run_scenario(chat: Chat, scenario: dict[str, Any], workspace: Path, env: dict[str, str], max_steps: int,
                 timeout: int, n_turns: int | None) -> dict[str, Any]:
    workspace.mkdir(parents=True, exist_ok=True)
    messages: list[dict[str, Any]] = [{"role": "system", "content": skill_prompt(workspace)}]
    transcript: dict[str, Any] = {"workspace": str(workspace), "turns": []}
    for user_text in scenario["turns"][: n_turns or None]:
        print(f"  user: {user_text[:90]}", file=sys.stderr)
        messages.append({"role": "user", "content": user_text})
        turn = {"user": user_text, "tool_calls": [], "answer": ""}
        for _ in range(max_steps):
            msg = chat(messages)
            calls = msg.get("tool_calls") or []
            messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")} |
                            {"role": "assistant", "content": msg.get("content") or ""})
            if not calls:
                turn["answer"] = msg.get("content") or ""
                break
            for call in calls:
                fn = call.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except ValueError:
                    args = {"_raw": fn.get("arguments")}
                print(f"    -> {fn.get('name')}: {json.dumps(args, ensure_ascii=False)[:140]}", file=sys.stderr)
                output = run_tool(fn.get("name", ""), args, workspace, env, timeout)
                turn["tool_calls"].append({"name": fn.get("name"), "args": args, "output": _truncate(output, 5000)})
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": output})
        else:
            turn["answer"] = "[max steps reached without a final answer]"
        transcript["turns"].append(turn)
    return transcript


def list_models(base_url: str, api_key: str | None) -> None:
    req = urllib.request.Request(base_url.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
    data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    rows = [m for m in data.get("data", []) if m["id"].endswith(":free")
            and "tools" in (m.get("supported_parameters") or [])]
    for m in sorted(rows, key=lambda m: -(m.get("context_length") or 0)):
        print(f"{m['id']:<60} ctx={m.get('context_length')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model")
    ap.add_argument("--base-url", default=os.environ.get("EVAL_BASE_URL", "https://openrouter.ai/api/v1"))
    ap.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--fake", action="store_true", help="serve synthetic Wikimedia data locally")
    ap.add_argument("--only", action="append", help="scenario id (repeatable)")
    ap.add_argument("--turns", type=int, help="limit turns per scenario (saves free-tier quota)")
    ap.add_argument("--max-steps", type=int, default=16)
    ap.add_argument("--timeout", type=int, default=600, help="per bash command, seconds")
    ap.add_argument("--min-interval", type=float, default=3.5, help="seconds between API calls (free tier: 20/min)")
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    key = os.environ.get(args.api_key_env)
    if args.list_models:
        list_models(args.base_url, key)
        return 0
    if not args.model or not key:
        ap.error(f"--model and ${args.api_key_env} are required")

    scenarios = json.loads((EVALS / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    if args.only:
        scenarios = [s for s in scenarios if s["id"] in args.only]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = args.out or EVALS / "runs" / f"{stamp}-{re.sub(r'[^a-zA-Z0-9.-]+', '_', args.model)}"
    out.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    env["WIKITRENDS_HOME"] = str(out / "home")  # shared cache across scenarios, like a real user
    server = None
    if args.fake:
        from fake_wikimedia import FakeWikimedia
        server = FakeWikimedia().__enter__()
        env.update(server.env)
    chat = Chat(args.base_url, key, args.model, args.min_interval, args.temperature)
    summary = []
    try:
        for sc in scenarios:
            print(f"== {sc['id']}", file=sys.stderr)
            t0 = time.monotonic()
            before = dict(chat.usage)
            try:
                tr = run_scenario(chat, sc, out / sc["id"], env, args.max_steps, args.timeout, args.turns)
                error = None
            except Exception as exc:  # noqa: BLE001 - record and continue with the next scenario
                tr, error = {"workspace": str(out / sc["id"]), "turns": []}, repr(exc)
            seconds = time.monotonic() - t0
            if args.turns:
                sc = dict(sc, checks=[c for c in sc["checks"] if c.get("turn", 1) <= args.turns])
            result = grade(sc, tr) if tr["turns"] else {"id": sc["id"], "passed": 0, "total": len(sc["checks"]),
                                                        "checks": []}
            result.update({"seconds": round(seconds), "error": error,
                           "tool_calls": sum(len(t["tool_calls"]) for t in tr["turns"]),
                           "prompt_tokens": chat.usage["prompt_tokens"] - before["prompt_tokens"],
                           "completion_tokens": chat.usage["completion_tokens"] - before["completion_tokens"]})
            (out / sc["id"]).mkdir(parents=True, exist_ok=True)
            (out / sc["id"] / "transcript.json").write_text(json.dumps(tr, ensure_ascii=False, indent=1), "utf-8")
            (out / sc["id"] / "grade.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
            summary.append(result)
            print(f"   {result['passed']}/{result['total']} checks, {result['tool_calls']} tool calls, "
                  f"{result['seconds']}s {('ERROR ' + error) if error else ''}", file=sys.stderr)
    finally:
        if server:
            server.__exit__(None, None, None)

    lines = [f"# Eval: {args.model} ({'fake' if args.fake else 'live'} data), {stamp}", "",
             "| scenario | checks | tool calls | tokens in/out | seconds | failed checks |", "|---|---|---|---|---|---|"]
    for r in summary:
        failed = "; ".join(f"{c['check']['type']}: {c['detail']}" for c in r["checks"] if not c["passed"])
        lines.append(f"| {r['id']} | {r['passed']}/{r['total']} | {r['tool_calls']} | {r['prompt_tokens']}/"
                     f"{r['completion_tokens']} | {r['seconds']} | {failed or r.get('error') or '-'} |")
    total = sum(r["passed"] for r in summary), sum(r["total"] for r in summary)
    lines += ["", f"**Total: {total[0]}/{total[1]} checks passed.**"]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
