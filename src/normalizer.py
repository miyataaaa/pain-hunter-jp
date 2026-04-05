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
    "請求書作成": "請求書・経理事務",
    "請求書管理": "請求書・経理事務",
    "経理": "請求書・経理事務",
    "会計": "請求書・経理事務",
    "帳簿": "請求書・経理事務",
    "確定申告": "税務申告・確定申告",
    "税務": "税務申告・確定申告",
    "インボイス": "税務申告・確定申告",
    "消費税": "税務申告・確定申告",
    "契約書": "契約・法務",
    "契約レビュー": "契約・法務",
    "NDA": "契約・法務",
    "法務": "契約・法務",
    "議事録": "会議・ドキュメント作成",
    "資料作成": "会議・ドキュメント作成",
    "提案書": "会議・ドキュメント作成",
    "報告書": "会議・ドキュメント作成",
    "業務効率化": "業務プロセス改善",
    "自動化": "業務プロセス改善",
    "DX": "業務プロセス改善",
    "ツール選定": "ツール・システム選定",
    "ツール導入": "ツール・システム選定",
    "システム導入": "ツール・システム選定",
    "顧客管理": "顧客対応・CRM",
    "顧客対応": "顧客対応・CRM",
    "スケジュール管理": "スケジュール・タスク管理",
    "タスク管理": "スケジュール・タスク管理",
}

_ROOT_CAUSE_MAP: dict[str, str] = {
    "制度が複雑": "制度・法規制の複雑性",
    "法律が複雑": "制度・法規制の複雑性",
    "ルールが分かりにくい": "制度・法規制の複雑性",
    "ツールが対応していない": "既存ツールの機能不足",
    "ツールが使いにくい": "既存ツールの機能不足",
    "ソフトが対応していない": "既存ツールの機能不足",
    "手動作業が多い": "手動プロセスの非効率",
    "自動化されていない": "手動プロセスの非効率",
    "転記が必要": "手動プロセスの非効率",
    "ツール間連携がない": "ツール間のサイロ化",
    "連携できない": "ツール間のサイロ化",
    "情報が散在": "情報散在・アクセス困難",
    "情報が分からない": "情報散在・アクセス困難",
    "知識がない": "専門知識の不足",
    "専門家に頼る必要": "専門知識の不足",
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
