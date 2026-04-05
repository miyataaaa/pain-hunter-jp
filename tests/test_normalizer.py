"""Normalizerのテスト。"""

import json
from pathlib import Path

import pytest

from src.normalizer import Normalizer, _normalize_field, _PERSONA_MAP, _JOB_MAP
from src.models import ExtractedPain, NormalizedPain


def make_extracted_pain(**kwargs) -> ExtractedPain:
    defaults = dict(
        question_id="abc123",
        is_pain=True,
        pain_summary="毎月のExcel手入力が非効率",
        persona_type="freelancer",
        persona_detail="個人事業主のデザイナー",
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


class TestNormalizer:
    """Normalizerのテスト。"""

    def setup_method(self):
        self.n = Normalizer()

    def test_normalize_field_exact_match(self):
        """完全一致マッピングが機能すること。"""
        result = _normalize_field("freelancer", _PERSONA_MAP, "その他")
        assert result == "フリーランス"

    def test_normalize_field_partial_match(self):
        """部分一致マッピングが機能すること。"""
        result = _normalize_field("個人事業主のデザイナー", _PERSONA_MAP, "その他")
        assert result == "フリーランス"

    def test_normalize_field_fallback(self):
        """マッチなしはデフォルト値を返すこと。"""
        result = _normalize_field("存在しない値", _PERSONA_MAP, "デフォルト")
        assert result == "デフォルト"

    def test_normalize_one_produces_normalized_pain(self):
        """normalize_one()がNormalizedPainを返すこと。"""
        pain = make_extracted_pain()
        result = self.n.normalize_one(pain)

        assert isinstance(result, NormalizedPain)
        assert result.question_id == "abc123"
        assert result.canonical_user == "フリーランス"
        assert result.canonical_job == "請求書・経理事務"
        assert len(result.tags) > 0

    def test_normalize_one_high_severity_tag(self):
        """severity>=4の場合high_severityタグが付くこと。"""
        pain = make_extracted_pain(severity=4)
        result = self.n.normalize_one(pain)
        assert "high_severity" in result.tags

    def test_normalize_one_pain_id_unique(self):
        """pain_idがユニークであること（異なるquestion_idから）。"""
        pain1 = make_extracted_pain(question_id="aaa")
        pain2 = make_extracted_pain(question_id="bbb")
        r1 = self.n.normalize_one(pain1, 0)
        r2 = self.n.normalize_one(pain2, 0)
        assert r1.pain_id != r2.pain_id

    def test_run_skips_non_pain(self, tmp_path, monkeypatch):
        """is_pain=Falseの投稿は正規化をスキップすること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        pain_true = make_extracted_pain(is_pain=True, question_id="aaa")
        pain_false = make_extracted_pain(is_pain=False, question_id="bbb")

        result = self.n.run([pain_true, pain_false], date_str="2026-04-05")
        assert len(result) == 1
        assert result[0].question_id == "aaa"

    def test_run_saves_json(self, tmp_path, monkeypatch):
        """run()がJSONを保存すること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        pains = [make_extracted_pain()]
        self.n.run(pains, date_str="2026-04-05")

        out_file = tmp_path / "normalized" / "2026-04-05.json"
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert "pain_id" in data[0]
