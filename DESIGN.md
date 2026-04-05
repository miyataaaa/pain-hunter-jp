# PainHunter JP — 設計ドキュメント v2

## 概要

日本語圏のSNS・Q&Aサイトから、個人・事業者・中小企業の「困りごと」「非効率」「不満」「手作業による摩擦」を抽出し、
それらを単発の投稿としてではなく「繰り返し現れる構造的課題」として整理し、
自分が実際に作れるプロダクトアイデア候補へ変換する個人用ツール。

定期実行で毎日深夜に動かし、朝には以下が分かる状態を目指す。

- 今日の強いペインは何か
- 直近数日で繰り返し現れている課題は何か
- その中で、自分のスキルセットで作れそうなものは何か
- MVP化するならどの切り口が良いか

---

## このツールの目的

このツールの目的は、単に「困っている投稿を集めること」ではない。

目的は以下の3つである。

1. 日本語圏で繰り返し現れる業務・生活上の構造的課題を見つける
2. その課題の中から、自分が作れる領域に絞って評価する
3. 実際に作る価値のあるツール/サービス案へ落とし込む

つまり、これは「感情分析ツール」ではなく、**事業仮説探索ツール**である。

---

## ゴール

### Phase 1（今日）
Yahoo!知恵袋を対象に、以下のパイプラインを作る。

- 質問取得
- ノイズ除去
- ペイン抽出・構造化
- 表現ゆれ正規化
- 類似ペインの簡易クラスタリング
- 課題機会スコア算出
- 上位クラスタのみアイデア生成
- JSON保存 + 日次レポート出力 + 通知

### Phase 2（今週中）
- X(Twitter)追加
- 5ch追加
- 直近7日トレンド検出追加
- クラスタ品質改善

### Phase 3（将来）
- note / はてなブックマーク / ココナラ / App Storeレビュー追加
- Streamlit UI
- ペインDB検索
- アイデア比較UI
- 手動評価フィードバック機構

---

## このツールの成功条件

このツールの成功は「ペインを多く抽出したこと」ではない。
以下を成功条件とする。

### 運用KPI
- 1週間で「作ってみたい」と思えるアイデアが3件以上出る
- 同一テーマの課題クラスタが3日以上繰り返し出現する
- 週に1件以上、自分の守備範囲でMVP 7日以内の案が出る
- 上位クラスタを見たときに「なぜ上位か」が説明できる

---

## ジャンル探索方針

### 基本方針
「市場が大きい」だけではなく、

- 自分が課題を理解できる
- 自分が作れる
- 課題が繰り返し起きる
- 今の代替手段が弱い

のAND条件で絞る。

### 初期ターゲットジャンル

#### ジャンル①：コンサル・士業の業務効率化
**なぜ**: 自分自身がコンサルタントで、課題の解像度が最も高い。
RFP回答、提案資料作成、議事録整理、契約書レビュー等の非効率は実体験済み。
士業（行政書士・税理士・社労士）も類似構造で、DX遅れが顕著。

**知恵袋の対象カテゴリ**:
| 大カテゴリ | 中カテゴリ | 狙い |
|---|---|---|
| ビジネス、経済とお金 | 企業と経営 | 経営・業務プロセスの悩み |
| ビジネス、経済とお金 | 会計、経理、財務 | 経理・財務の非効率 |
| ビジネス、経済とお金 | 起業 | 起業準備の障壁 |
| ビジネス、経済とお金 | 企業法務、知的財産 | 法務・契約の面倒さ |
| 職業とキャリア | 仕事効率化、ノウハウ | 業務改善ニーズ直球 |
| 職業とキャリア | 労働問題 | 労務管理の課題 |

#### ジャンル②：フリーランス・個人事業主の事務作業
**なぜ**: 確定申告、請求書、契約書、見積書、スケジュール管理など
「本業じゃないのにやらなきゃいけない作業」が大量にある市場。
freeeやマネーフォワードがカバーしきれていないニッチが多い。

**知恵袋の対象カテゴリ**:
| 大カテゴリ | 中カテゴリ | 狙い |
|---|---|---|
| ビジネス、経済とお金 | 税金、年金 | 確定申告・税務の困りごと |
| ビジネス、経済とお金 | 保険 | 社会保険・年金の複雑さ |
| ビジネス、経済とお金 | インターネットビジネス、SOHO | 在宅ワーク・副業の課題 |
| 暮らしと生活ガイド | 法律、消費者問題 | 契約・法的トラブル |

#### ジャンル③：中小企業のIT・DX
**なぜ**: 「どのツールを使えばいいかわからない」「Excelでやってるけど限界」
という悩みが大量にあり、ITリテラシーのギャップが構造的に大きい。
解決策がAI×自動化で提供しやすい。

**知恵袋の対象カテゴリ**:
| 大カテゴリ | 中カテゴリ | 狙い |
|---|---|---|
| コンピュータテクノロジー | プログラミング | 自動化・ツール開発の相談 |
| スマートデバイス、PC、家電 | パソコン | PC業務の非効率 |
| インターネット、通信 | サービス、探しています | ツール選定の悩み |

### 探索スケジュール

```
Week 1 (Day 1-7): 3ジャンル全部を毎日スクレイプ
  → 各ジャンルのペイン件数・深刻度・ビジネス可能性を定量比較

Week 2 (Day 8-14): Top 1-2ジャンルに絞り込み
  → 絞ったジャンル内のサブカテゴリを深掘り

Week 3以降: 最有望ジャンルで実際にMVPプロダクトの設計に入る
```

### Week 1の意思決定基準
- 同一テーマが複数回出るジャンルを優先
- 自分の builder fit が高いジャンルを優先
- 単なる情報不足質問が多いジャンルは除外
- 具体的 workaround が多く見えるジャンルを優先

---

## 自分のスキルセットと適合領域

### スキルセット
- Python / Azure / クラウド基盤
- LLM API連携
- データ分析・可視化（pandas, matplotlib, Streamlit）
- Webアプリ（Next.js / Streamlit）
- API連携・自動化パイプライン
- MLOps / CI/CD / pytest

### したがって向いているプロダクト
- 反復業務の自動化ツール
- LLMを使った情報整理/文書生成支援
- 複数ツール間のデータ接続・転記削減
- 業務フロー上の面倒を減らすラッパーSaaS
- ドメイン特化の軽量支援ツール

---

## アーキテクチャ

### 設計思想

**変更前**: 1投稿 → 1ペイン → 1アイデア
**変更後**: 複数投稿 → 構造化ペイン → 類似クラスタ → 機会評価 → 上位のみアイデア生成

**狙い**: 単発の愚痴や相談ではなく、繰り返し出る構造的課題から事業仮説を作る。

### パイプライン

```
┌────────────────────────────────────────────────────┐
│ cron / GitHub Actions — 毎日 AM 3:00 実行         │
└─────────────┬──────────────────────────────────────┘
              ▼
┌─────────────────────────┐
│ 1. Scraper              │
│ - Yahoo!知恵袋          │
│ - カテゴリ別に質問取得  │
│ - HTML解析              │
└─────────────┬───────────┘
              ▼
┌─────────────────────────┐
│ 2. Filter               │
│ - スパム除去            │
│ - 重複除去              │
│ - 低情報量除去          │
│ - 知識質問・比較質問除外│
└─────────────┬───────────┘
              ▼
┌─────────────────────────┐
│ 3. Pain Extractor       │
│ - 困りごとか判定        │
│ - ペイン要約            │
│ - 構造化属性抽出        │
│ - workaround / root cause│
└─────────────┬───────────┘
              ▼
┌─────────────────────────┐
│ 4. Normalizer           │
│ - 表現ゆれ統一          │
│ - 業務単位に正規化      │
│ - root cause 正規化     │
└─────────────┬───────────┘
              ▼
┌─────────────────────────┐
│ 5. Clusterer            │
│ - 類似ペインの束化      │
│ - テーマ名付与          │
│ - 件数集計              │
└─────────────┬───────────┘
              ▼
┌─────────────────────────┐
│ 6. Opportunity Scorer   │
│ - severity              │
│ - recurrence            │
│ - solution_gap          │
│ - WTP proxy             │
│ - builder_fit           │
│ - productability        │
└─────────────┬───────────┘
              ▼
┌─────────────────────────┐
│ 7. Idea Generator       │
│ - 上位クラスタのみ対象  │
│ - MVP案へ変換           │
│ - 切り口を複数出す      │
└─────────────┬───────────┘
              ▼
┌─────────────────────────┐
│ 8. Report + Notify      │
│ - JSON蓄積              │
│ - 日次Markdown          │
│ - ntfy.sh / Slack通知   │
└─────────────────────────┘
```

---

## ディレクトリ構成

```
pain-hunter-jp/
├── DESIGN.md
├── CLAUDE.md
├── requirements.txt
├── .env.example
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── models.py
│   ├── scraper/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── chiebukuro.py
│   ├── filter.py
│   ├── extractor.py
│   ├── normalizer.py
│   ├── clusterer.py
│   ├── scorer.py
│   ├── idea_generator.py
│   ├── report.py
│   └── notifier.py
├── data/
│   ├── raw/
│   ├── filtered/
│   ├── extracted/
│   ├── normalized/
│   ├── clustered/
│   ├── scored/
│   └── ideas/
├── reports/
├── logs/
└── tests/
    ├── test_scraper.py
    ├── test_filter.py
    ├── test_extractor.py
    ├── test_normalizer.py
    ├── test_clusterer.py
    └── test_scorer.py
```

---

## データモデル

### 1. RawQuestion
```python
@dataclass
class RawQuestion:
    source: str
    category_major: str
    category_minor: str
    title: str
    body: str
    url: str
    answers_count: int | None
    views: int | None
    posted_at: str | None
    scraped_at: str
```

### 2. ExtractedPain
```python
@dataclass
class ExtractedPain:
    question_id: str
    is_pain: bool
    pain_summary: str
    persona_type: str              # freelancer, consultant, small_biz_owner, etc.
    persona_detail: str            # 例: 個人事業主のデザイナー
    job_to_be_done: str            # 例: 請求書作成、契約レビュー
    pain_stage: str                # 例: 作成時、提出前、月末処理
    pain_category: str             # 業務寄りカテゴリ
    current_workaround: str        # 今どうしのいでいるか
    root_cause: str                # なぜ発生しているか
    severity: int                  # 1-5
    urgency: int                   # 1-5
    recurrence_hint: str           # daily / weekly / monthly / one_off / unknown
    willingness_to_pay_proxy: int  # 1-5
    builder_fit: int               # 1-5
    evidence_text: str             # 根拠となる本文抜粋
```

### 3. NormalizedPain
```python
@dataclass
class NormalizedPain:
    pain_id: str
    question_id: str
    canonical_problem: str
    canonical_user: str
    canonical_job: str
    canonical_root_cause: str
    tags: list[str]
```

### 4. PainCluster
```python
@dataclass
class PainCluster:
    cluster_id: str
    cluster_label: str
    canonical_problem: str
    representative_user: str
    representative_job: str
    root_cause_summary: str
    question_ids: list[str]
    pain_ids: list[str]
    cluster_size: int
    avg_severity: float
    avg_urgency: float
    avg_wtp_proxy: float
    avg_builder_fit: float
    recurrence_score: float
    solution_gap_score: float
    productability_score: float
    opportunity_score: float
```

### 5. IdeaCandidate
```python
@dataclass
class IdeaCandidate:
    cluster_id: str
    idea_title: str
    one_liner: str
    target_user: str
    problem_statement: str
    solution: str
    mvp_scope: str
    revenue_model: str
    estimated_price: str
    tech_stack: list[str]
    mvp_days: int
    moat: str
    key_risks: list[str]
    why_now: str
```

---

## Pain Category（業務・行動ベース）

| カテゴリ | 説明 |
|---|---|
| `manual_reentry` | 手入力・転記・二重入力が多い |
| `document_creation` | 書類作成が面倒、毎回ゼロから作っている |
| `knowledge_lookup` | 情報が散在していて調べるのが大変 |
| `tool_fragmentation` | 複数ツールに分かれていて一気通貫でできない |
| `compliance_confusion` | 制度・法律・ルールが複雑で分からない |
| `approval_bottleneck` | 承認や確認待ちで詰まる |
| `recurring_admin_work` | 毎月・毎週発生する事務作業が重い |
| `exception_handling` | イレギュラー対応だけ手間が大きい |
| `customer_followup` | 顧客対応・追跡・連絡が面倒 |
| `handoff_loss` | 引き継ぎ・共有で情報が抜ける |
| `other` | 上記に当てはまらない |

---

## Opportunity Scorer 合成式

```python
opportunity_score = (
    0.20 * severity_score
    + 0.20 * recurrence_score
    + 0.20 * solution_gap_score
    + 0.15 * wtp_score
    + 0.15 * builder_fit_score
    + 0.10 * productability_score
)
```

---

## 環境変数 (.env)

```bash
ANTHROPIC_API_KEY=sk-ant-...
NTFY_TOPIC=pain-hunter-jp-xxxxx
SLACK_WEBHOOK_URL=
SCRAPE_INTERVAL_SEC=2
MAX_QUESTIONS_PER_CATEGORY=20
OPPORTUNITY_THRESHOLD=3.8
CLUSTER_SIMILARITY_THRESHOLD=0.82
LOOKBACK_DAYS=7
```

---

## コスト見積もり

| 項目 | 月額 |
|------|------|
| Anthropic API (抽出+正規化+アイデア生成) | ~$10-25 |
| GitHub Actions (無料枠内) | $0 |
| ntfy.sh | $0 |
| **合計** | **~¥1,500-4,000** |

---

## Phase 1でやらないこと

- 精密な市場規模推定
- 厳密な競合マッピング
- SaaS前提の認証/課金機能
- 全ジャンル横断の網羅
- 高度な機械学習による分類最適化
- X / 5ch / note等の追加データソース
- Streamlit UI / DB化

**最初にやるべきは、良い課題が継続的に見つかるかの検証である。**

---

## 最終的な思想

PainHunter JP は「困りごと収集ツール」ではない。

これは、日本語圏で言語化されている細かな不便や摩擦を、
自分が作れる具体的な事業仮説へ変換するための
**個人用オポチュニティ・サーチエンジン**である。

設計の4つのキモ:
1. **投稿単位ではなくクラスタ単位で見る**
2. **事業性を分解スコアで見る**
3. **who / workaround / root cause を構造化する**
4. **上位クラスタだけをアイデア化する**
