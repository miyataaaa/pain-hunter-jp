"""Scorerのテスト。"""

import json
from pathlib import Path

import pytest

from src.scorer import Scorer, _estimate_solution_gap, _estimate_productability, _calc_recurrence_score
from src.models import ExtractedPain, NormalizedPain, PainCluster


def make_extracted_pain(question_id: str = "q001", **kwargs) -> ExtractedPain:
    defaults = dict(
        question_id=question_id,
        is_pain=True,
        pain_summary="テストペイン",
        persona_type="freelancer",
        persona_detail="個人事業主",
        job_to_be_done="請求書作成",
        pain_stage="月末処理",
        pain_category="manual_reentry",
        current_workaround="Excelで手動管理",
        root_cause="ツールが対応していない",
        severity=4,
        urgency=3,
        recurrence_hint="monthly",
        willingness_to_pay_proxy=3,
        builder_fit=4,
        evidence_text="毎月手動でExcelに入力しています",
    )
    defaults.update(kwargs)
    return ExtractedPain(**defaults)


def make_cluster(**kwargs) -> PainCluster:
    defaults = dict(
        cluster_id="cl_001",
        cluster_label="請求書管理の非効率",
        canonical_problem="Excelでの手動管理が非効率",
        representative_user="フリーランス",
        representative_job="請求書・経理事務",
        root_cause_summary="手動プロセスの非効率",
        question_ids=["q001"],
        pain_ids=["p001"],
        cluster_size=1,
    )
    defaults.update(kwargs)
    return PainCluster(**defaults)


class TestScorer:
    """Scorerのテスト。"""

    def setup_method(self):
        self.s = Scorer()

    def test_estimate_solution_gap_weak_workaround(self):
        """Excelなど弱いworkaroundはスコアが高い。"""
        score = _estimate_solution_gap("Excelで手動管理")
        assert score >= 0.7

    def test_estimate_solution_gap_strong_workaround(self):
        """freeeなど強いworkaroundはスコアが低い。"""
        score = _estimate_solution_gap("freeeで管理できている")
        assert score <= 0.4

    def test_estimate_solution_gap_empty(self):
        """workaroundが空なら中間値。"""
        score = _estimate_solution_gap("")
        assert 0.4 <= score <= 0.6

    def test_estimate_productability_daily(self):
        """dailyは高いproductabilityスコア。"""
        score = _estimate_productability(["daily", "daily"])
        assert score >= 0.9

    def test_estimate_productability_one_off(self):
        """one_offは低いproductabilityスコア。"""
        score = _estimate_productability(["one_off"])
        assert score <= 0.3

    def test_calc_recurrence_score(self):
        """クラスタサイズが多いほどrecurrence_scoreが高い。"""
        s_small = _calc_recurrence_score(1, 1)
        s_large = _calc_recurrence_score(10, 1)
        assert s_large > s_small

    def test_score_cluster_updates_fields(self):
        """score_cluster()でopportunity_scoreが更新されること。"""
        cluster = make_cluster()
        pain_lookup = {"q001": make_extracted_pain()}

        result = self.s.score_cluster(cluster, pain_lookup)
        assert result.opportunity_score > 0
        assert result.avg_severity == 4.0
        assert result.avg_builder_fit == 4.0

    def test_opportunity_score_range(self):
        """opportunity_scoreが0〜1の範囲に収まること。"""
        cluster = make_cluster()
        pain_lookup = {"q001": make_extracted_pain(severity=5, builder_fit=5, willingness_to_pay_proxy=5)}
        result = self.s.score_cluster(cluster, pain_lookup)
        assert 0.0 <= result.opportunity_score <= 1.0

    def test_run_sorts_by_score(self, tmp_path, monkeypatch):
        """run()がopportunity_score降順でソートすること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        cluster_low = make_cluster(cluster_id="cl_low", question_ids=["q_low"])
        cluster_high = make_cluster(cluster_id="cl_high", question_ids=["q_high"])

        pain_low = make_extracted_pain(question_id="q_low", severity=1, builder_fit=1, willingness_to_pay_proxy=1, recurrence_hint="one_off")
        pain_high = make_extracted_pain(question_id="q_high", severity=5, builder_fit=5, willingness_to_pay_proxy=5, recurrence_hint="daily")

        extracted = [pain_low, pain_high]
        result = self.s.run([cluster_low, cluster_high], [], extracted, date_str="2026-04-05")

        assert result[0].opportunity_score >= result[1].opportunity_score

    def test_run_saves_json(self, tmp_path, monkeypatch):
        """run()がJSONを保存すること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        cluster = make_cluster()
        extracted = [make_extracted_pain()]
        self.s.run([cluster], [], extracted, date_str="2026-04-05")

        out_file = tmp_path / "scored" / "2026-04-05.json"
        assert out_file.exists()
