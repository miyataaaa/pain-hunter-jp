# ブランチ戦略

## ブランチ構成

| ブランチ | 役割 |
|---|---|
| `dev` | 安定版・マージ先の基点 |
| `features/xxxx` | 機能追加・改修 |
| `bugfix/xxxx` | バグ修正 |

- `master` ブランチは使用しない
- 作業ブランチは常に `dev` から切り、`dev` にマージして削除する

## バージョン管理

セマンティックバージョニング（`vMAJOR.MINOR.PATCH`）でタグ管理。

| バージョン | 例 | 意味 |
|---|---|---|
| MAJOR | v1.0.0 | 後方互換性のない大きな変更 |
| MINOR | v0.2.0 | 後方互換性のある機能追加 |
| PATCH | v0.1.1 | バグ修正・軽微な改善 |

節目でタグを付与してスナップショット管理を行う。

## 運用フロー

```
dev
 └── features/xxx  ←作業
         │
         └──(merge)──▶ dev  ←タグ付与（節目のみ）
```

```bash
# 機能ブランチを切る
git checkout dev
git checkout -b features/xxx

# 作業後、devにマージ
git checkout dev
git merge --no-ff features/xxx
git branch -d features/xxx

# 節目でタグ
git tag -a v0.1.1 -m "v0.1.1 — ..."
```
