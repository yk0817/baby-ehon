"""child_reviewer の純粋ノード / dedupe / format / privacy のテスト（TDD）。

ネットワーク・ブラウザ（Playwright）・実 LLM・langgraph には一切依存しない。
judge は fake 注入、IO は fake オブジェクトで委譲を確認する。

設計: docs/automation/agent-pipeline.md §7 / §8.4 / §8.5 / §2.1
"""

from datetime import datetime, timezone

from child_reviewer import nodes

# --- detect_changed_books（§7.1 / §7.7） --------------------------------------


class TestDetectChangedBooks:
    def test_extracts_book_dirs_from_diff(self):
        # Arrange
        diff = (
            "diff --git a/hikouki/index.html b/hikouki/index.html\n"
            "+++ b/hikouki/index.html\n"
            "diff --git a/densha/theme.css b/densha/theme.css\n"
        )

        # Act
        books = nodes.detect_changed_books(diff)

        # Assert
        assert books == ["densha", "hikouki"]

    def test_excludes_github_docs_git_shared(self):
        # Arrange
        diff = (
            "+++ b/.github/workflows/x.yml\n"
            "+++ b/docs/automation/agent-pipeline.md\n"
            "+++ b/shared/ehon.js\n"
            "+++ b/kuruma/config.js\n"
        )

        # Act
        books = nodes.detect_changed_books(diff)

        # Assert: 絵本ディレクトリのみ残る
        assert books == ["kuruma"]

    def test_filters_to_known_books_when_provided(self):
        # Arrange
        diff = "+++ b/spurious/index.html\n+++ b/hikouki/index.html\n"

        # Act
        books = nodes.detect_changed_books(diff, known_books=["hikouki", "densha"])

        # Assert: known に無い spurious は除外
        assert books == ["hikouki"]

    def test_returns_empty_for_no_book_change(self):
        assert nodes.detect_changed_books("+++ b/README.md\n") == []


# --- extract_closes_issue（§2.1） ---------------------------------------------


class TestExtractClosesIssue:
    def test_parses_closes_keyword(self):
        assert nodes.extract_closes_issue("本文\n\nCloses #21\n") == 21

    def test_parses_fixes_keyword_case_insensitive(self):
        assert nodes.extract_closes_issue("fixes #7") == 7

    def test_returns_none_when_absent(self):
        assert nodes.extract_closes_issue("ただの本文 #notanumber") is None


# --- score_rubric クランプ（§7.4） --------------------------------------------


class TestScoreRubric:
    def test_clamps_out_of_range_values(self):
        # Arrange: score_fn が範囲外を返す
        def score_fn(_text):
            return {"fun": 9, "clarity": -3, "safety": 5, "consistency": 2}

        # Act
        result = nodes.score_rubric({"raw_review": "x"}, score_fn=score_fn)

        # Assert: [0,5] にクランプ、4 軸すべて存在
        assert result["rubric"] == {
            "fun": 5,
            "clarity": 0,
            "safety": 5,
            "consistency": 2,
        }

    def test_parses_inline_scores_from_review_text(self):
        # Arrange: 所見本文に fun=4 等が埋まっている
        review = "良い点 fun=4 clarity=3 safety=5 consistency=4 まとめ"

        # Act
        result = nodes.score_rubric({"raw_review": review})

        # Assert
        assert result["rubric"] == {
            "fun": 4,
            "clarity": 3,
            "safety": 5,
            "consistency": 4,
        }

    def test_missing_axes_default_to_min(self):
        # Arrange: 何も拾えない
        result = nodes.score_rubric({"raw_review": "所見だけで点数なし"})

        # Assert: 全軸 0、欠けなし
        assert result["rubric"] == {
            "fun": 0,
            "clarity": 0,
            "safety": 0,
            "consistency": 0,
        }


# --- format_review（§7.5） ----------------------------------------------------

_FIXED_NOW = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)  # JST 10:00 → 2026-06-09


class TestFormatReview:
    def _state(self):
        return {
            "changed_books": ["hikouki"],
            "rubric": {"fun": 4, "clarity": 3, "safety": 5, "consistency": 4},
            "raw_review": "タップで飛行機が動いて楽しい。",
            "artifact_url": "https://example/artifact",
        }

    def test_leading_two_markers_with_jst_date(self):
        # Act
        result = nodes.format_review(self._state(), now=_FIXED_NOW)
        body = result["rendered_review"]
        lines = body.splitlines()

        # Assert: 先頭 2 行が score / run マーカー、日付は JST 当日
        assert lines[0] == (
            "<!-- child-review-score: fun=4 clarity=3 safety=5 consistency=4 -->"
        )
        assert lines[1] == "<!-- child-review-run: 2026-06-09 -->"

    def test_states_observation_only_not_approval(self):
        # Act
        body = nodes.format_review(self._state(), now=_FIXED_NOW)["rendered_review"]

        # Assert: 所見のみ・Approve しない旨を明記
        assert "所見のみ" in body or "所見" in body
        assert "Approve ではありません" in body
        assert "承認ではありません" in body

    def test_reflects_rubric_and_artifact(self):
        # Act
        body = nodes.format_review(self._state(), now=_FIXED_NOW)["rendered_review"]

        # Assert: ルーブリック値と artifact リンクが反映
        assert "4/5" in body and "3/5" in body and "5/5" in body
        assert "https://example/artifact" in body
        assert "hikouki" in body

    def test_falls_back_to_shelf_when_no_books(self):
        state = {"changed_books": [], "rubric": {}, "raw_review": ""}
        body = nodes.format_review(state, now=_FIXED_NOW)["rendered_review"]
        assert "index.html" in body

    def test_round_trips_with_score_parser(self):
        # Arrange: format → parse でルーブリックが復元できる（共通マーカー仕様）
        from common import score_parser

        body = nodes.format_review(self._state(), now=_FIXED_NOW)["rendered_review"]

        # Act
        parsed = score_parser.parse_child_review_score(body)
        run = score_parser.parse_child_review_run(body)

        # Assert
        assert parsed == {"fun": 4, "clarity": 3, "safety": 5, "consistency": 4}
        assert run == "2026-06-09"


# --- judge（fake Vision 注入） ------------------------------------------------


class TestJudge:
    def test_passes_screenshot_urls_to_judge_fn(self):
        # Arrange
        captured = {}

        def fake_judge(system, user, image_urls):
            captured["images"] = list(image_urls)
            captured["user"] = user
            return "所見テキスト fun=4"

        state = {
            "changed_books": ["hikouki"],
            "screenshots": [
                {
                    "book": "hikouki",
                    "viewport": 320,
                    "phase": "initial",
                    "path": "/t/a.png",
                },
                {
                    "book": "hikouki",
                    "viewport": 768,
                    "phase": "after_tap",
                    "path": "/t/b.png",
                },
            ],
            "code_excerpts": {"hikouki/index.html": "<html>"},
            "errors": [],
        }

        # Act
        result = nodes.judge(state, judge_fn=fake_judge, system="sys")

        # Assert: path が file:// URL 化されて渡る、所見が state に入る
        assert captured["images"] == ["file:///t/a.png", "file:///t/b.png"]
        assert result["raw_review"] == "所見テキスト fun=4"

    def test_records_error_when_judge_raises(self):
        def boom(_s, _u, _i):
            raise RuntimeError("vision down")

        result = nodes.judge({"errors": []}, judge_fn=boom)

        # Assert: 落とさず errors に記録、実値（例外メッセージ）は出さない
        assert result["raw_review"] == ""
        assert any("judge" in e for e in result["errors"])
        assert not any("vision down" in e for e in result["errors"])


# --- privacy_check（§8.6 違反 abort・実値非露出） ------------------------------


class TestPrivacyCheck:
    def test_aborts_on_denylist_hit_without_leaking_value(self):
        # Arrange: 所見本文に denylist の実名が混入
        secret = "やまだはなこ"
        state = {"rendered_review": f"対象児 {secret} が喜んでいた", "errors": []}

        # Act
        result = nodes.privacy_check(state, denylist=[secret])

        # Assert: abort、かつ errors に実値を含めない
        assert result["abort"] is True
        joined = "\n".join(result["errors"])
        assert secret not in joined
        assert nodes.route_privacy(result) == "abort"

    def test_passes_clean_text(self):
        state = {"rendered_review": "対象児が喜んでいた所見", "errors": []}
        result = nodes.privacy_check(state, denylist=["やまだ"])
        assert result["abort"] is False
        assert nodes.route_privacy(result) == "ok"


# --- dedupe（§7.6 当日マーカーで skip） ---------------------------------------


class TestDedupe:
    def test_detects_today_marker(self):
        # Arrange: 当日 child-review-run マーカー付きコメント
        bodies = [
            "別コメント",
            "<!-- child-review-run: 2026-06-09 -->\n所見...",
        ]

        # Act / Assert
        assert nodes.has_today_review_marker(bodies, now=_FIXED_NOW) is True

    def test_ignores_other_day_marker(self):
        bodies = ["<!-- child-review-run: 2026-06-01 -->"]
        assert nodes.has_today_review_marker(bodies, now=_FIXED_NOW) is False

    def test_no_marker_returns_false(self):
        assert nodes.has_today_review_marker(["ただの所見"], now=_FIXED_NOW) is False


# --- post_pr_comment（comment のみ / stage 付与 / dry-run） --------------------


class _FakeIO:
    def __init__(self):
        self.commented = None
        self.labeled = []

    def create_issue_comment(self, number, body):
        self.commented = (number, body)
        return type("C", (), {"html_url": "https://example/comment"})()

    def add_labels(self, number, *labels):
        self.labeled.append((number, labels))


class TestPostPrComment:
    def test_comments_and_labels_target_issue(self):
        # Arrange
        io = _FakeIO()
        state = {
            "pr_number": 99,
            "pr_body": "実装しました。\n\nCloses #21",
            "rendered_review": "所見本文",
        }

        # Act
        result = nodes.post_pr_comment(state, io=io, dry_run=False)

        # Assert: PR にコメント、Closes 先 Issue に stage:child-reviewed のみ付与
        assert io.commented == (99, "所見本文")
        assert io.labeled == [(21, ("stage:child-reviewed",))]
        assert result["posted_comment_url"] == "https://example/comment"

    def test_dry_run_does_not_write(self):
        io = _FakeIO()
        state = {"pr_number": 99, "pr_body": "Closes #21", "rendered_review": "x"}

        result = nodes.post_pr_comment(state, io=io, dry_run=True)

        assert io.commented is None
        assert io.labeled == []
        assert result["posted_comment_url"] is None

    def test_skips_label_when_no_closes(self):
        io = _FakeIO()
        state = {"pr_number": 99, "pr_body": "Closes 無し", "rendered_review": "x"}

        nodes.post_pr_comment(state, io=io, dry_run=False)

        # Assert: コメントはするが label は付けない
        assert io.commented == (99, "x")
        assert io.labeled == []
