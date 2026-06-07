"""baby-ehon 自動化の LLM 呼び出しを 1 箇所に集約するラッパ。

全役（リサーチャー①② / 作成者 / こども）の LLM 呼び出しはここを通す。
OpenAI 公式 SDK の Chat Completions を 1 本だけ叩き、`base_url` と役割別 `model`
を環境変数で差し替えられるようにする。

設計方針（DoD）:
- **モデル名をコードにハードコードしない**。model は ``LLM_MODEL_<ROLE>`` から解決し、
  未設定なら例外（既定のモデル名にフォールバックしない）。
- ``base_url`` / ``api_key`` も env から解決し、未設定は明示エラー。
- Vision 入力（画像）に対応した呼び出し口を持つ（こども用、§7）。
- run 単位のトークン / 時間ガード（``MAX_TOKENS_PER_RUN`` / ``MAX_RUN_SECONDS``、§10）。

設計: docs/automation/agent-pipeline.md §3.1 / §10
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# --- env キー -----------------------------------------------------------------

BASE_URL_ENV = "OPENAI_BASE_URL"
API_KEY_ENV = "OPENAI_API_KEY"

# 役割 → model を解決する env 変数名（§3.1）。文言（モデル名）はここに持たない。
MODEL_ENV_BY_ROLE: dict[str, str] = {
    "daily": "LLM_MODEL_DAILY",
    "proposer": "LLM_MODEL_PROPOSER",
    "creator": "LLM_MODEL_CREATOR",
    "child": "LLM_MODEL_CHILD",
}

# --- run 単位のガード（§10） --------------------------------------------------

MAX_TOKENS_PER_RUN = 500_000
MAX_RUN_SECONDS = 1500
DEFAULT_MAX_TOKENS = 4096  # 1 呼び出しの既定上限。ノード側で上書きする


class LLMError(RuntimeError):
    """LLM 呼び出し関連の基底例外。"""


class BudgetExceededError(LLMError):
    """run 単位のトークン / 時間上限を超過した。"""


def resolve_model(role: str, env: Mapping[str, str] | None = None) -> str:
    """役割名から model を env 経由で解決する。

    未知の役割、または対応する ``LLM_MODEL_<ROLE>`` が未設定なら ``ValueError``。
    既定のモデル名にはフォールバックしない（ハードコード禁止）。
    """
    source = os.environ if env is None else env
    try:
        var = MODEL_ENV_BY_ROLE[role]
    except KeyError:
        valid = sorted(MODEL_ENV_BY_ROLE)
        raise ValueError(f"未知の役割: {role!r}（{valid} のいずれか）") from None
    model = source.get(var, "").strip()
    if not model:
        raise ValueError(f"環境変数 {var} が未設定です（役割 {role!r} の model）")
    return model


def create_client(
    env: Mapping[str, str] | None = None,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> Any:
    """OpenAI SDK クライアントを生成する。

    ``OPENAI_API_KEY`` は必須。``OPENAI_BASE_URL`` は未設定なら ``None``（SDK 既定）。
    ``client_factory`` を渡すとそれを使う（テスト用に SDK 依存を切り離す）。
    """
    source = os.environ if env is None else env
    api_key = source.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise ValueError(f"環境変数 {API_KEY_ENV} が未設定です")
    base_url = source.get(BASE_URL_ENV, "").strip() or None

    if client_factory is not None:
        return client_factory(api_key=api_key, base_url=base_url)

    from openai import OpenAI  # 遅延 import（テストは SDK 不要）

    return OpenAI(api_key=api_key, base_url=base_url)


def build_messages(
    system: str,
    user: str,
    *,
    image_urls: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Chat Completions 用の messages を組み立てる。

    ``image_urls`` があるときは user メッセージをマルチモーダル content にする（Vision）。
    """
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})

    if image_urls:
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for url in image_urls:
            content.append({"type": "image_url", "image_url": {"url": url}})
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": user})

    return messages


@dataclass
class RunBudget:
    """run 単位のトークン / 経過時間の上限ガード（§10）。"""

    max_tokens: int = MAX_TOKENS_PER_RUN
    max_seconds: int = MAX_RUN_SECONDS
    tokens_used: int = 0
    clock: Callable[[], float] = time.monotonic
    _start: float = field(default=0.0, init=False)

    def __post_init__(self) -> None:
        self._start = self.clock()

    def elapsed(self) -> float:
        return self.clock() - self._start

    def add_tokens(self, n: int) -> None:
        self.tokens_used += max(0, n)

    def check(self) -> None:
        """上限超過なら ``BudgetExceededError``。LLM 呼び出し直前に通す。"""
        if self.tokens_used >= self.max_tokens:
            raise BudgetExceededError(
                f"トークン上限超過: {self.tokens_used} >= {self.max_tokens}"
            )
        elapsed = self.elapsed()
        if elapsed >= self.max_seconds:
            raise BudgetExceededError(
                f"実行時間上限超過: {elapsed:.0f}s >= {self.max_seconds}s"
            )


def chat(
    client: Any,
    *,
    role: str,
    system: str,
    user: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    image_urls: Sequence[str] = (),
    budget: RunBudget | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """役割 model で Chat Completions を 1 回叩き、本文テキストを返す。

    ``budget`` を渡すと呼び出し前に上限チェックし、応答後に usage を加算する。
    """
    model = resolve_model(role, env)
    if budget is not None:
        budget.check()

    messages = build_messages(system, user, image_urls=image_urls)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
    )

    if budget is not None:
        usage = getattr(response, "usage", None)
        total = getattr(usage, "total_tokens", 0) or 0
        budget.add_tokens(int(total))

    return response.choices[0].message.content
