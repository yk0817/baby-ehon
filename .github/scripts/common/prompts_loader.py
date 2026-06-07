"""役ごとのプロンプト文言（system / persona / rubric）を外部 Markdown から読むローダ。

各役の振る舞い（口調・評価観点・制約）を Python を触らずに調整できるよう、文言は
``prompts/<role>/`` の Markdown に外部化する。このモジュールは**読み込みに徹し、
文言自体は一切ハードコードしない**（設計 §3.2 の DoD）。

ディレクトリ構成::

    prompts/
      common/privacy_system.md   # §8.1 共通プライバシー system（全役の先頭に必ず連結）
      <role>/system.md           # 必須。役固有の system プロンプト
      <role>/persona.md          # 任意。ペルソナ（無ければ空文字）
      <role>/rubric.md           # 任意。評価ルーブリック（無ければ空文字）

切替: 環境変数 ``PROMPT_DIR``（既定 ``"prompts"``）でルートを差し替えられる。実験用
ペルソナを別ディレクトリに置いて A/B するため。``env`` を ``Mapping`` で注入できる
ようにし、テストから副作用なく解決できるようにしている。

パス解決: ``prompt_dir`` が絶対パスならそのまま、相対なら本ファイルの隣
（``.github/scripts/<prompt_dir>``）を基準にする。CI の作業ディレクトリに依存しない
ため。

重要（§8.1）: ``privacy_system.md`` は省略不可。全役の system 先頭に必ず連結し、
ファイルが無ければ ``FileNotFoundError`` で明示的に失敗させる。

設計: docs/automation/agent-pipeline.md §3.2 / §8.1
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR_ENV = "PROMPT_DIR"
DEFAULT_PROMPT_DIR = "prompts"

#: 外部化対象の 4 役。daily=既存 Issue 調査・採点、proposer=新案発案・起票、
#: creator=実装し Draft PR、child=1 歳児視点でブラウザ確認し所見（§3.2）。
ROLES: tuple[str, ...] = ("daily", "proposer", "creator", "child")

COMMON_DIR = "common"
PRIVACY_SYSTEM_FILE = "privacy_system.md"
SYSTEM_FILE = "system.md"
PERSONA_FILE = "persona.md"
RUBRIC_FILE = "rubric.md"

# .github/scripts/ を起点にする（このファイルは common/ 配下なので親の親）。
_SCRIPTS_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class RolePrompts:
    """役 1 つ分のプロンプト束（不変）。

    ``system`` は ``privacy_system.md`` を先頭に連結済みの**最終形**。
    呼び出し側はそのまま LLM の system プロンプトに渡せる。
    """

    role: str
    system: str
    persona: str
    rubric: str


def resolve_prompt_dir(
    prompt_dir: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Path:
    """プロンプトのルートディレクトリを絶対パスで解決する。

    優先順位: 引数 ``prompt_dir`` → env ``PROMPT_DIR`` → 既定 ``"prompts"``。
    絶対パスはそのまま、相対パスは ``.github/scripts/`` 基準に解決する。
    """
    source = os.environ if env is None else env
    raw = (
        prompt_dir
        if prompt_dir is not None
        else source.get(PROMPT_DIR_ENV, DEFAULT_PROMPT_DIR)
    )
    path = Path(raw)
    if not path.is_absolute():
        path = _SCRIPTS_ROOT / path
    return path


def _read_required(path: Path) -> str:
    """必須ファイルを読む。無ければ FileNotFoundError（メッセージにパスを明示）。"""
    if not path.is_file():
        raise FileNotFoundError(f"必須プロンプトが見つかりません: {path}")
    return path.read_text(encoding="utf-8")


def _read_optional(path: Path) -> str:
    """任意ファイルを読む。無ければ空文字。"""
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def load_role_prompts(
    role: str,
    *,
    prompt_dir: str | None = None,
    env: Mapping[str, str] | None = None,
) -> RolePrompts:
    """指定役の system / persona / rubric を読み、``RolePrompts`` を返す。

    - ``role`` が ``ROLES`` 以外なら ``ValueError``
    - ``common/privacy_system.md`` と ``<role>/system.md`` は必須（無ければ
      ``FileNotFoundError``）
    - ``persona.md`` / ``rubric.md`` は任意（無ければ空文字）
    - 返り値の ``system`` は ``privacy_system`` を先頭に連結した最終形
    """
    if role not in ROLES:
        raise ValueError(f"未知の役割です: {role!r}（有効: {', '.join(ROLES)}）")

    root = resolve_prompt_dir(prompt_dir, env=env)

    privacy_system = _read_required(root / COMMON_DIR / PRIVACY_SYSTEM_FILE)
    role_system = _read_required(root / role / SYSTEM_FILE)
    persona = _read_optional(root / role / PERSONA_FILE)
    rubric = _read_optional(root / role / RUBRIC_FILE)

    system = f"{privacy_system.rstrip()}\n\n{role_system.lstrip()}"

    return RolePrompts(
        role=role,
        system=system,
        persona=persona,
        rubric=rubric,
    )
