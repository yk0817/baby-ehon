"""Daily Investigator の CLI エントリ（``python -m daily_investigator.run``）。

オープン中の全 Issue（または ``ONLY_ISSUE`` で 1 件）を調査・採点し、claude-score
マーカー付きコメントを投稿、対象 Issue に stage:researched を付与する（§4 / §2.1）。

環境変数:

| env | 役割 |
|---|---|
| ``DRY_RUN``         | true で GitHub への書き込みをしない（投稿・ラベル付与なし） |
| ``ONLY_ISSUE``      | 単一 Issue 番号に限定 |
| ``FORCE``           | 当日マーカーがあっても dedupe をスキップさせず強制実行 |
| ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL`` | LLM 接続（§3.1） |
| ``LLM_MODEL_DAILY`` | daily 役のモデル（§3.1） |
| ``BABY_EHON_NAME_DENYLIST`` | プライバシー denylist（§8.2） |
| ``PROMPT_DIR``      | プロンプトのルート切替（§3.2） |
| ``GITHUB_TOKEN`` / ``GITHUB_REPOSITORY`` | GitHub 接続 |

**オフライン dry-run**: ``DRY_RUN`` かつ ``OPENAI_API_KEY`` 未設定なら、LLM ノードは
スタブ文言を返し、format_comment まで通して整形済みコメントを stdout に出す。これで
``DRY_RUN=true ONLY_ISSUE=1 python -m daily_investigator.run`` がネットワーク無しで
完走する（DoD: 整形済みコメントが stdout / API 投稿なし）。

設計: docs/automation/agent-pipeline.md §4 / §2.1 / §3.1
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from common import llm, privacy
from daily_investigator import nodes, prompts

STUB_REPLY = "（stub: LLM未接続）"


def _is_truthy(value: str | None) -> bool:
    """env 文字列を真偽に変換する（"true"/"1"/"yes" を真とする）。"""
    return (value or "").strip().lower() in {"true", "1", "yes", "on"}


@dataclass(frozen=True)
class RunConfig:
    """run のオプション（env から解決した不変設定）。"""

    dry_run: bool
    force: bool
    only_issue: int | None
    has_api_key: bool
    repo: str | None
    denylist: tuple[str, ...] = field(default_factory=tuple)


def load_config(env: Mapping[str, str] | None = None) -> RunConfig:
    """env から ``RunConfig`` を組み立てる。"""
    source = os.environ if env is None else env
    only_raw = source.get("ONLY_ISSUE", "").strip()
    only_issue = int(only_raw) if only_raw.isdigit() else None
    return RunConfig(
        dry_run=_is_truthy(source.get("DRY_RUN")),
        force=_is_truthy(source.get("FORCE")),
        only_issue=only_issue,
        has_api_key=bool(source.get("OPENAI_API_KEY", "").strip()),
        repo=source.get("GITHUB_REPOSITORY", "").strip() or None,
        denylist=privacy.load_denylist(source),
    )


def _stub_chat(client: Any, **kwargs: Any) -> str:
    """オフライン dry-run 用のスタブ chat（ネットワーク不要）。"""
    return STUB_REPLY


def _resolve_chat(config: RunConfig) -> Callable[..., str]:
    """API キーが無い dry-run ではスタブ、それ以外は本物の ``llm.chat``。"""
    if config.dry_run and not config.has_api_key:
        return _stub_chat
    return llm.chat


def _build_client(config: RunConfig, env: Mapping[str, str]) -> Any | None:
    """実 ``llm.chat`` を使うときだけ OpenAI クライアントを生成する。

    スタブ経路（dry-run かつ API キー無し）では chat がクライアントを使わないため
    ``None`` を返す。それ以外は ``OPENAI_API_KEY`` からクライアントを構築する。
    """
    if config.dry_run and not config.has_api_key:
        return None
    return llm.create_client(env)


@dataclass
class _StubIssue:
    """オフライン dry-run 用のダミー Issue（GitHub 未接続でも回す）。"""

    number: int
    title: str = "（stub: オフライン dry-run のダミー Issue）"
    body: str = "（stub: GITHUB_TOKEN/REPOSITORY 未設定のため本文は取得していません）"
    labels: tuple[Any, ...] = ()


def _build_io(config: RunConfig, env: Mapping[str, str]) -> Any | None:
    """GitHub IO を構築する。トークン / repo が無ければ None（dry-run のみ許容）。"""
    token = env.get("GITHUB_TOKEN", "").strip()
    if not config.repo or not token:
        return None
    from common.github_io import GitHubIO

    return GitHubIO(config.repo, token=token, env=env)


def _collect_targets(
    config: RunConfig,
    io: Any | None,
) -> list[Any]:
    """調査対象の Issue オブジェクト列を集める。

    IO があれば実 Issue を取得する。IO が無い（オフライン dry-run）場合は、
    ``ONLY_ISSUE`` 番号のスタブ Issue を 1 件だけ作る。
    """
    if io is None:
        number = config.only_issue if config.only_issue is not None else 1
        return [_StubIssue(number=number)]

    if config.only_issue is not None:
        return [io.get_issue(config.only_issue)]

    repo = io._repo()  # noqa: SLF001 (薄いラッパ越しに open issue を列挙)
    return list(repo.get_issues(state="open"))


def _comment_bodies(io: Any | None, number: int) -> list[str]:
    """対象 Issue の既存コメント本文列を取得する（IO 無しなら空）。"""
    if io is None:
        return []
    return [getattr(c, "body", "") or "" for c in io.list_issue_comments(number)]


def process_issue(
    issue: Any,
    *,
    config: RunConfig,
    io: Any | None,
    chat: Callable[..., str],
    client: Any = None,
    role_prompts: Any,
    env: Mapping[str, str],
    now: datetime | None = None,
) -> dict[str, Any]:
    """1 Issue 分のノードを順に回し、最終 state を返す（graph.py と同じ順序）。

    オフライン / dry-run でも完走するよう、IO 無しでも例外を出さない経路にしている。
    投稿は dry_run のとき行わない。
    """
    bodies = _comment_bodies(io, issue.number)
    state: dict[str, Any] = nodes.load_issue(
        {}, issue=issue, comment_bodies=bodies, now=now
    )

    gate = nodes.dedupe_gate(state, now=now, force=config.force)
    state.update(gate)
    if state.get("skip"):
        return state

    for node in (
        nodes.research_notes,
        nodes.difficulty_estimate,
        nodes.feature_proposal,
        nodes.score_priority,
    ):
        state.update(
            node(state, chat=chat, client=client, env=env, prompts=role_prompts)
        )

    state.update(nodes.format_comment(state, now=now))
    state.update(nodes.privacy_check(state, denylist=config.denylist, env=env))
    if state.get("abort"):
        return state

    if io is not None:
        state.update(nodes.post_comment(state, io=io, dry_run=config.dry_run))
    return state


def main(
    env: Mapping[str, str] | None = None,
    *,
    out=sys.stdout,
) -> int:
    """エントリポイント。0 が正常終了。"""
    source = dict(os.environ if env is None else env)
    config = load_config(source)
    chat = _resolve_chat(config)
    client = _build_client(config, source)
    role_prompts = prompts.load(env=source)
    io = _build_io(config, source)

    if io is None and not config.dry_run:
        print(
            "ERROR: GITHUB_TOKEN/GITHUB_REPOSITORY が未設定です"
            "（実運用には必須。DRY_RUN=true ならオフラインで回せます）",
            file=sys.stderr,
        )
        return 1

    targets = _collect_targets(config, io)
    exit_code = 0
    for issue in targets:
        state = process_issue(
            issue,
            config=config,
            io=io,
            chat=chat,
            client=client,
            role_prompts=role_prompts,
            env=source,
        )
        if state.get("skip"):
            print(
                f"--- Issue #{issue.number}: 当日処理済みのためスキップ ---", file=out
            )
            continue
        if state.get("abort"):
            # 実値は privacy.redact 済みのエラーメッセージのみ出す（§8.6）
            print(
                f"--- Issue #{issue.number}: プライバシー違反で中断（投稿なし） ---",
                file=out,
            )
            for msg in state.get("errors", []):
                print(privacy.redact(msg, config.denylist), file=out)
            exit_code = 1
            continue
        print(f"--- Issue #{issue.number}: 調査コメント ---", file=out)
        print(state.get("rendered_comment", ""), file=out)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
