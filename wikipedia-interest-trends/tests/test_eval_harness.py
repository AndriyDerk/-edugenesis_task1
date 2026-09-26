"""The eval harness itself: agent loop + graders, driven by a scripted
OpenAI-compatible 'model' so it runs offline."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL / "evals"))

pytest.importorskip("matplotlib")


class ScriptedModel(BaseHTTPRequestHandler):
    """Replies with a fixed plan: read SKILL.md, run analyze, then answer
    using the numbers printed by the tool."""

    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msgs = body["messages"]
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        assert body["tools"][0]["function"]["name"] == "bash"
        if len(tool_msgs) == 0:
            msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "read_file", "arguments": json.dumps({"path": str(SKILL / "SKILL.md")})}}]}
        elif len(tool_msgs) == 1:
            cmd = f"python3 {SKILL}/scripts/wt.py analyze --topic 'intermittent fasting' --langs pl,cs --quiet"
            msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "c2", "type": "function", "function": {
                "name": "bash", "arguments": json.dumps({"command": cmd})}}]}
        else:
            out = tool_msgs[-1]["content"]
            line = next(l for l in out.splitlines() if l.startswith("- Polish (pl) — growing"))
            pct = line.split(": ", 1)[1].split("%")[0] + "%"
            msg = {"role": "assistant", "content": f"Польська росте швидше: {pct} рік до року; чеська значно "
                                                   f"повільніше. Довіра висока. Перегляди показують цікавість, "
                                                   f"а не готовність платити."}
        payload = json.dumps({"choices": [{"message": msg}], "usage": {"prompt_tokens": 10,
                                                                       "completion_tokens": 5}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def test_agent_loop_and_graders(env, fake_server, tmp_path):
    import agent_eval
    from graders import grade

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ScriptedModel)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        chat = agent_eval.Chat(f"http://127.0.0.1:{httpd.server_address[1]}", "k", "scripted", 0, 0)
        import os
        run_env = dict(os.environ)
        run_env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + run_env.get("PATH", "")
        scenarios = json.loads((SKILL / "evals" / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
        sc = next(s for s in scenarios if s["id"] == "fasting-pl-cs")
        tr = agent_eval.run_scenario(chat, sc, tmp_path / "ws", run_env, max_steps=5, timeout=300, n_turns=1)
    finally:
        httpd.shutdown()
    assert len(tr["turns"]) == 1 and tr["turns"][0]["answer"].startswith("Польська")
    sc1 = dict(sc, checks=[c for c in sc["checks"] if c.get("turn", 1) == 1])
    report = grade(sc1, tr)
    failed = [c for c in report["checks"] if not c["passed"]]
    assert not failed, failed


def test_numbers_grader_flags_invented_figures(tmp_path):
    from graders import numbers_problems
    (tmp_path / "r").mkdir()
    res = {"cells": [{"id": "t1:pl", "label": "pl", "lang": "pl", "error": None,
                      "metrics": {"yoy": {"value": 0.3, "ci": [0.2, 0.4]}, "trend": {}, "spike_excess_share": 0,
                                  "total_views_raw": 1},
                      "confidence": {"reasons": []}, "spikes": {"events": []}}], "comparisons": []}
    (tmp_path / "r" / "results.json").write_text(json.dumps(res))
    assert numbers_problems("grew 30% (90% CI 20-40%)", str(tmp_path)) == []
    assert numbers_problems("grew 55%", str(tmp_path)) == ["55%"]
    assert numbers_problems("the user said 55%", str(tmp_path), extra_ok="55%") == []
