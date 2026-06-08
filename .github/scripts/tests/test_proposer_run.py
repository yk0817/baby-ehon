"""issue_proposer.run の補助関数とオフライン dry-run のテスト（TDD）。

langgraph / openai / PyGithub を必要としない部分を検証する。完走 smoke は別途
``DRY_RUN=true python -m issue_proposer.run`` で確認する。

設計: docs/automation/agent-pipeline.md §5
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from issue_proposer import run


class TestTodayJst:
    def test_converts_utc_to_jst_date(self):
        # Arrange: UTC 2026-06-07 16:00 は JST 2026-06-08 01:00
        utc = datetime(2026, 6, 7, 16, 0, tzinfo=timezone.utc)
        # Act / Assert
        assert run.today_jst(utc) == "2026-06-08"

    def test_same_day_when_within_jst(self):
        utc = datetime(2026, 6, 8, 1, 0, tzinfo=timezone.utc)
        assert run.today_jst(utc) == "2026-06-08"


class TestIsTruthy:
    def test_recognizes_truthy_values(self):
        for v in ("1", "true", "TRUE", "yes", "on", " True "):
            assert run._is_truthy(v) is True

    def test_falsey_for_others(self):
        for v in ("", "0", "false", "no", None):
            assert run._is_truthy(v) is False


class TestLoadContextOffline:
    def test_builds_state_without_github(self, tmp_path: Path):
        # Arrange: 絵本ディレクトリ 2 つ（config.js あり）
        (tmp_path / "densha").mkdir()
        (tmp_path / "densha" / "config.js").write_text("x", encoding="utf-8")
        (tmp_path / "kuruma").mkdir()
        (tmp_path / "kuruma" / "config.js").write_text("x", encoding="utf-8")

        # Act: io=None（オフライン）
        state = run.load_context(tmp_path, io=None, backlog_max=3)

        # Assert
        assert state["lineup"] == ["densha", "kuruma"]
        assert state["existing_open_titles"] == []
        assert state["pending_proposed_count"] == 0
        assert state["novelty_attempts"] == 0


class TestRouteLlm:
    def test_routes_score_prompt_to_score_llm(self):
        call = run._route_llm(
            idea_llm=lambda s, u: "IDEA",
            score_llm=lambda s, u: "SCORE",
        )
        assert call("共通ルーブリックで採点", "x") == "SCORE"
        assert call("発案フォーマット", "x") == "IDEA"


class TestMakeIo:
    def test_none_when_offline(self):
        assert run._make_io({"GITHUB_REPOSITORY": "o/r"}, offline=True) is None

    def test_none_when_repo_missing(self, capsys):
        assert run._make_io({}, offline=False) is None
        assert "GITHUB_REPOSITORY" in capsys.readouterr().out


class _FakeIssue:
    def __init__(self, title):
        self.title = title


class _FakeRepo:
    def get_issues(self, state, labels=None):
        if labels:  # claude-proposed の未対応件数
            return [_FakeIssue("p1"), _FakeIssue("p2")]
        if state == "open":
            return [_FakeIssue("でんしゃ えほん")]
        return [_FakeIssue("くるま えほん")]


class _FakeIO:
    def _repo(self):
        return _FakeRepo()


class TestGatherIssueContext:
    def test_collects_titles_and_pending_count(self):
        open_titles, closed_titles, pending = run._gather_issue_context(_FakeIO())
        assert open_titles == ["でんしゃ えほん"]
        assert closed_titles == ["くるま えほん"]
        assert pending == 2

    def test_returns_empty_on_error(self):
        class _Broken:
            def _repo(self):
                raise RuntimeError("boom")

        assert run._gather_issue_context(_Broken()) == ([], [], 0)


class TestReport:
    def test_prints_dry_run_summary(self, capsys):
        state = {
            "idea": {"title": "おとあそび", "kind": "feature"},
            "self_score": {"total": 87},
            "is_duplicate": False,
            "accepted": True,
            "privacy_ok": True,
            "created_issue_url": None,
            "errors": ["メモ1"],
        }
        run._report(state, dry_run=True)
        out = capsys.readouterr().out
        assert "おとあそび" in out
        assert "DRY_RUN のため起票していません" in out
        assert "メモ1" in out


class TestMainOffline:
    def test_offline_dry_run_completes_without_issue(self, capsys):
        # langgraph が無い環境ではスキップ（CI/ローカルとも --with で入る）
        pytest.importorskip("langgraph")

        # Act: オフライン dry-run（OPENAI_API_KEY 無し）
        code = run.main(env={"DRY_RUN": "true"})

        # Assert: 正常終了し、起票せず案・ゲート判定が stdout に出る
        assert code == 0
        out = capsys.readouterr().out
        assert "OFFLINE DRY_RUN" in out
        assert "起票していません" in out
        assert "採用" in out
