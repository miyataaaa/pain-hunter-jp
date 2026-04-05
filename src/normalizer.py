"""正規化モジュール。ペインの表現ゆれを統一してNormalizedPainを生成する。"""

import hashlib
import json
import logging
from pathlib import Path

from src.config import config
from src.models import ExtractedPain, NormalizedPain


# 同義語マッピング辞書
_PERSONA_MAP: dict[str, str] = {
    "フリーランス": "フリーランス",
    "freelancer": "フリーランス",
    "個人事業主": "フリーランス",
    "ソロプレナー": "フリーランス",
    "副業": "フリーランス",
    "コンサルタント": "コンサルタント",
    "consultant": "コンサルタント",
    "士業": "士業",
    "税理士": "士業",
    "行政書士": "士業",
    "社労士": "士業",
    "中小企業": "中小企業",
    "small_biz_owner": "中小企業",
    "経営者": "中小企業",
    "社長": "中小企業",
    "会社員": "会社員",
    "employee": "会社員",
    "サラリーマン": "会社員",
    "その他": "その他",
    "other": "その他",
}

_JOB_MAP: dict[str, str] = {
    # 税務系
    "確定申告": "確定申告",
    "確定申告作業": "確定申告",
    "年末調整": "年末調整",
    # 請求・経理系
    "請求書作成": "請求書作成",
    "請求書発行": "請求書作成",
    "請求書管理": "請求書作成",
    "経費精算": "経費精算",
    "経費処理": "経費精算",
    "経費申請": "経費精算",
    "経理": "月次決算",
    "会計": "月次決算",
    "月次決算": "月次決算",
    "帳簿": "月次決算",
    "インボイス": "確定申告",
    "消費税": "確定申告",
    # 契約・法務系
    "契約書": "契約書レビュー",
    "契約レビュー": "契約書レビュー",
    "契約書レビュー": "契約書レビュー",
    "NDA": "契約書レビュー",
    "法務": "契約書レビュー",
    "商標出願": "商標出願",
    # ドキュメント系
    "議事録": "議事録作成",
    "議事録作成": "議事録作成",
    "資料作成": "資料作成",
    "提案書": "資料作成",
    "報告書": "資料作成",
    # ツール・システム系
    "ツール選定": "ツール選定",
    "ツール導入": "ツール選定",
    "システム導入": "ツール選定",
    "業務効率化": "ツール選定",
    "自動化": "ツール選定",
    "DX": "ツール選定",
    # IT系
    "PC環境構築": "PC環境構築",
    "PC設定": "PC環境構築",
    "環境構築": "PC環境構築",
    "ファイル共有": "ファイル共有",
    "ファイル送信": "ファイル共有",
    "ファイル配布": "ファイル共有",
    # 顧客・採用系
    "顧客管理": "顧客対応",
    "顧客対応": "顧客対応",
    "採用面接": "採用面接",
    "スケジュール管理": "勤怠管理",
    "タスク管理": "勤怠管理",
    "勤怠管理": "勤怠管理",
}

_ROOT_CAUSE_MAP: dict[str, str] = {
    # 部分一致パターン → canonical_root_cause
    "制度が複雑": "制度の複雑さ",
    "法律が複雑": "制度の複雑さ",
    "ルールが分かりにくい": "制度の複雑さ",
    "制度が": "制度の複雑さ",
    "ツールが未対応": "ツール未対応",
    "ツールが対応していない": "ツール未対応",
    "ソフトが対応していない": "ツール未対応",
    "ツールが使いにくい": "ツール未対応",
    "属人化": "属人化・引き継ぎ不足",
    "引き継ぎ": "属人化・引き継ぎ不足",
    "連携がない": "システム間連携不足",
    "データ連携": "システム間連携不足",
    "ツール間連携がない": "システム間連携不足",
    "連携できない": "システム間連携不足",
    "手動": "手動作業の残存",
    "手作業": "手動作業の残存",
    "転記が必要": "手動作業の残存",
    "自動化されていない": "手動作業の残存",
    "情報が散在": "情報散在",
    "情報が分からない": "情報散在",
    "知識がない": "専門知識不足",
    "専門家に頼る必要": "専門知識不足",
    "コストが高い": "コスト・リソース制約",
    "時間がかかる": "コスト・リソース制約",
}


def _normalize_field(value: str, mapping: dict[str, str], default: str = "その他") -> str:
    """フィールド値をマッピング辞書で正規化する。

    完全一致 → 部分一致の順で検索する。
    """
    # 完全一致
    if value in mapping:
        return mapping[value]
    # 部分一致
    for key, normalized in mapping.items():
        if key in value or value in key:
            return normalized
    return default


def _make_tags(pain: ExtractedPain, normalized_job: str, normalized_cause: str) -> list[str]:
    """検索・クラスタリング用タグを生成する。"""
    tags: set[str] = set()
    tags.add(pain.pain_category)
    tags.add(pain.recurrence_hint)
    if pain.severity >= 4:
        tags.add("high_severity")
    if pain.urgency >= 4:
        tags.add("high_urgency")
    if pain.willingness_to_pay_proxy >= 4:
        tags.add("high_wtp")
    if pain.builder_fit >= 4:
        tags.add("high_builder_fit")
    # ジョブのキーワードをタグ化
    for kw in ["請求書", "確定申告", "議事録", "契約書", "Excel", "自動化", "インボイス"]:
        if kw in pain.job_to_be_done or kw in pain.current_workaround:
            tags.add(kw)
    return sorted(tags)


def _make_pain_id(question_id: str, index: int) -> str:
    """pain_idを生成する。"""
    return hashlib.md5(f"{question_id}_{index}".encode()).hexdigest()[:12]


class Normalizer:
    """ExtractedPainを正規化してNormalizedPainを生成するクラス。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def normalize_one(self, pain: ExtractedPain, index: int = 0) -> NormalizedPain:
        """1件のExtractedPainを正規化する。"""
        canonical_user = _normalize_field(
            pain.persona_type + " " + pain.persona_detail, _PERSONA_MAP, "その他"
        )
        canonical_job = _normalize_field(pain.job_to_be_done, _JOB_MAP, pain.job_to_be_done)
        canonical_cause = _normalize_field(pain.root_cause, _ROOT_CAUSE_MAP, pain.root_cause)

        # canonical_problem: pain_summary を短く正規化したもの（簡易版）
        canonical_problem = pain.pain_summary[:80] if pain.pain_summary else ""

        tags = _make_tags(pain, canonical_job, canonical_cause)

        return NormalizedPain(
            pain_id=_make_pain_id(pain.question_id, index),
            question_id=pain.question_id,
            canonical_problem=canonical_problem,
            canonical_user=canonical_user,
            canonical_job=canonical_job,
            canonical_root_cause=canonical_cause,
            tags=tags,
        )

    def run(self, extracted: list[ExtractedPain], date_str: str) -> list[NormalizedPain]:
        """is_pain=TrueのExtractedPainを正規化してJSONに保存する。

        Args:
            extracted: ExtractedPainリスト
            date_str: 実行日付 (YYYY-MM-DD)

        Returns:
            NormalizedPainのリスト
        """
        pains_only = [p for p in extracted if p.is_pain]
        self.logger.info("正規化対象: %d件 / %d件", len(pains_only), len(extracted))

        normalized: list[NormalizedPain] = []
        for i, pain in enumerate(pains_only):
            try:
                n = self.normalize_one(pain, i)
                n.fetched_date = date_str[:10]
                normalized.append(n)
            except Exception as e:
                self.logger.warning("正規化エラー question_id=%s  error=%s", pain.question_id, e)

        # JSON保存
        out_dir = Path(config.DATA_DIR) / "normalized"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        data = [n.__dict__ for n in normalized]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.logger.info("normalized保存: %s (%d件)", out_path, len(normalized))
        return normalized
