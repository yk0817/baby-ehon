"""Weekly Implementer のエントリポイント（env 解決・文脈収集・グラフ実行）。

CI（週次 cron）から ``python -m weekly_implementer.run`` で起動する。env から依存を
解決し、GitHub から open Issue とコメント（claude-score 抽出用）を集めて初期 state を
作り、``graph.build_graph`` を実行する。

オフライン dry-run（DoD）:
    ``DRY_RUN`` が真かつ ``OPENAI_API_KEY`` 未設定なら、plan_change / generate_patch を
    スタブ化し、git / PR / workflow 操作を一切行わず、選定 Issue・変更計画・対象ファイル
    を stdout に出して完走する（**PR を作らない**）。GITHUB 系 env が未設定でも、
    候補取得をスタブ / 空にして落とさない。

env:
    DRY_RUN, OPENAI_API_KEY, OPENAI_BASE_URL, LLM_MODEL_CREATOR,
    BABY_EHON_NAME_DENYLIST, PROMPT_DIR, GITHUB_TOKEN, GITHUB_REPOSITORY

設計: docs/automation/agent-pipeline.md §6
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from common import llm as llm_mod
from common import privacy, repo_reader
from common.gh_cli import run_gh

from . import nodes, prompts

ROLE = "creator"
DRY_RUN_ENV = "DRY_RUN"
REPO_ENV = "GITHUB_REPOSITORY"

LLMFn = Callable[[str, str], str]


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _repo_root() -> Path:
    """リポジトリルート（.github/scripts の 2 つ上）を返す。"""
    return Path(__file__).resolve().parents[3]


# --- オフライン dry-run 用スタブ ----------------------------------------------


def _stub_plan_llm(_system: str, _user: str) -> str:
    """plan_change のスタブ応答（実装しない・形だけの変更計画）。"""
    return (
        "- shared/ehon.css: タップ報酬のアニメーションに prefers-reduced-motion 配慮を追加\n"
        "- （DRY_RUN スタブのため実際の変更は行いません）"
    )


def _stub_generate_llm(_system: str, _user: str) -> str:
    """generate_patch のスタブ応答（パッチを作らず空ブロックにして書き込み回避）。"""
    return "（DRY_RUN スタブ: ファイルブロックを生成しません）"


# generate_patch は全ファイル全文を出すうえ、gpt-5 系は推論トークンも
# max_completion_tokens に含むため、既定 4096 では本文が空/截断になりやすい。
# 役ごとに十分な上限を与える（plan は計画のみなので控えめ）。
PLAN_MAX_TOKENS = 8000
GENERATE_MAX_TOKENS = 32000


def _build_llm(
    env: Mapping[str, str],
    *,
    client: Any | None = None,
    budget: Any | None = None,
    max_tokens: int = llm_mod.DEFAULT_MAX_TOKENS,
) -> LLMFn:
    """実 LLM 呼び出し（creator 役・prompts.py の文言を system に使う）。

    ``client`` / ``budget`` を渡せば共有する（plan と generate で 1 接続・1 予算）。
    ``max_tokens`` は 1 呼び出しの出力上限（generate は大きめにする）。
    """
    role_prompts = prompts.load(env=env)
    client = client if client is not None else llm_mod.create_client(env=env)
    budget = budget if budget is not None else llm_mod.RunBudget()

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
            max_tokens=max_tokens,
            budget=budget,
            env=env,
        )

    return call


# --- GitHub 文脈収集 ----------------------------------------------------------


def _gather_issue_state(io: Any) -> nodes.WeeklyState:
    """open Issue とコメント（claude-score 抽出用）を集めて初期 state を組む。

    list_open_issues → collect_scores を I/O ありで実行した結果に相当する state を返す。
    io が None（オフライン / repo 未設定）なら空候補で返す。
    """
    base_state: nodes.WeeklyState = {"candidate_issues": [], "errors": []}
    if io is None:
        return base_state

    try:
        repo = io._repo()  # noqa: SLF001  薄いラッパの内部 repo を読み取り専用で使う
        issues = list(repo.get_issues(state="open"))
    except Exception:  # noqa: BLE001
        # 収集に失敗しても落とさず空候補で返す。select_top が「approved なし」で skip する。
        return base_state

    listed = nodes.list_open_issues(base_state, issues=issues)

    comments_by_issue: dict[int, list[tuple[str, Any]]] = {}
    for issue in listed.get("candidate_issues", []):
        number = int(issue["number"])
        try:
            comments = [
                (c.body or "", c.created_at)
                for c in repo.get_issue(number).get_comments()
            ]
        except Exception:  # noqa: BLE001  個別 Issue のコメント取得失敗は無視
            comments = []
        comments_by_issue[number] = comments

    scored = nodes.collect_scores(listed, comments_by_issue=comments_by_issue)
    return {**listed, **scored}


def _make_io(source: Mapping[str, str], *, offline: bool) -> Any | None:
    """GitHubIO を生成する。オフラインや repo 未設定なら None。"""
    if offline:
        return None
    repo = source.get(REPO_ENV, "").strip()
    if not repo:
        print(f"WARN: {REPO_ENV} 未設定のため GitHub 文脈収集・PR 作成をスキップします")
        return None
    from common.github_io import GitHubIO  # 遅延 import（PyGithub をここでだけ要求）

    return GitHubIO(repo, env=source)


# --- I/O アダプタ（git / PR / workflow） --------------------------------------


class _GitCli:
    """git 操作の薄い subprocess ラッパ（CI 本番用）。テストでは fake を注入する。"""

    def __init__(self, repo_root: Path) -> None:
        self._cwd = str(repo_root)

    def _run(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self._cwd, check=True)

    def create_branch(self, name: str) -> None:
        self._run("checkout", "-B", name)

    def add_all(self) -> None:
        self._run("add", "-A")

    def commit(self, message: str) -> None:
        self._run("commit", "-m", message)

    def push(self, name: str) -> None:
        self._run("push", "-u", "origin", name)


def _make_pr_runner(repo: str) -> Callable[..., dict[str, Any]]:
    """``gh pr create --draft`` で PR を作り、再 read で isDraft を確認して返す。"""

    def run(
        *, title: str, body: str, head: str, base: str, draft: bool
    ) -> dict[str, Any]:
        args = [
            "pr",
            "create",
            "--title",
            title,
            "--body",
            body,
            "--head",
            head,
            "--base",
            base,
            "--repo",
            repo,
        ]
        if draft:
            args.append("--draft")
        created = run_gh(args)
        url = (created.stdout or "").strip().splitlines()[-1] if created.stdout else ""

        import json

        viewed = run_gh(
            ["pr", "view", url, "--repo", repo, "--json", "number,isDraft,url"]
        )
        data = json.loads(viewed.stdout)
        return {
            "url": data.get("url", url),
            "number": data.get("number"),
            "isDraft": data.get("isDraft", False),
        }

    return run


def _make_workflow_runner(repo: str) -> Callable[[str, dict[str, str]], Any]:
    """``gh workflow run <file> -f k=v`` を実行する runner（§6.5）。"""

    def run(workflow_file: str, inputs: dict[str, str]) -> Any:
        args = ["workflow", "run", workflow_file, "--repo", repo]
        for key, value in inputs.items():
            args.extend(["-f", f"{key}={value}"])
        return run_gh(args)

    return run


def _make_writer(repo_root: Path) -> Callable[[str, str], None]:
    """相対パスにファイル内容を書き込む writer（apply_patches 用）。"""

    def write(rel_path: str, contents: str) -> None:
        target = repo_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8")

    return write


# --- main --------------------------------------------------------------------


def main(env: Mapping[str, str] | None = None) -> int:
    """Weekly Implementer を 1 回実行する。戻り値はプロセス終了コード。"""
    source = dict(os.environ if env is None else env)

    dry_run = _is_truthy(source.get(DRY_RUN_ENV))
    has_api_key = bool(source.get(llm_mod.API_KEY_ENV, "").strip())
    offline = dry_run and not has_api_key

    denylist = privacy.load_denylist(source)
    repo_root = _repo_root()
    repo = source.get(REPO_ENV, "").strip()

    io = _make_io(source, offline=offline)

    if offline:
        print("=== [OFFLINE DRY_RUN] LLM/GitHub を使わずスタブで完走します ===")
        plan_llm, generate_llm = _stub_plan_llm, _stub_generate_llm
    else:
        # client / budget を共有しつつ、generate だけ出力上限を大きくする。
        shared_client = llm_mod.create_client(env=source)
        shared_budget = llm_mod.RunBudget()
        plan_llm = _build_llm(
            source,
            client=shared_client,
            budget=shared_budget,
            max_tokens=PLAN_MAX_TOKENS,
        )
        generate_llm = _build_llm(
            source,
            client=shared_client,
            budget=shared_budget,
            max_tokens=GENERATE_MAX_TOKENS,
        )

    state = _gather_issue_state(io)

    from .graph import build_graph  # 遅延 import（langgraph をここでだけ要求）

    graph = build_graph(
        plan_llm=plan_llm,
        generate_llm=generate_llm,
        reader=repo_reader.read_allowlisted,
        repo_root=repo_root,
        writer=_make_writer(repo_root),
        git=_GitCli(repo_root),
        pr_runner=_make_pr_runner(repo) if repo else _noop_pr_runner,
        workflow_runner=_make_workflow_runner(repo) if repo else _noop_workflow_runner,
        io=io,
        denylist=denylist,
        dry_run=dry_run,
    )

    final = graph.invoke(state)
    _report(final, dry_run=dry_run)

    # プライバシー違反は exit 1（§6.1: record_failure_comment → exit 1）。
    if final.get("privacy_violations"):
        return 1
    return 0


def _noop_pr_runner(**_kwargs: Any) -> dict[str, Any]:
    """repo 未設定時の PR runner（呼ばれない想定だが安全側で no-op）。"""
    return {"url": None, "number": None, "isDraft": True}


def _noop_workflow_runner(_workflow: str, _inputs: dict[str, str]) -> None:
    """repo 未設定時の workflow runner（no-op）。"""
    return None


# repo_reader を import 済み（build_graph に read_allowlisted を渡すため）。


def _report(state: nodes.WeeklyState, *, dry_run: bool) -> None:
    """選定 Issue・変更計画・対象ファイル・結果を stdout にまとめて出す（DoD）。"""
    print("\n=== Weekly Implementer 実行結果 ===")
    selected = state.get("selected_issue", {}) or {}
    if selected:
        print(
            f"選定 Issue : #{selected.get('number')} {selected.get('title')}"
            f"（score={selected.get('score')}）"
        )
    else:
        print("選定 Issue : （approved 付き候補なし → 何もせず終了）")

    plan = (state.get("change_plan") or "").strip()
    if plan:
        print("変更計画   :")
        print(privacy.redact(plan))

    patches = state.get("proposed_patches", []) or []
    if patches:
        print("対象ファイル:")
        for patch in patches:
            print(f"  - {patch.get('path')}")

    violations = state.get("privacy_violations", []) or []
    if violations:
        print(f"プライバシー: 違反 {len(violations)} 件検出（実値は非表示）")

    if dry_run:
        print("PR        : DRY_RUN のため作成していません")
    else:
        print(f"PR        : {state.get('pr_url') or '(作成なし)'}")

    errors = state.get("errors", [])
    if errors:
        print("メモ      :")
        for e in errors:
            print(f"  - {e}")


if __name__ == "__main__":
    raise SystemExit(main())
