"""End-to-end: the real CLI against the fake Wikimedia server, whose true
trends are known (see fake_wikimedia.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fake_wikimedia import Handler

pypdf = pytest.importorskip("pypdf")
pytest.importorskip("matplotlib")
pytest.importorskip("reportlab")


def _results(out: str) -> tuple[dict, Path]:
    line = next(l for l in out.splitlines() if l.strip().startswith("results:"))
    path = Path(line.split("results:", 1)[1].strip())
    return json.loads(path.read_text(encoding="utf-8")), path.parent


def _pdf_text(path: Path) -> tuple[int, str]:
    reader = pypdf.PdfReader(str(path))
    return len(reader.pages), "\n".join(p.extract_text() for p in reader.pages)


def _cell(res: dict, lang: str, topic: str = "t1") -> dict:
    return next(c for c in res["cells"] if c["id"] == f"{topic}:{lang}")


def test_example1_compare_two_languages(run_cli):
    code, out, err = run_cli("analyze", "--topic", "intermittent fasting", "--langs", "pl,cs", "--pdf")
    assert code == 0, err
    res, folder = _results(out)
    pl, cs = _cell(res, "pl"), _cell(res, "cs")
    # ground truth: pl +45%/yr, cs +3%/yr
    assert 0.40 < pl["metrics"]["yoy"]["value"] < 0.52 and pl["metrics"]["direction"] == "growing"
    assert pl["confidence"]["grade"] == "HIGH"
    assert cs["metrics"]["yoy"]["value"] < 0.12
    comp = res["comparisons"][0]
    assert comp["winner"] == "t1:pl" and comp["ci_pp"][0] > 20
    # the injected desktop-only burst is found and classified
    ev = pl["spikes"]["events"][0]
    assert ev["peak_day"] == "2025-03-14" and ev["kind"] == "bot-like"
    assert cs["spikes"]["events"][0]["kind"] == "event-like"
    # the whole pl.wikipedia shrinks 6%/yr, so relative growth is higher
    assert pl["metrics"]["project_yoy"] == pytest.approx(-0.06, abs=0.01)
    assert pl["metrics"]["yoy_normalized"]["value"] > pl["metrics"]["yoy"]["value"]
    assert pl["articles"][0]["title"] == "Post przerywany" and pl["articles"][0]["redirects"] == 1
    pages, text = _pdf_text(folder / "report.pdf")
    assert pages == 1
    assert "Intermittent fasting" in text and "Key findings" in text
    for name in ("trend.png", "growth.png", "monthly.csv", "summary.md", "report.md"):
        assert (folder / name).exists(), name
    assert "Findings (quote these" in out


def test_example2_single_language_trust(run_cli):
    code, out, err = run_cli("analyze", "--topic", "uk:Астрономія", "--langs", "uk", "--lang", "uk", "--pdf")
    assert code == 0, err
    res, folder = _results(out)
    uk = _cell(res, "uk")
    assert 0.07 < uk["metrics"]["yoy"]["value"] < 0.17  # truth +12%/yr
    assert uk["metrics"]["direction"] in ("growing", "likely growing")
    assert uk["confidence"]["grade"] in ("HIGH", "MEDIUM")
    assert res["ranking"] is None and res["comparisons"] == []
    pages, text = _pdf_text(folder / "report.pdf")
    assert pages == 1 and "Ключові висновки" in text and "Астрономія" in text


def test_example3_basket_many_languages_and_report(run_cli):
    code, out, err = run_cli(
        "analyze", "--basket", "Q1860", "en:English as a second or foreign language", "name=Learning English",
        "--langs", "de,pl,uk,es,tr,fr", "--lang", "uk")
    assert code == 0, err
    res, folder = _results(out)
    assert res["ranking"]["dimension"] == "language"
    tr = _cell(res, "tr")
    assert any(f["code"] == "incomplete_basket" for f in tr["flags"])
    uk = _cell(res, "uk")
    assert len(uk["articles"]) == 2
    ranks = [r["cell"] for r in res["ranking"]["rows"]]
    # uk (+18%) and tr (+12%) grow fastest in the synthetic world
    assert ranks.index("t1:uk") < ranks.index("t1:de")
    assert (folder / "opportunity.png").exists()

    summary = ("Найсильніший сигнал — українська: +18% р/р. Турецька теж росте, але кошик неповний.")
    code, out, err = run_cli("report", str(folder), "--lang", "uk", "--summary", summary, "--title",
                             "Вивчення англійської: які аудиторії дослідити далі")
    assert code == 0
    assert "NUMBER CHECK" in out or "number check" in out
    pages, text = _pdf_text(folder / "report.pdf")
    assert pages == 1 and "Вивчення англійської" in text


def test_report_strict_rejects_invented_numbers(run_cli):
    code, out, _ = run_cli("analyze", "--topic", "intermittent fasting", "--langs", "pl,cs")
    res, folder = _results(out)
    code, out, _ = run_cli("report", str(folder), "--summary", "Polish interest grew 93% last year.", "--strict")
    assert code == 2
    assert "93%" in out and not (folder / "report.pdf").exists()
    good = f"Polish interest grew {res['cells'][0]['metrics']['yoy']['value'] * 100:.0f}% last year."
    code, out, _ = run_cli("report", str(folder), "--summary", good, "--strict")
    assert code == 0 and (folder / "report.pdf").exists()


def test_new_article_is_not_reported_as_growth(run_cli):
    code, out, _ = run_cli("analyze", "--topic", "intermittent fasting", "--langs", "pl,uk")
    res, _ = _results(out)
    uk = _cell(res, "uk")
    assert uk["metrics"]["direction"] == "new-article"
    assert uk["confidence"]["grade"] == "LOW"
    assert res["comparisons"] == []  # nothing valid to compare against
    assert "new article" in out


def test_rank_reweighting_without_refetch(run_cli):
    code, out, _ = run_cli("analyze", "--basket", "Q1860", "name=English", "--langs", "en,uk,tr")
    res, folder = _results(out)
    assert res["ranking"]["rows"][0]["cell"] != "t1:en"  # en is big but shrinking
    n_before = len(Handler.requests_log)
    code, out, _ = run_cli("rank", str(folder), "--weights", "size-first")
    assert code == 0 and "1. en" in out
    assert len(Handler.requests_log) == n_before
    saved = json.loads((folder / "results.json").read_text(encoding="utf-8"))
    assert saved["ranking"]["weights"]["reach"] == 0.6


def test_cache_makes_follow_ups_cheap(run_cli):
    run_cli("analyze", "--topic", "Astronomy", "--langs", "uk,pl", "--no-charts")
    code, out, _ = run_cli("analyze", "--topic", "Astronomy", "--langs", "uk,pl", "--no-charts")
    res, _ = _results(out)
    assert res["fetch"]["requests"] == 0
    # longer history: only the missing earlier year is downloaded (5 series + 2 project aggregates)
    code, out, _ = run_cli("analyze", "--topic", "Astronomy", "--langs", "uk,pl", "--months", "36", "--no-charts")
    res, _ = _results(out)
    assert 0 < res["fetch"]["requests"] <= 8
    assert res["cells"][0]["metrics"]["trend"]["months"] == 36


def test_topics_within_one_language(run_cli):
    code, out, _ = run_cli("analyze", "--topic", "Astronomy", "--topic", "intermittent fasting", "--langs", "uk",
                           "--no-charts")
    res, _ = _results(out)
    assert res["ranking"]["dimension"] == "topic"
    labels = {c["label"] for c in res["cells"]}
    assert labels == {"Astronomy", "Intermittent fasting"}


def test_ambiguous_topic_warns_with_alternatives(run_cli):
    code, out, _ = run_cli("resolve", "--topic", "Mercury", "--langs", "en,uk")
    assert code == 0
    assert "ambiguous" in out and "alternative" in out
    assert "uk: Меркурій" in out


def test_missing_language_article_and_unknown_topic(run_cli):
    code, out, err = run_cli("analyze", "--topic", "Mercury (element)", "--langs", "uk,en", "--no-charts")
    assert code == 0
    res, _ = _results(out)
    assert _cell(res, "uk")["error"]
    code, out, err = run_cli("analyze", "--topic", "zzqx nonexistent", "--langs", "en")
    assert code == 2 and "nothing found" in err


def test_bad_inputs_give_actionable_errors(run_cli):
    code, _, err = run_cli("analyze", "--topic", "Astronomy", "--langs", "Polish language")
    assert code == 2 and "language code" in err
    code, _, err = run_cli("analyze", "--topic", "Astronomy", "--langs", "uk", "--start", "2026-05", "--end", "2025-01")
    assert code == 2 and "after" in err
    code, _, err = run_cli("analyze", "--langs", "uk")
    assert code == 2


def test_views_history_cache_doctor(run_cli):
    code, out, _ = run_cli("views", "uk:Астрономія", "--months", "3")
    assert code == 0 and out.count("\n") == 5 and "date,views" in out
    run_cli("analyze", "--topic", "Astronomy", "--langs", "uk", "--no-charts")
    code, out, _ = run_cli("history")
    assert "Astronomy" in out
    code, out, _ = run_cli("cache", "info")
    assert '"series"' in out
    code, out, _ = run_cli("doctor")
    assert code == 0 and "all good" in out


def test_offline_mode_uses_cache_only(run_cli, monkeypatch):
    run_cli("analyze", "--topic", "Astronomy", "--langs", "uk", "--no-charts")
    monkeypatch.setenv("WIKITRENDS_OFFLINE", "1")
    code, out, _ = run_cli("analyze", "--topic", "Astronomy", "--langs", "uk", "--no-charts")
    assert code == 0
    code, out, err = run_cli("analyze", "--topic", "Astronomy", "--langs", "de", "--no-charts")
    assert code == 3 and "offline" in err


def test_pdf_stays_one_page_under_pressure(run_cli):
    code, out, _ = run_cli("analyze", "--basket", "Q1860", "Q900002",
                           "--langs", "en,de,pl,uk,es,tr,fr,cs")
    res, folder = _results(out)
    long_text = " ".join(["This is a long executive summary sentence about the audiences."] * 40)
    rec = "\n".join(f"- step {i}: validate the audience with a landing page test" for i in range(12))
    code, out, _ = run_cli("report", str(folder), "--summary", long_text, "--recommendation", rec)
    assert code == 0
    pages, text = _pdf_text(folder / "report.pdf")
    assert pages == 1


def test_request_budget_trims_redirects(run_cli):
    code, out, _ = run_cli("analyze", "--topic", "intermittent fasting", "--langs", "en,pl", "--max-requests", "6",
                           "--no-charts")
    assert code == 0
    res, _ = _results(out)
    assert any("request budget" in w for w in res["warnings"])
    assert all(a["redirects"] == 0 for c in res["cells"] for a in c["articles"])
    assert any(f["code"] == "redirects_truncated" for c in res["cells"] for f in c["flags"])


def test_basket_without_name_keeps_every_item(run_cli):
    # regression: the first argument used to be taken as the name, silently dropping an article
    code, out, _ = run_cli("analyze", "--basket", "English language", "English as a second or foreign language",
                           "--langs", "uk,pl", "--no-charts")
    assert code == 0
    res, _ = _results(out)
    topic = res["resolution"]["topics"][0]
    assert [i["qid"] for i in topic["items"]] == ["Q1860", "Q900002"]
    assert topic["label"] == "English +1"
    assert len(res["cells"][0]["articles"]) == 2
