# CLAUDE.md — ココナラ需要分析モジュール（src/coconala/）

## このモジュールの目的

ココナラ（coconala.com）の出品データをスクレイプし、
「繰り返し売れている × 自動化可能な作業」を特定する。

知恵袋パイプライン（src/chiebukuro/）が「困っている人」を見つけるのに対し、
このモジュールは「お金を払っている人」を見つける。
両者をクロスで見ることで、事業機会の確度が上がる。

## 既存コードとの関係

- **同じリポジトリ**（pain-hunter-jp/）に追加する
- **既存の知恵袋パイプラインには一切手を加えない**
- 共通で使うのは `src/config.py` の環境変数読み込みのみ
- GitHub Actionsのワークフローは別ファイル（`coconala.yml`）で新規作成

## 技術スタック

- **言語**: Python 3.12（既存と同じ）
- **スクレイピング**: 既存の `src/scraper/base.py` の raw socket + ssl 方式を流用
  - ただしココナラのドメインでも同じ方式が使えるか要検証
  - requests + BeautifulSoup で問題なくアクセスできるならそちらを優先（シンプルに保つ）
- **LLM**: Anthropic Claude API（claude-sonnet-4-20250514）
- **データ保存**: ローカルJSON

## ディレクトリ構成

```
pain-hunter-jp/
├── src/
│   ├── chiebukuro/         # 既存（触らない）
│   ├── coconala/           # ★新規
│   │   ├── __init__.py
│   │   ├── scraper.py      # Step1: 出品一覧スクレイプ
│   │   ├── analyzer.py     # Step2: Claude APIで自動化可能性判定
│   │   ├── report.py       # Step3: ランキングMarkdown出力
│   │   └── main.py         # パイプライン制御・CLI引数
│   ├── config.py           # 共通（ANTHROPIC_API_KEY等）
│   └── models.py           # 共通（ココナラ用dataclass追加）
├── data/
│   └── coconala/           # ★新規
│       ├── raw/            # Step1出力
│       ├── analyzed/       # Step2出力
│       └── reports/        # Step3出力
├── .github/workflows/
│   ├── daily.yml           # 知恵袋（既存、触らない）
│   └── coconala.yml        # ★新規（週1実行）
└── tests/
    └── test_coconala.py    # ★新規
```

## データモデル

`src/models.py` に以下のdataclassを追加する。

```python
@dataclass
class CoconalaListing:
    """ココナラの出品データ。"""
    listing_id: str
    title: str
    description: str           # 出品の説明文（500文字まで）
    category_major: str        # 大カテゴリ
    category_minor: str        # 中カテゴリ
    price: int                 # 最低価格（円）
    sales_count: int           # 販売実績件数
    review_count: int          # レビュー件数
    rating: float              # 平均評価（0.0〜5.0）
    seller_name: str           # 出品者名
    url: str
    scraped_at: str            # ISO形式

@dataclass
class AnalyzedListing:
    """自動化可能性を分析済みの出品データ。"""
    listing_id: str
    title: str
    category_major: str
    category_minor: str
    price: int
    sales_count: int
    review_count: int
    rating: float
    url: str
    # --- 分析結果（Claude APIで付与） ---
    is_automatable: bool       # Python/LLM/APIで自動化可能か
    automation_summary: str    # どう自動化できるか（1〜2文）
    task_type: str             # 10文字以内の作業名（知恵袋のjob_to_be_doneと揃える）
    automation_difficulty: int  # 1=簡単 3=中程度 5=専門知識必要
    builder_fit: int           # 1-5（Python/LLM/APIで作れる度）
    monthly_demand_estimate: str  # high / medium / low
    saas_price_suggestion: int    # 月額SaaS化した場合の推定価格（円）
```

## 実装順序（この順番で作ること）

### Step 0: 基盤
- `src/coconala/__init__.py`
- `src/models.py` に `CoconalaListing` と `AnalyzedListing` を追加
- `src/config.py` にココナラ関連の設定を追加（あれば）
- `data/coconala/raw/`, `data/coconala/analyzed/`, `data/coconala/reports/` ディレクトリ作成

### Step 1: Scraper（`src/coconala/scraper.py`）

**何をするか**: ココナラの対象カテゴリの出品一覧を、販売実績順にスクレイプする。

**対象カテゴリ（自動化に近い領域のみ）**:

以下のカテゴリページから出品を取得する。
まず coconala.com のカテゴリ構造を確認し、以下に相当するURLとカテゴリIDを特定すること。

- IT・プログラミング・開発
- ビジネス代行・コンサル・士業
- ライティング・翻訳
- データ入力・リサーチ
- Web制作・Webデザイン
- 動画・アニメーション・撮影（編集作業部分）
- マーケティング・Web集客

**取得データ**:
- 各カテゴリの出品一覧ページを「販売実績順」（おすすめ順ではない）でソート
- 上位30件を取得（1カテゴリあたり）
- 各出品の詳細ページからタイトル、説明文、価格、販売実績、レビュー数、評価を抽出

**制約**:
- robots.txt を事前に確認し、許可されているパスのみアクセス
- リクエスト間隔は最低2秒
- 1回の実行で最大200リクエスト以内
- 説明文は500文字で切り捨て（LLM送信時）

**出力**: `data/coconala/raw/{date}.json` に `CoconalaListing` のリストを保存

**HTTPクライアントについて**:
- まず `requests` + `BeautifulSoup` で試す
- ココナラがJSレンダリング必須の場合のみ、知恵袋と同じ raw socket 方式を検討
- Cloudflare等のbot対策がある場合は、User-Agent設定とリクエスト間隔調整で対処
- どうしてもブロックされる場合は、APIエンドポイントの有無を調査（ココナラはSPAなのでJSON APIがある可能性がある）

### Step 2: Analyzer（`src/coconala/analyzer.py`）

**何をするか**: Claude APIで各出品の「自動化可能性」を判定する。

**処理方式**: 10件ずつバッチにまとめてAPI送信（コスト削減）。

**LLMシステムプロンプト**:

```
あなたは業務自動化の専門家です。
ココナラの出品（人が手作業で提供しているサービス）を読み、
「Python / LLM / API を使って自動化できるか」を判定してください。

【判定基準 — is_automatable の true/false】

is_automatable: true にする条件:
- データ入力・転記・変換作業（Excel、CSV、PDF→データ化など）
- 文書作成・テンプレート埋め（契約書、請求書、メール文面など）
- リサーチ・情報収集・まとめ作業
- 翻訳・校正・リライト
- 画像の簡単な加工（リサイズ、背景除去、フォーマット変換）
- データ分析・レポート作成
- SNS投稿の作成・スケジューリング

is_automatable: false にする条件:
- 高度なデザイン・イラスト制作（人のクリエイティビティが必要）
- 対面コンサルティング・カウンセリング
- 写真撮影・動画撮影（物理的作業）
- 法律・税務・医療の専門的助言
- ナレーション・声優（声の個性が価値）

【フィールド制約】

■ task_type: **10文字以内**の作業名。
  良い例: データ入力、文書作成、翻訳、リサーチ、画像加工、SNS運用
  悪い例: Excelデータの入力と整理と分析（長すぎる）

■ automation_difficulty: 1〜5の整数
  1=既存ライブラリで即実装可 3=API連携やプロンプト設計が必要 5=ML/専門知識が必要

■ builder_fit: 1〜5の整数
  1=専門知識が必要 3=汎用スキルで可能 5=Python/LLM/APIで十分

■ monthly_demand_estimate: high / medium / low
  販売実績と価格から推定。sales_count > 100かつprice >= 3000 なら high。

■ saas_price_suggestion: 月額SaaS化した場合の推定価格（円）
  出品価格の1/3〜1/5が目安。最低500円、最高10000円。

出力は必ずJSON配列で返す。
```

**パース時のバリデーション**: 知恵袋Extractorと同様、enum値チェック・文字数切り詰め・数値クランプを行う。

**出力**: `data/coconala/analyzed/{date}.json` に `AnalyzedListing` のリストを保存

### Step 3: Report（`src/coconala/report.py`）

**何をするか**: 分析結果をMarkdownレポートに整理する。

**レポート構成**:

```markdown
# ココナラ需要分析レポート — {date}

## サマリー
- 分析出品数: XX件
- 自動化可能: XX件
- 上位作業タイプ: データ入力（XX件）、文書作成（XX件）、...

## 自動化可能な出品 TOP10（販売実績順）

### #1 {title}
- **販売実績**: XX件 / **価格**: ¥X,XXX / **評価**: ★X.X
- **作業タイプ**: {task_type}
- **自動化の方法**: {automation_summary}
- **builder_fit**: X/5 / **難易度**: X/5
- **SaaS化した場合の月額**: ¥X,XXX

## 作業タイプ別集計

| 作業タイプ | 出品数 | 平均販売実績 | 平均価格 | SaaS化余地 |
|---|---|---|---|---|
| データ入力 | XX | XX件 | ¥X,XXX | 高 |

## 知恵袋クラスタとのクロス参照
（将来実装：同じtask_typeが知恵袋でもクラスタ化されていれば表示）
```

**出力**: `data/coconala/reports/{date}.md`

### Step 4: main.py + GitHub Actions

**`src/coconala/main.py`**:

```bash
# 通常実行
python -m src.coconala.main

# ドライラン
python -m src.coconala.main --dry-run

# カテゴリ指定
python -m src.coconala.main --categories "IT・プログラミング" "ライティング"

# 通知スキップ
python -m src.coconala.main --skip-notify
```

**`.github/workflows/coconala.yml`**:
- 週1回実行（日曜 AM 3:00 JST = 土曜 UTC 18:00）
- `workflow_dispatch` で手動実行可能（limitパラメータ付き）
- Secretsは既存の `ANTHROPIC_API_KEY`, `NTFY_TOPIC` を共用
- Commit results ステップで `data/coconala/` をpush

## コーディング規約

既存の知恵袋パイプラインと同じ規約に従うこと。

1. **型ヒント必須**: すべての関数にtype hints
2. **dataclass使用**: models.pyに定義
3. **エラーハンドリング**: スクレイピングとAPI呼び出しは必ずtry/exceptで囲む
4. **ログ**: loggingモジュールを使用、print()は使わない
5. **環境変数**: config.pyで一元管理
6. **docstring**: 各モジュール・クラス・主要関数に日本語docstring

## 重要な注意事項

### スクレイピング
- coconala.com の robots.txt を事前に確認すること
- User-Agentを適切に設定
- リクエスト間隔は最低2秒
- 1回の実行で最大200リクエスト以内
- 個人情報（出品者の本名等）は取得・保存しない。seller_nameは表示名のみ

### ココナラのサイト構造
- ココナラはSPA（Single Page Application）の可能性が高い
- その場合、HTMLを直接パースしてもデータが取れない
- **まず以下を確認すること**:
  1. ブラウザのDevToolsでNetworkタブを開き、カテゴリページにアクセス
  2. XHR/Fetchリクエストを確認し、JSON APIがあるか調べる
  3. JSON APIがあればそれを直接叩く（HTMLパースより安定）
  4. なければ、ページソースに埋め込まれたJSONデータ（__NEXT_DATA__等）を探す

### API呼び出し
- 知恵袋Extractorと同じ方式（exponential backoff、最大3回リトライ）
- バッチサイズ10件

### コスト
- Claude API: 10バッチ × 約$0.05 = 約$0.5/回
- 週1実行で月$2程度

## よく使うコマンド

```bash
# 開発実行（ドライラン）
python -m src.coconala.main --dry-run

# 本番実行
python -m src.coconala.main

# テスト
pytest tests/test_coconala.py -v
```