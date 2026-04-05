"""データモデル定義モジュール。すべてのdataclassをここで管理する。"""

from dataclasses import dataclass, field


@dataclass
class RawQuestion:
    """スクレイピング直後の生データ。"""

    source: str                    # データソース識別子 (例: "chiebukuro")
    category_major: str            # 大カテゴリ
    category_minor: str            # 中カテゴリ
    title: str                     # 質問タイトル
    body: str                      # 質問本文
    url: str                       # 質問URL
    answers_count: int | None      # 回答数
    views: int | None              # 閲覧数
    posted_at: str | None          # 投稿日時 (ISO形式)
    scraped_at: str                # スクレイプ日時 (ISO形式)


@dataclass
class ExtractedPain:
    """LLMによるペイン抽出結果。"""

    question_id: str               # RawQuestion.urlのハッシュ
    is_pain: bool                  # 真のペインか否か
    pain_summary: str              # ペインの要約（1〜2文）
    persona_type: str              # freelancer / consultant / small_biz_owner / employee / other
    persona_detail: str            # 例: 個人事業主のデザイナー
    job_to_be_done: str            # 例: 請求書作成、契約レビュー
    pain_stage: str                # 例: 作成時、提出前、月末処理
    pain_category: str             # Pain Categoryの値（models定義参照）
    current_workaround: str        # 今どうしのいでいるか
    root_cause: str                # なぜ発生しているか
    severity: int                  # 深刻度 1-5
    urgency: int                   # 緊急度 1-5
    recurrence_hint: str           # daily / weekly / monthly / one_off / unknown
    willingness_to_pay_proxy: int  # 支払意欲プロキシ 1-5
    builder_fit: int               # 作り手適合度 1-5
    evidence_text: str             # 根拠となる本文抜粋


@dataclass
class NormalizedPain:
    """表現ゆれを正規化したペイン。"""

    pain_id: str                   # ユニークID
    question_id: str               # 対応するExtractedPain.question_id
    canonical_problem: str         # 正規化された課題名
    canonical_user: str            # 正規化されたユーザー種別
    canonical_job: str             # 正規化されたジョブ
    canonical_root_cause: str      # 正規化された根本原因
    tags: list[str] = field(default_factory=list)  # 検索用タグ群
    fetched_date: str = ""         # 取得日 (YYYY-MM-DD)。Clustererでdate_count算出に使用


@dataclass
class PainCluster:
    """類似ペインをまとめたクラスタ。"""

    cluster_id: str
    cluster_label: str             # クラスタのラベル（テーマ名）
    canonical_problem: str
    representative_user: str
    representative_job: str
    root_cause_summary: str
    question_ids: list[str] = field(default_factory=list)
    pain_ids: list[str] = field(default_factory=list)
    cluster_size: int = 0
    date_count: int = 1            # 何日分のデータから構成されるか（recurrence_score算出用）
    avg_severity: float = 0.0
    avg_urgency: float = 0.0
    avg_wtp_proxy: float = 0.0
    avg_builder_fit: float = 0.0
    recurrence_score: float = 0.0
    solution_gap_score: float = 0.0
    productability_score: float = 0.0
    opportunity_score: float = 0.0


@dataclass
class IdeaCandidate:
    """アイデア候補。"""

    cluster_id: str
    idea_title: str
    one_liner: str                 # 1行説明
    target_user: str
    problem_statement: str
    solution: str
    mvp_scope: str                 # MVP範囲
    revenue_model: str
    estimated_price: str
    tech_stack: list[str] = field(default_factory=list)
    mvp_days: int = 0
    moat: str = ""                 # 参入障壁
    key_risks: list[str] = field(default_factory=list)
    why_now: str = ""              # なぜ今か
