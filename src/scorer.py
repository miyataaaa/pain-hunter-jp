"""Opportunity Scorerモジュール。DESIGN.mdの合成式でopportunity_scoreを算出する。"""

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from src.config import config
from src.models import ExtractedPain, NormalizedPain, PainCluster


def _load_past_extracted(today: date) -> list[ExtractedPain]:
    """過去LOOKBACK_DAYS日分のExtractedPainを読み込む。"""
    ext_dir = Path(config.DATA_DIR) / "extracted"
    results: list[ExtractedPain] = []
    logger = logging.getLogger(__name__)
    for i in range(1, config.LOOKBACK_DAYS + 1):
        past_date = today - timedelta(days=i)
        for past_file in sorted(ext_dir.glob(f"{past_date.isoformat()}*.json")):
            try:
                with open(past_file, encoding="utf-8") as f:
                    items = json.load(f)
                for item in items:
                    results.append(ExtractedPain(**item))
            except Exception as e:
                logger.warning("過去extractedデータ読み込みエラー: %s  error=%s", past_file, e)
    return results


# recurrence_hint → スコア変換テーブル
_RECURRENCE_SCORE_MAP: dict[str, float] = {
    "daily": 1.0,
    "weekly": 0.8,
    "monthly": 0.6,
    "one_off": 0.2,
    "unknown": 0.4,
}

# 高スコア（代替手段が弱い = 事業機会がある）→ 0.7〜1.0
_HIGH_GAP_KEYWORDS = [
    "手動", "手作業", "手書き", "手入力", "目視",
    "Excel", "エクセル", "コピー", "貼り付け",
    "毎回", "都度", "ゼロから",
    "対処なし", "放置", "我慢", "泣き寝入り",
    "自力で調べ", "ネット検索", "毎回聞", "都度確認",
    "紙", "FAX", "電話で確認",
    "税理士に聞く", "専門家に依頼", "仕方なく", "諦めて",
    "とりあえず", "なんとか",
]

# 低スコア（既存の解決策がある = 参入が難しい）→ 0.1〜0.3
_LOW_GAP_KEYWORDS = [
    "SaaS", "専用ソフト", "専用ツール", "専用アプリ",
    "freee", "マネーフォワード", "弥生",
    "自動化済み", "API連携", "クラウド会計",
    "自動化できている", "解決済み",
]


def _estimate_solution_gap(workaround: str) -> float:
    """current_workaroundのキーワードからsolution_gap_scoreを推定する。

    弱いworkaround（手動・Excel等）が多いほどスコアが高い。
    Returns: 0.0〜1.0
    """
    if not workaround:
        return 0.5

    high_count = sum(1 for kw in _HIGH_GAP_KEYWORDS if kw in workaround)
    low_count = sum(1 for kw in _LOW_GAP_KEYWORDS if kw in workaround)

    if low_count > 0 and high_count == 0:
        return 0.2
    if high_count >= 2:
        return 0.9
    if high_count == 1:
        return 0.7
    return 0.5


def _estimate_productability(recurrence_hints: list[str]) -> float:
    """recurrence_hintの分布からproductability_scoreを算出する。

    繰り返し頻度が高いほどプロダクト化しやすい。
    Returns: 0.0〜1.0
    """
    if not recurrence_hints:
        return 0.3

    scores = [_RECURRENCE_SCORE_MAP.get(h, 0.4) for h in recurrence_hints]
    avg = sum(scores) / len(scores)
    return round(avg, 3)


def _calc_recurrence_score(cluster_size: int, date_count: int) -> float:
    """クラスタサイズと出現日数からrecurrence_scoreを算出する。

    - cluster_size: 件数（多いほど高い）
    - date_count: 異なる日に出現した回数（複数日出現 = 繰り返し性が高い）
    Returns: 0.0〜1.0
    """
    size_score = min(cluster_size / 10.0, 1.0)
    recurrence_bonus = min(date_count / config.LOOKBACK_DAYS, 1.0)
    return round((size_score * 0.7 + recurrence_bonus * 0.3), 3)


class Scorer:
    """PainClusterのopportunity_scoreを算出するクラス。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def _build_pain_lookup(
        self, extracted: list[ExtractedPain]
    ) -> dict[str, ExtractedPain]:
        """question_id → ExtractedPain の辞書を作成する。"""
        return {p.question_id: p for p in extracted if p.is_pain}

    def score_cluster(
        self,
        cluster: PainCluster,
        pain_lookup: dict[str, ExtractedPain],
    ) -> PainCluster:
        """1クラスタのスコアを算出して更新する。"""
        # クラスタに属するExtractedPainを取得
        cluster_pains = [pain_lookup[qid] for qid in cluster.question_ids if qid in pain_lookup]

        if not cluster_pains:
            self.logger.warning("クラスタ %s: ExtractedPain未発見", cluster.cluster_id)
            return cluster

        # 平均スコア算出
        cluster.avg_severity = round(sum(p.severity for p in cluster_pains) / len(cluster_pains), 2)
        cluster.avg_urgency = round(sum(p.urgency for p in cluster_pains) / len(cluster_pains), 2)
        cluster.avg_wtp_proxy = round(sum(p.willingness_to_pay_proxy for p in cluster_pains) / len(cluster_pains), 2)
        cluster.avg_builder_fit = round(sum(p.builder_fit for p in cluster_pains) / len(cluster_pains), 2)

        # severity_score: 平均severityを0-1にスケール
        severity_score = (cluster.avg_severity - 1) / 4.0

        # recurrence_score: クラスタサイズ + 出現日数
        cluster.recurrence_score = _calc_recurrence_score(cluster.cluster_size, cluster.date_count)

        # solution_gap_score: workaroundの弱さを推定
        workarounds = " ".join(p.current_workaround for p in cluster_pains)
        cluster.solution_gap_score = _estimate_solution_gap(workarounds)

        # wtp_score: 0-1にスケール
        wtp_score = (cluster.avg_wtp_proxy - 1) / 4.0

        # builder_fit_score: 0-1にスケール
        builder_fit_score = (cluster.avg_builder_fit - 1) / 4.0

        # productability_score: recurrence_hintの分布から算出
        recurrence_hints = [p.recurrence_hint for p in cluster_pains]
        cluster.productability_score = _estimate_productability(recurrence_hints)

        # opportunity_score: DESIGN.mdの合成式
        cluster.opportunity_score = round(
            0.20 * severity_score
            + 0.20 * cluster.recurrence_score
            + 0.20 * cluster.solution_gap_score
            + 0.15 * wtp_score
            + 0.15 * builder_fit_score
            + 0.10 * cluster.productability_score,
            3,
        )

        self.logger.debug(
            "クラスタ %s スコア: opportunity=%.3f severity=%.2f recurrence=%.2f gap=%.2f",
            cluster.cluster_id,
            cluster.opportunity_score,
            severity_score,
            cluster.recurrence_score,
            cluster.solution_gap_score,
        )

        return cluster

    def run(
        self,
        clusters: list[PainCluster],
        normalized: list[NormalizedPain],
        extracted: list[ExtractedPain],
        date_str: str,
    ) -> list[PainCluster]:
        """全クラスタのスコアを算出してJSONに保存する。

        Args:
            clusters: PainClusterリスト
            normalized: NormalizedPainリスト（参照用）
            extracted: ExtractedPainリスト（スコア値取得用）
            date_str: 実行日付 (YYYY-MM-DD)

        Returns:
            スコア更新済みPainClusterリスト（opportunity_score降順）
        """
        today = date.fromisoformat(date_str[:10])
        past_extracted = _load_past_extracted(today)
        all_extracted = extracted + past_extracted
        self.logger.info("extracted: 当日%d件 + 過去%d件", len(extracted), len(past_extracted))

        pain_lookup = self._build_pain_lookup(all_extracted)
        self.logger.info("スコアリング対象: %dクラスタ", len(clusters))

        scored: list[PainCluster] = []
        for cluster in clusters:
            try:
                scored_cluster = self.score_cluster(cluster, pain_lookup)
                scored.append(scored_cluster)
            except Exception as e:
                self.logger.warning("スコアリングエラー cluster_id=%s  error=%s", cluster.cluster_id, e)
                scored.append(cluster)

        # opportunity_score降順ソート
        scored.sort(key=lambda c: c.opportunity_score, reverse=True)

        # JSON保存
        out_dir = Path(config.DATA_DIR) / "scored"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        data = [c.__dict__ for c in scored]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        top3 = scored[:3]
        self.logger.info(
            "scored保存: %s  TOP3: %s",
            out_path,
            [(c.cluster_label, c.opportunity_score) for c in top3],
        )
        return scored
