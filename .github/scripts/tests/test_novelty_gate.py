"""issue_proposer のゲート群テスト（TDD: 実装より先に書く・DoD 必須ファイル）。

novelty_gate（重複排除）と backlog_gate（氾濫防止）、self_score_gate（合格ライン）を
ネットワーク / 実 LLM / langgraph 無しで検証する。LLM は fake を注入する。

設計: docs/automation/agent-pipeline.md §5.1 / §5.3 / §5.4 / §4.4
"""

from issue_proposer import nodes

# --- backlog_gate（§5.4） -----------------------------------------------------


class TestBacklogGate:
    def test_skips_when_at_or_above_max(self):
        # Arrange: 未対応 claude-proposed が上限に達している
        state = {"pending_proposed_count": 3, "errors": []}

        # Act
        result = nodes.backlog_gate(state, backlog_max=3)

        # Assert: skip フラグが立ち、理由が errors に残る
        assert result["skip"] is True

    def test_passes_when_below_max(self):
        # Arrange
        state = {"pending_proposed_count": 2, "errors": []}

        # Act
        result = nodes.backlog_gate(state, backlog_max=3)

        # Assert
        assert result["skip"] is False

    def test_skips_when_above_max(self):
        state = {"pending_proposed_count": 5, "errors": []}
        result = nodes.backlog_gate(state, backlog_max=3)
        assert result["skip"] is True

    def test_routing_helper_reports_skip_or_continue(self):
        assert nodes.route_backlog({"skip": True}) == "skip"
        assert nodes.route_backlog({"skip": False}) == "continue"


# --- novelty_gate（§5.4） -----------------------------------------------------


def _idea(title: str, summary: str = "ようす") -> dict:
    return {
        "kind": "feature",
        "title": title,
        "summary": summary,
        "research_basis": ["共同注意"],
        "target_files": ["shared/ehon.js"],
    }


class TestNoveltyGate:
    def test_passes_when_title_is_novel(self):
        # Arrange
        state = {
            "idea": _idea("おとあそび えほん"),
            "existing_open_titles": ["でんしゃ えほん"],
            "recent_closed_titles": ["くるま えほん"],
            "errors": [],
        }

        # Act
        result = nodes.novelty_gate(state)

        # Assert
        assert result["is_duplicate"] is False

    def test_detects_duplicate_against_open_titles(self):
        # Arrange: 既存 open と実質同じタイトル（空白・大小無視で一致）
        state = {
            "idea": _idea("でんしゃ えほん"),
            "existing_open_titles": ["でんしゃえほん"],
            "recent_closed_titles": [],
            "errors": [],
        }

        # Act
        result = nodes.novelty_gate(state)

        # Assert
        assert result["is_duplicate"] is True

    def test_detects_duplicate_against_recent_closed(self):
        # 大小・全半角・空白のゆらぎ（ABC ↔ ＡＢＣ、大小、空白）を正規化で吸収
        state = {
            "idea": _idea("ABC えほん"),
            "existing_open_titles": [],
            "recent_closed_titles": ["ａｂｃえほん"],  # 全角小文字
            "errors": [],
        }
        result = nodes.novelty_gate(state)
        assert result["is_duplicate"] is True

    def test_detects_duplicate_by_containment(self):
        # Arrange: 既存タイトルが生成案タイトルに包含される
        state = {
            "idea": _idea("あたらしい でんしゃ えほん"),
            "existing_open_titles": ["でんしゃ えほん"],
            "recent_closed_titles": [],
            "errors": [],
        }
        result = nodes.novelty_gate(state)
        assert result["is_duplicate"] is True

    def test_routing_retries_until_max_then_skips(self):
        # 重複 & まだ再生成余地あり → retry
        assert (
            nodes.route_novelty(
                {"is_duplicate": True, "novelty_attempts": 0}, max_attempts=2
            )
            == "retry"
        )
        # 重複 & 再生成上限到達 → skip
        assert (
            nodes.route_novelty(
                {"is_duplicate": True, "novelty_attempts": 2}, max_attempts=2
            )
            == "skip"
        )
        # 新規 → 続行
        assert (
            nodes.route_novelty(
                {"is_duplicate": False, "novelty_attempts": 1}, max_attempts=2
            )
            == "continue"
        )


# --- normalize（重複判定の前処理） --------------------------------------------


class TestNormalizeTitle:
    def test_lowercases_and_strips_whitespace(self):
        assert nodes.normalize_title("  デンシャ  EHON ") == nodes.normalize_title(
            "デンシャehon"
        )

    def test_empty_for_blank(self):
        assert nodes.normalize_title("   ") == ""


# --- self_score_gate（§4.4 / §5.3） -------------------------------------------


def _score(total: int, feasibility: int = 20) -> dict:
    return {
        "dev_value": 30,
        "feasibility": feasibility,
        "reusability": 15,
        "a11y_safety": 10,
        "total": total,
    }


class TestSelfScoreGate:
    def test_passes_at_threshold_60(self):
        # Arrange: 合計ちょうど 60、HTML/CSS/JS で完結
        state = {
            "self_score": _score(60),
            "idea": _idea("おとあそび"),
            "html_css_js_only": True,
            "errors": [],
        }

        # Act
        result = nodes.self_score_gate(state, threshold=60)

        # Assert
        assert result["accepted"] is True

    def test_drops_below_threshold(self):
        # Arrange: 59 点
        state = {
            "self_score": _score(59),
            "idea": _idea("おとあそび"),
            "html_css_js_only": True,
            "errors": [],
        }
        # Act
        result = nodes.self_score_gate(state, threshold=60)
        # Assert
        assert result["accepted"] is False

    def test_drops_when_not_html_css_js_only(self):
        # Arrange: 合計は高いが HTML/CSS/JS で完結しない
        state = {
            "self_score": _score(90),
            "idea": _idea("WebGL 3D えほん"),
            "html_css_js_only": False,
            "errors": [],
        }
        # Act
        result = nodes.self_score_gate(state, threshold=60)
        # Assert
        assert result["accepted"] is False

    def test_routing_helper(self):
        assert nodes.route_self_score({"accepted": True}) == "accept"
        assert nodes.route_self_score({"accepted": False}) == "drop"
