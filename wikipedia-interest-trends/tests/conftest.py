from __future__ import annotations

import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SKILL = TESTS.parent
sys.path.insert(0, str(SKILL / "scripts"))
sys.path.insert(0, str(TESTS))

from fake_wikimedia import FakeWikimedia  # noqa: E402


@pytest.fixture(scope="session")
def fake_server():
    with FakeWikimedia() as server:
        yield server


@pytest.fixture
def env(fake_server, tmp_path, monkeypatch):
    """Point the tool at the fake APIs with an isolated cache and output dir."""
    for key, value in fake_server.env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("WIKITRENDS_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("WIKITRENDS_OUT", str(tmp_path / "out"))
    monkeypatch.delenv("WIKITRENDS_OFFLINE", raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def run_cli(env, capsys):
    from wikitrends.cli import main

    def _run(*argv: str) -> tuple[int, str, str]:
        code = main(list(argv))
        out, err = capsys.readouterr()
        return code, out, err

    return _run
