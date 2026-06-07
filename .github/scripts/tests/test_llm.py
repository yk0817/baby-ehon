"""llm.py のテスト（TDD: 実装より先に書く）。

設計: docs/automation/agent-pipeline.md §3.1 / §10
- model は env 必須（ハードコードのモデル名を持たない＝DoD）
- base_url / api_key を env から解決し、未設定は明示エラー
- Vision 入力（画像）対応のメッセージ整形
- run 単位のトークン / 時間ガード（MAX_TOKENS_PER_RUN / MAX_RUN_SECONDS）
"""

import pytest

from common import llm


class TestResolveModel:
    def test_returns_env_value_per_role(self):
        env = {"LLM_MODEL_DAILY": "model-x"}
        assert llm.resolve_model("daily", env) == "model-x"

    def test_strips_whitespace(self):
        env = {"LLM_MODEL_CREATOR": "  model-y  "}
        assert llm.resolve_model("creator", env) == "model-y"

    def test_raises_when_env_missing(self):
        # DoD: 既定のモデル名にフォールバックしない（ハードコード禁止）
        with pytest.raises(ValueError):
            llm.resolve_model("proposer", {})

    def test_raises_for_unknown_role(self):
        with pytest.raises(ValueError):
            llm.resolve_model("stranger", {"LLM_MODEL_DAILY": "m"})

    def test_no_hardcoded_model_names_in_source(self):
        # モジュール定数にモデル名らしき文字列が無いこと（env 経由のみ）
        import inspect

        source = inspect.getsource(llm)
        assert "claude-" not in source
        assert "gpt-" not in source


class TestCreateClient:
    def test_raises_without_api_key(self):
        with pytest.raises(ValueError):
            llm.create_client({}, client_factory=lambda **kw: kw)

    def test_passes_base_url_when_set(self):
        env = {"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "https://example/v1"}
        client = llm.create_client(env, client_factory=lambda **kw: kw)
        assert client["base_url"] == "https://example/v1"
        assert client["api_key"] == "k"

    def test_base_url_none_when_unset(self):
        env = {"OPENAI_API_KEY": "k"}
        client = llm.create_client(env, client_factory=lambda **kw: kw)
        assert client["base_url"] is None


class TestBuildMessages:
    def test_text_only(self):
        messages = llm.build_messages("sys", "hello")
        assert messages == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]

    def test_omits_empty_system(self):
        messages = llm.build_messages("", "hi")
        assert messages == [{"role": "user", "content": "hi"}]

    def test_vision_inputs_become_multimodal_content(self):
        messages = llm.build_messages(
            "sys", "見て", image_urls=("data:image/png;base64,AAA",)
        )
        user = messages[-1]
        assert user["role"] == "user"
        assert {"type": "text", "text": "見て"} in user["content"]
        assert any(part["type"] == "image_url" for part in user["content"])


class TestRunBudget:
    def test_check_raises_when_tokens_exceeded(self):
        budget = llm.RunBudget(max_tokens=100)
        budget.add_tokens(100)
        with pytest.raises(llm.BudgetExceededError):
            budget.check()

    def test_check_raises_when_time_exceeded(self):
        clock = iter([0.0, 9999.0])
        budget = llm.RunBudget(max_seconds=10, clock=lambda: next(clock))
        with pytest.raises(llm.BudgetExceededError):
            budget.check()

    def test_under_budget_passes(self):
        budget = llm.RunBudget(max_tokens=100, max_seconds=10, clock=lambda: 0.0)
        budget.add_tokens(50)
        budget.check()  # should not raise


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeUsage:
    def __init__(self, total):
        self.total_tokens = total


class _FakeResponse:
    def __init__(self, content, total_tokens):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage(total_tokens)


class _FakeClient:
    def __init__(self, content="ok", total_tokens=42):
        self._response = _FakeResponse(content, total_tokens)
        self.calls = []

        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                return outer._response

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


class TestChat:
    def test_returns_content_and_uses_resolved_model(self):
        env = {"LLM_MODEL_DAILY": "model-x"}
        client = _FakeClient(content="hi")
        text = llm.chat(client, role="daily", system="s", user="u", env=env)
        assert text == "hi"
        assert client.calls[0]["model"] == "model-x"

    def test_passes_max_tokens(self):
        env = {"LLM_MODEL_DAILY": "m"}
        client = _FakeClient()
        llm.chat(client, role="daily", system="s", user="u", max_tokens=123, env=env)
        assert client.calls[0]["max_tokens"] == 123

    def test_accumulates_budget_from_usage(self):
        env = {"LLM_MODEL_DAILY": "m"}
        client = _FakeClient(total_tokens=42)
        budget = llm.RunBudget()
        llm.chat(client, role="daily", system="s", user="u", env=env, budget=budget)
        assert budget.tokens_used == 42

    def test_budget_checked_before_call(self):
        env = {"LLM_MODEL_DAILY": "m"}
        client = _FakeClient()
        budget = llm.RunBudget(max_tokens=10)
        budget.add_tokens(10)
        with pytest.raises(llm.BudgetExceededError):
            llm.chat(client, role="daily", system="s", user="u", env=env, budget=budget)
        assert client.calls == []  # 呼び出し前に弾く
