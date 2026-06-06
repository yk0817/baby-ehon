---
name: 絵本の機能提案（research-based）
about: 1歳児向け絵本への新機能・新ブックの提案
title: ""
labels: ["enhancement", "research-based"]
assignees: []
---

<!-- ╔══════════════════════════════════════════════════════════════╗ -->
<!-- ║ ⚠️ プライバシー方針（公開リポジトリ）— 必ず守る               ║ -->
<!-- ║ ・お子さん/家族の本名・愛称を書かない。呼びかけは __NAME__     ║ -->
<!-- ║ ・住所/電話/メール/保育園名/通園経路/GPS など個人特定情報を書かない ║ -->
<!-- ║ ・一般名詞（お子さん/対象児/ユーザー）で書く                   ║ -->
<!-- ║ 詳細: CLAUDE.md / docs/automation/agent-pipeline.md §8         ║ -->
<!-- ╚══════════════════════════════════════════════════════════════╝ -->

## 背景・ねらい（発達研究）
<!-- どんな発達的効果を狙うか。先行研究の裏付けを 1-3 件（共同注意・音象徴・繰り返し・コントラスト感受性など） -->
-

## 提案内容
<!-- 何を・どの絵本に・どう足すか。HTML/CSS/JS のみで完結する前提で具体的に -->


## 想定影響ファイル
<!-- 例: shared/ehon.js, <book>/config.js -->
-

## 受け入れ条件
- [ ] 対象冊（または5冊: hikouki/densha/kuruma/otenki/yorunosora）で挙動を確認
- [ ] `__NAME__` プレースホルダ以外に人名が入らない
- [ ] 誤操作で抜けない・タップ報酬が即時・点滅/音が過多でない（0-2歳の安全性）
- [ ] README の「ラインナップ」「構成」更新要否を判断

---
### 📋 このリポジトリの承認フロー（Issue → PR → 人間 merge）
- この Issue を**実装してよい**と判断したら **`approved` ラベル**を貼る（人間の入口ゲート）
- 自動の作成者は **`approved` 付き Issue だけ**を実装し **Draft PR** を出す（自動マージはしない）
- ラベルの流れ: `stage:researched` →（人間が `approved`）→ `stage:implemented` → `stage:child-reviewed` → 人間が merge
- 自動処理から外したい場合は `automation:skip` を貼る
- 詳細: [`docs/automation/agent-pipeline.md`](../blob/main/docs/automation/agent-pipeline.md)
