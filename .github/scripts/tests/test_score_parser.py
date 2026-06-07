"""score_parser.py のテスト（TDD: 実装より先に書く）。

コメント本文に埋め込まれた機械可読マーカーを抽出する。
設計: docs/automation/agent-pipeline.md §4.3 / §7.5

マーカー仕様:
- <!-- claude-score: 87 -->                                       → int
- <!-- claude-run: 2026-05-25 -->                                 → 日付文字列
- <!-- child-review-score: fun=4 clarity=3 safety=5 consistency=4 --> → dict[str, int]
- <!-- child-review-run: 2026-05-25 -->                           → 日付文字列
"""

from common import score_parser


class TestParseClaudeScore:
    def test_extracts_int(self):
        # Arrange
        body = "<!-- claude-score: 87 -->\n## 調査"
        # Act / Assert
        assert score_parser.parse_claude_score(body) == 87

    def test_none_when_marker_absent(self):
        assert score_parser.parse_claude_score("## 調査だけ") is None

    def test_tolerates_whitespace_variants(self):
        assert score_parser.parse_claude_score("<!--claude-score:87-->") == 87

    def test_invalid_non_numeric_returns_none(self):
        assert score_parser.parse_claude_score("<!-- claude-score: high -->") is None

    def test_picks_first_marker_when_multiple(self):
        body = "<!-- claude-score: 70 -->\n<!-- claude-score: 90 -->"
        assert score_parser.parse_claude_score(body) == 70


class TestParseClaudeRun:
    def test_extracts_date(self):
        assert (
            score_parser.parse_claude_run("<!-- claude-run: 2026-05-25 -->")
            == "2026-05-25"
        )

    def test_none_when_absent(self):
        assert score_parser.parse_claude_run("no marker") is None

    def test_tolerates_no_spaces(self):
        assert (
            score_parser.parse_claude_run("<!--claude-run:2026-05-25-->")
            == "2026-05-25"
        )


class TestParseChildReviewScore:
    def test_extracts_dict(self):
        body = "<!-- child-review-score: fun=4 clarity=3 safety=5 consistency=4 -->"
        assert score_parser.parse_child_review_score(body) == {
            "fun": 4,
            "clarity": 3,
            "safety": 5,
            "consistency": 4,
        }

    def test_none_when_absent(self):
        assert score_parser.parse_child_review_score("no marker") is None

    def test_tolerates_extra_whitespace(self):
        body = "<!--child-review-score:  fun=4   clarity=3  safety=5 consistency=4  -->"
        assert score_parser.parse_child_review_score(body) == {
            "fun": 4,
            "clarity": 3,
            "safety": 5,
            "consistency": 4,
        }

    def test_ignores_non_numeric_pairs(self):
        body = "<!-- child-review-score: fun=4 clarity=high safety=5 -->"
        assert score_parser.parse_child_review_score(body) == {"fun": 4, "safety": 5}

    def test_none_when_no_valid_pairs(self):
        assert (
            score_parser.parse_child_review_score("<!-- child-review-score:  -->")
            is None
        )


class TestParseChildReviewRun:
    def test_extracts_date(self):
        assert (
            score_parser.parse_child_review_run("<!-- child-review-run: 2026-05-25 -->")
            == "2026-05-25"
        )

    def test_none_when_absent(self):
        assert score_parser.parse_child_review_run("nothing here") is None


class TestLatestClaudeScore:
    def test_picks_latest_by_created_at(self):
        # Arrange: (本文, created_at) のシーケンス。順不同で渡す
        comments = [
            ("<!-- claude-score: 70 -->", "2026-05-20"),
            ("<!-- claude-score: 90 -->", "2026-05-25"),
            ("コメント（マーカー無し）", "2026-05-22"),
        ]
        # Act / Assert
        assert score_parser.latest_claude_score(comments) == 90

    def test_skips_comments_without_marker(self):
        comments = [
            ("マーカー無し", "2026-05-30"),
            ("<!-- claude-score: 55 -->", "2026-05-25"),
        ]
        assert score_parser.latest_claude_score(comments) == 55

    def test_none_when_no_marker_anywhere(self):
        comments = [("a", "2026-05-01"), ("b", "2026-05-02")]
        assert score_parser.latest_claude_score(comments) is None

    def test_empty_returns_none(self):
        assert score_parser.latest_claude_score([]) is None


class TestLatestChildReviewScore:
    def test_picks_latest_by_created_at(self):
        comments = [
            (
                "<!-- child-review-score: fun=1 clarity=1 safety=1 consistency=1 -->",
                "2026-05-20",
            ),
            (
                "<!-- child-review-score: fun=4 clarity=3 safety=5 consistency=4 -->",
                "2026-05-25",
            ),
        ]
        assert score_parser.latest_child_review_score(comments) == {
            "fun": 4,
            "clarity": 3,
            "safety": 5,
            "consistency": 4,
        }

    def test_none_when_absent(self):
        assert (
            score_parser.latest_child_review_score([("no marker", "2026-05-25")])
            is None
        )
