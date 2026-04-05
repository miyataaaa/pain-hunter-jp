# PainHunter JP

Yahoo!知恵袋の投稿から「繰り返し現れる構造的なニーズ」を自動抽出し、プロダクトアイデアへ変換する個人用CLIツール。

cronで毎日深夜に自動実行し、朝にntfy.shで結果を通知する。

## パイプライン

```
Yahoo!知恵袋
  └─[Scraper]──▶ data/raw/
  └─[Filter]───▶ data/filtered/
  └─[Extractor]▶ data/extracted/   ← Claude API
  └─[Normalizer]▶ data/normalized/
  └─[Clusterer]▶ data/clustered/   ← 過去7日分と合流
  └─[Scorer]───▶ data/scored/
  └─[IdeaGen]──▶ data/ideas/       ← Claude API（上位3クラスタのみ）
  └─[Report]───▶ reports/
  └─[Notify]───▶ ntfy.sh
```

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env
# .env に ANTHROPIC_API_KEY と NTFY_TOPIC を記入
```

## 実行

```bash
# 本番実行
python -m src.main

# ドライラン（API呼び出しなし・動作確認用）
python -m src.main --dry-run --limit 5

# 通知スキップ
python -m src.main --skip-notify

# カテゴリ絞り込み
python -m src.main --categories "税金、年金" "起業"
```

## 技術スタック

- **言語**: Python 3.12
- **スクレイピング**: raw socket + ssl（TLSフィンガープリント回避）
- **LLM**: Anthropic Claude API（`claude-sonnet-4-20250514`）
- **通知**: ntfy.sh（HTTPS POST）
- **定期実行**: WSL cron

## ディレクトリ構成

```
├── src/
│   ├── main.py            # パイプライン制御・CLI
│   ├── config.py          # 環境変数管理
│   ├── models.py          # dataclass定義
│   ├── scraper/           # Yahoo!知恵袋スクレイパー
│   ├── filter.py          # ノイズ除去
│   ├── extractor.py       # Claude APIでペイン構造化
│   ├── normalizer.py      # 表現ゆれ正規化
│   ├── clusterer.py       # クラスタリング
│   ├── scorer.py          # 機会スコア算出
│   ├── idea_generator.py  # アイデア生成
│   ├── report.py          # Markdownレポート生成
│   └── notifier.py        # ntfy.sh通知
├── data/                  # 各ステップの中間JSON（日付別）
├── reports/               # 日次Markdownレポート
├── docs/                  # バージョン別仕様ドキュメント
└── tests/                 # pytest
```

## 環境変数

| 変数名 | 説明 | デフォルト |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic APIキー | 必須 |
| `NTFY_TOPIC` | ntfy.shのトピック名 | 必須 |
| `SCRAPE_INTERVAL_SEC` | リクエスト間隔（秒） | 2 |
| `MAX_QUESTIONS_PER_CATEGORY` | カテゴリあたり最大取得数 | 20 |
| `OPPORTUNITY_THRESHOLD` | アイデア生成の足切りスコア | 0.65 |
| `LOOKBACK_DAYS` | 過去データの参照日数 | 7 |

## テスト

```bash
pytest tests/ -v
```

## ドキュメント

バージョン別の仕様・設計ドキュメントは `docs/` 以下に格納。

- [`docs/v0.1.x/v0.1.0.md`](docs/v0.1.x/v0.1.0.md) — 初回リリース
- [`docs/v0.1.x/v0.1.1.md`](docs/v0.1.x/v0.1.1.md) — クラスタリング改善・スコアスケール修正
- [`docs/common/git_branch_strategy.md`](docs/common/git_branch_strategy.md) — ブランチ戦略
