"""issue_proposer の LLM / IO ノードのテスト（TDD）。

ideate / draft_issue / privacy_check / create_issue を、fake LLM・fake IO 注入で
検証する。ネットワーク・実 LLM・langgraph には依存しない。

設計: docs/automation/agent-pipeline.md §5.1 / §5.3 / §5.5 / §8
"""

from issue_proposer import nodes

# --- ideate（§5.3、LLM は fake 注入） -----------------------------------------


def _idea_json() -> str:
    return (
        '{"kind": "feature", "title": "おとあそび えほん", '
        '"summary": "タップで音が鳴る", '
        '"research_basis": ["音象徴", "共同注意"], '
        '"target_files": ["shared/ehon.js"], '
        '"html_css_js_only": true}'
    )


def _score_json() -> str:
    return (
        '{"dev_value": 35, "feasibility": 22, "reusability": 18, '
        '"a11y_safety": 13, "total": 88}'
    )


class TestIdeate:
    def test_parses_llm_idea_into_state(self):
        # Arrange: LLM は JSON を返す fake
        def fake_llm(system: str, user: str) -> str:
            return _idea_json()

        state = {
            "lineup": ["densha"],
            "existing_open_titles": [],
            "recent_closed_titles": [],
            "errors": [],
        }

        # Act
        result = nodes.ideate(state, llm=fake_llm)

        # Assert
        assert result["idea"]["kind"] == "feature"
        assert result["idea"]["title"] == "おとあそび えほん"
        assert result["html_css_js_only"] is True
        assert result["novelty_attempts"] == 1

    def test_increments_attempts_on_regenerate(self):
        def fake_llm(system: str, user: str) -> str:
            return _idea_json()

        state = {
            "lineup": [],
            "existing_open_titles": [],
            "recent_closed_titles": [],
            "errors": [],
            "novelty_attempts": 1,
        }
        result = nodes.ideate(state, llm=fake_llm)
        assert result["novelty_attempts"] == 2

    def test_tolerates_json_in_code_fence(self):
        def fake_llm(system: str, user: str) -> str:
            return "```json\n" + _idea_json() + "\n```"

        state = {
            "lineup": [],
            "existing_open_titles": [],
            "recent_closed_titles": [],
            "errors": [],
        }
        result = nodes.ideate(state, llm=fake_llm)
        assert result["idea"]["title"] == "おとあそび えほん"

    def test_records_error_on_invalid_json(self):
        def fake_llm(system: str, user: str) -> str:
            return "これは JSON ではありません"

        state = {
            "lineup": [],
            "existing_open_titles": [],
            "recent_closed_titles": [],
            "errors": [],
        }
        result = nodes.ideate(state, llm=fake_llm)
        assert result["idea"] == {}
        assert result["errors"]


class TestSelfScoreNode:
    def test_parses_llm_score(self):
        def fake_llm(system: str, user: str) -> str:
            return _score_json()

        state = {
            "idea": {"title": "おとあそび", "summary": "x"},
            "errors": [],
        }
        result = nodes.self_score(state, llm=fake_llm)
        assert result["self_score"]["total"] == 88

    def test_records_error_on_invalid_json(self):
        def fake_llm(system: str, user: str) -> str:
            return "スコアなし"

        state = {"idea": {"title": "x"}, "errors": []}
        result = nodes.self_score(state, llm=fake_llm)
        assert result["self_score"] == {}
        assert result["errors"]


# --- draft_issue（§5.5） ------------------------------------------------------


class TestDraftIssue:
    def test_builds_title_and_body_with_marker(self):
        # Arrange
        state = {
            "idea": {
                "kind": "feature",
                "title": "おとあそび えほん",
                "summary": "タップで音が鳴る機能",
                "research_basis": ["音象徴", "共同注意"],
                "target_files": ["shared/ehon.js", "densha/config.js"],
            },
            "errors": [],
        }

        # Act
        result = nodes.draft_issue(state, today="2026-06-08")

        # Assert: タイトルに案名、本文に marker / 種別 / 研究根拠 / 影響ファイル
        assert "おとあそび えほん" in result["issue_title"]
        body = result["issue_body"]
        assert body.startswith("<!-- claude-proposed: 2026-06-08 -->")
        assert "音象徴" in body
        assert "shared/ehon.js" in body
        assert "機能追加" in body  # kind=feature の表示

    def test_new_book_kind_label_in_body(self):
        state = {
            "idea": {
                "kind": "new_book",
                "title": "あめ えほん",
                "summary": "雨の絵本",
                "research_basis": ["コントラスト感受性"],
                "target_files": ["ame/config.js"],
            },
            "errors": [],
        }
        result = nodes.draft_issue(state, today="2026-06-08")
        assert "新しい絵本" in result["issue_body"]


# --- privacy_check（§8） ------------------------------------------------------


class TestPrivacyCheck:
    def test_passes_clean_text(self):
        state = {
            "issue_title": "提案: おとあそび えほん",
            "issue_body": "## 提案\n音が鳴る機能。__NAME__ に呼びかける。",
            "errors": [],
        }
        result = nodes.privacy_check(state, denylist=())
        assert result["privacy_ok"] is True

    def test_aborts_on_denylist_hit_without_leaking_value(self):
        # Arrange: denylist 名が本文に混入
        secret = "ひみつなまえ"
        state = {
            "issue_title": "提案",
            "issue_body": f"{secret} のための絵本",
            "errors": [],
        }
        # Act
        result = nodes.privacy_check(state, denylist=(secret,))
        # Assert: 違反検出、かつ errors に実値が漏れない
        assert result["privacy_ok"] is False
        joined = " ".join(result["errors"])
        assert secret not in joined

    def test_routing_helper(self):
        assert nodes.route_privacy({"privacy_ok": True}) == "ok"
        assert nodes.route_privacy({"privacy_ok": False}) == "abort"


# --- create_issue（§5.1） -----------------------------------------------------


class _FakeIO:
    def __init__(self):
        self.created = None

    def create_issue(self, *, title, body, labels):
        self.created = {"title": title, "body": body, "labels": labels}
        return type("Obj", (), {"html_url": "https://example/issues/99"})()


class TestCreateIssue:
    def test_creates_issue_and_records_url(self):
        # Arrange
        io = _FakeIO()
        state = {
            "issue_title": "提案: おとあそび",
            "issue_body": "本文",
            "errors": [],
        }
        # Act
        result = nodes.create_issue(state, io=io, dry_run=False)
        # Assert
        assert io.created["title"] == "提案: おとあそび"
        assert "claude-proposed" in io.created["labels"]
        assert result["created_issue_url"] == "https://example/issues/99"

    def test_dry_run_does_not_create(self, capsys):
        # Arrange
        io = _FakeIO()
        state = {
            "issue_title": "提案: おとあそび",
            "issue_body": "本文",
            "errors": [],
        }
        # Act
        result = nodes.create_issue(state, io=io, dry_run=True)
        # Assert: 起票せず、URL は None、stdout に出力
        assert io.created is None
        assert result["created_issue_url"] is None
        out = capsys.readouterr().out
        assert "提案: おとあそび" in out
