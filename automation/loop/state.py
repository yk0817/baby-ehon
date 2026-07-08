"""状態機械（足場の ②State）。

ループの「記憶」をここに集約する。会話の外＝ファイル(state.json)に状態を置くのが肝。
これにより、ループが途中で止まっても再開でき、各 maker 起動はステートレスにできる。

設計方針: 不変(immutable)。状態を変える操作は **新しいオブジェクトを返す**。
（既存を書き換えないことで、追いにくい副作用を防ぐ — coding-style: Immutability）

設計の正: docs/automation/harness-loop.md §2 ②State。
ラボ ~/harness-loop-lab/loop/state.py の写像。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

# 機能(feature)の状態
PENDING = "pending"  # 未着手
IN_PROGRESS = "in_progress"  # 着手中（クラッシュ時に再開対象と分かる）
DONE = "done"  # 受け入れテスト green
FAILED = "failed"  # 総試行回数の上限に達して断念


@dataclass(frozen=True)
class Feature:
    """spec の1機能。maker に1つずつ渡す単位（④Scope）。"""

    id: str
    title: str
    goal: str
    acceptance_test: str
    status: str = PENDING
    attempts: int = 0
    last_error: str = ""


@dataclass(frozen=True)
class LoopState:
    project: str
    features: tuple[Feature, ...]

    # ---- 問い合わせ ----
    def next_actionable(self) -> Feature | None:
        """次に着手すべき機能（pending か in_progress の先頭）。無ければ None。"""
        for f in self.features:
            if f.status in (PENDING, IN_PROGRESS):
                return f
        return None

    def is_complete(self) -> bool:
        """全機能が done か failed（=これ以上動かせない）なら True。"""
        return all(f.status in (DONE, FAILED) for f in self.features)

    def all_done(self) -> bool:
        return all(f.status == DONE for f in self.features)

    # ---- 遷移（新しい LoopState を返す）----
    def _with_feature(self, updated: Feature) -> LoopState:
        features = tuple(updated if f.id == updated.id else f for f in self.features)
        return replace(self, features=features)

    def mark_in_progress(self, feature_id: str) -> LoopState:
        return self._with_feature(replace(self._get(feature_id), status=IN_PROGRESS))

    def mark_done(self, feature_id: str) -> LoopState:
        return self._with_feature(
            replace(self._get(feature_id), status=DONE, last_error="")
        )

    def record_failure(
        self, feature_id: str, error: str, max_attempts: int
    ) -> LoopState:
        """1回失敗を記録。総試行回数が max_attempts に達したら FAILED、まだなら IN_PROGRESS。"""
        f = self._get(feature_id)
        attempts = f.attempts + 1
        status = FAILED if attempts >= max_attempts else IN_PROGRESS
        return self._with_feature(
            replace(f, attempts=attempts, last_error=error, status=status)
        )

    def _get(self, feature_id: str) -> Feature:
        for f in self.features:
            if f.id == feature_id:
                return f
        raise KeyError(feature_id)

    # ---- 永続化 ----
    def to_dict(self) -> dict:
        # asdict は frozen Feature を再帰コピーして返す。vars(f) だと __dict__ への
        # 参照を晒し、返値を変更すると frozen インスタンスを無音で汚染するため使わない。
        return {
            "project": self.project,
            "features": [asdict(f) for f in self.features],
        }

    def save(self, path: Path | str) -> None:
        # 一時ファイルに書いてから置換する。途中でクラッシュしても既存 state.json は
        # 壊れない（os.replace は同一FS内でアトミック）= 再開可能性の主契約を守る。
        p = Path(path)
        tmp = p.parent / (p.name + ".tmp")
        tmp.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(p)

    @classmethod
    def from_dict(cls, data: dict) -> LoopState:
        features = tuple(Feature(**f) for f in data["features"])
        return cls(project=data["project"], features=features)

    @classmethod
    def from_features_json(cls, features_json: Path | str) -> LoopState:
        """specs/<name>/features.json から初期状態（全部 pending）を作る。"""
        data = json.loads(Path(features_json).read_text(encoding="utf-8"))
        features = tuple(
            Feature(
                id=f["id"],
                title=f["title"],
                goal=f["goal"],
                acceptance_test=f["acceptance_test"],
            )
            for f in data["features"]
        )
        if not features:
            raise ValueError(f"features が空です: {features_json}")
        return cls(project=data.get("project", "project"), features=features)

    @classmethod
    def load(cls, path: Path | str) -> LoopState:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
