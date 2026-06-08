"""Proposer のエントリポイント（env 解決・load_context・グラフ実行）。

CI（週次 cron）から ``python -m issue_proposer.run`` で起動する。env から依存を解決し、
リポジトリと GitHub から文脈（ラインナップ・既存タイトル・未対応件数）を集めて初期 state
を作り、``graph.build_graph`` を実行する。

オフライン dry-run（DoD）:
    ``DRY_RUN`` が真かつ ``OPENAI_API_KEY`` 未設定なら、ideate / self_score を
    スタブ化し、GitHub アクセスも行わず、ゲート判定と生成案・採点を stdout に出して
    完走する（**起票しない**）。GITHUB 系 env が未設定でも落ちない。

env:
    DRY_RUN, OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL_PROPOSER,
    BABY_EHON_NAME_DENYLIST, PROMPT_DIR, PROPOSED_BACKLOG_MAX,
    GITHUB_TOKEN, GITHUB_REPOSITORY

設計: docs/automation/agent-pipeline.md §5
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from common import llm as llm_mod
from common import privacy

from . import nodes, prompts

ROLE = "proposer"
DRY_RUN_ENV = "DRY_RUN"
BACKLOG_MAX_ENV = "PROPOSED_BACKLOG_MAX"
REPO_ENV = "GITHUB_REPOSITORY"

# 直近クローズ済みとして読むタイトルの上限（novelty_gate 用の窓）。
RECENT_CLOSED_LIMIT = 30

JST = timezone(timedelta(hours=9))

LLMFn = Callable[[str, str], str]


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def today_jst(now: datetime | None = None) -> str:
    """JST の現在日を ``YYYY-MM-DD`` で返す（マーカー用、§5.5）。"""
    moment = now.astimezone(JST) if now else datetime.now(JST)
    return moment.strftime("%Y-%m-%d")


def _repo_root() -> Path:
    """リポジトリルート（.github/scripts の 2 つ上）を返す。"""
    return Path(__file__).resolve().parents[3]


def _discover_lineup(repo_root: Path) -> list[str]:
    """``*/config.js` を持つ絵本ディレクトリ名を列挙する（決定的順）。"""
    return sorted(p.parent.name for p in repo_root.glob("*/config.js"))


# --- オフライン dry-run 用スタブ ----------------------------------------------


def _stub_idea_llm(_system: str, _user: str) -> str:
    """ideate のスタブ応答（発達研究ベースの素直な 1 案）。"""
    return (
        '{"kind": "feature", '
        '"title": "おとあそび ボタン", '
        '"summary": "各絵本にタップで音象徴オノマトペが鳴るボタンを足す。'
        "誤操作で抜けないチャイルドロックと prefers-reduced-motion に配慮する。"
        'タップ報酬は即時。", '
        '"research_basis": ["音象徴（ブーバ/キキ効果）", '
        '"共同注意を促す呼びかけ", "繰り返しによる予測形成"], '
        '"target_files": ["shared/ehon.js", "shared/ehon.css"], '
        '"html_css_js_only": true}'
    )


def _stub_score_llm(_system: str, _user: str) -> str:
    """self_score のスタブ応答（合格ラインを超える内訳）。"""
    return (
        '{"dev_value": 34, "feasibility": 22, "reusability": 18, '
        '"a11y_safety": 13, "total": 87}'
    )


def _build_llm(env: Mapping[str, str]) -> LLMFn:
    """実 LLM 呼び出し（proposer 役・prompts.py の文言を system に使う）。"""
    role_prompts = prompts.load(env=env)
    client = llm_mod.create_client(env=env)
    budget = llm_mod.RunBudget()

    persona = role_prompts.persona.strip()
    base_system = role_prompts.system
    if persona:
        base_system = f"{base_system}\n\n{persona}"

    def call(extra_system: str, user: str) -> str:
        system = f"{base_system}\n\n{extra_system}" if extra_system else base_system
        return llm_mod.chat(
            client,
            role=ROLE,
            system=system,
            user=user,
            budget=budget,
            env=env,
        )

    return call


def _split_llm(call: LLMFn) -> tuple[LLMFn, LLMFn]:
    """ideate / self_score は同じ呼び出し口を使う（system 末尾の指示で切替）。"""
    return call, call


# --- load_context ------------------------------------------------------------


def load_context(
    repo_root: Path,
    *,
    io: Any | None,
    backlog_max: int,
) -> nodes.ProposerState:
    """初期 state を組み立てる（README/config 文脈は repo から、Issue は GitHub から）。

    ``io`` が None（オフライン dry-run）なら GitHub 由来の項目は空 / 0 にする。
    """
    lineup = _discover_lineup(repo_root)
    existing_open: list[str] = []
    recent_closed: list[str] = []
    pending = 0

    if io is not None:
        existing_open, recent_closed, pending = _gather_issue_context(io)

    return {
        "lineup": lineup,
        "existing_open_titles": existing_open,
        "recent_closed_titles": recent_closed,
        "pending_proposed_count": pending,
        "idea": {},
        "self_score": {},
        "issue_title": "",
        "issue_body": "",
        "created_issue_url": None,
        "errors": [],
        "novelty_attempts": 0,
    }


def _gather_issue_context(io: Any) -> tuple[list[str], list[str], int]:
    """GitHub から open / 直近 closed タイトルと未対応 claude-proposed 件数を集める。

    io は PyGithub の repo を提供する ``GitHubIO`` 互換。例外時は空で返し、起票判断は
    backlog_gate 側に委ねる（落とさない）。
    """
    try:
        repo = io._repo()  # noqa: SLF001  薄いラッパの内部 repo を読み取り専用で使う
    except Exception:  # noqa: BLE001  文脈収集失敗で全体を止めない
        return [], [], 0

    open_titles = [i.title for i in repo.get_issues(state="open")]
    closed_titles = [i.title for i in repo.get_issues(state="closed")][
        :RECENT_CLOSED_LIMIT
    ]
    pending = sum(
        1 for i in repo.get_issues(state="open", labels=[nodes.PROPOSED_MARKER])
    )
    return open_titles, closed_titles, pending


# --- main --------------------------------------------------------------------


def main(env: Mapping[str, str] | None = None) -> int:
    """Proposer を 1 回実行する。戻り値はプロセス終了コード。"""
    source = dict(os.environ if env is None else env)

    dry_run = _is_truthy(source.get(DRY_RUN_ENV))
    has_api_key = bool(source.get(llm_mod.API_KEY_ENV, "").strip())
    offline = dry_run and not has_api_key

    backlog_max = int(source.get(BACKLOG_MAX_ENV, str(nodes.DEFAULT_BACKLOG_MAX)))
    denylist = privacy.load_denylist(source)
    today = today_jst()
    repo_root = _repo_root()

    # IO は (a) オフライン dry-run、(b) GITHUB 未設定 のとき None にして落とさない。
    io = _make_io(source, offline=offline)

    if offline:
        print("=== [OFFLINE DRY_RUN] LLM/GitHub を使わずスタブで完走します ===")
        idea_llm, score_llm = _stub_idea_llm, _stub_score_llm
    else:
        call = _build_llm(source)
        idea_llm, score_llm = _split_llm(call)

    state = load_context(repo_root, io=io, backlog_max=backlog_max)

    from .graph import build_graph  # 遅延 import（langgraph をここでだけ要求）

    # ideate / self_score は LLM が別物に見えるよう、graph には統合 call を渡しつつ
    # offline ではスタブを使い分ける（self_score は self_score ノードが使う）。
    graph = build_graph(
        llm=_route_llm(idea_llm, score_llm),
        io=io,
        today=today,
        denylist=denylist,
        dry_run=dry_run,
        backlog_max=backlog_max,
    )

    final = graph.invoke(state)
    _report(final, dry_run=dry_run)
    return 0


def _route_llm(idea_llm: LLMFn, score_llm: LLMFn) -> LLMFn:
    """system 末尾の指示（採点ルーブリックか発案フォーマットか）で呼び先を振り分ける。

    ideate と self_score は同じ ``llm`` 引数を共有するため、system 文面の特徴語で
    ルーティングする（オフラインのスタブ切替を 1 つの口で両立させるための薄い分配）。
    """

    def call(system: str, user: str) -> str:
        if "ルーブリック" in system or "採点" in system:
            return score_llm(system, user)
        return idea_llm(system, user)

    return call


def _make_io(source: Mapping[str, str], *, offline: bool) -> Any | None:
    """GitHubIO を生成する。オフラインや repo 未設定なら None。"""
    if offline:
        return None
    repo = source.get(REPO_ENV, "").strip()
    if not repo:
        print(f"WARN: {REPO_ENV} 未設定のため GitHub 文脈収集と起票をスキップします")
        return None
    from common.github_io import GitHubIO  # 遅延 import（PyGithub をここでだけ要求）

    return GitHubIO(repo, env=source)


def _report(state: nodes.ProposerState, *, dry_run: bool) -> None:
    """ゲート判定・生成案・採点・結果を stdout にまとめて出す（DoD）。"""
    print("\n=== Proposer 実行結果 ===")
    idea = state.get("idea", {}) or {}
    print(f"案     : {idea.get('title', '(なし)')}（kind={idea.get('kind', '-')}）")
    print(f"自己採点: {state.get('self_score', {}) or '(なし)'}")
    print(f"重複    : {state.get('is_duplicate')}")
    print(f"採用    : {state.get('accepted')}")
    print(f"privacy : {state.get('privacy_ok')}")
    url = state.get("created_issue_url")
    if dry_run:
        print("起票    : DRY_RUN のため起票していません")
    else:
        print(f"起票    : {url or '(起票なし)'}")
    errors = state.get("errors", [])
    if errors:
        print("メモ    :")
        for e in errors:
            print(f"  - {e}")


if __name__ == "__main__":
    raise SystemExit(main())
