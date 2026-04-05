"""Clustererのテスト。"""

import json
from pathlib import Path

import pytest

from src.clusterer import Clusterer, _cluster_key, _tag_overlap
from src.models import NormalizedPain, PainCluster


def make_normalized_pain(**kwargs) -> NormalizedPain:
    defaults = dict(
        pain_id="p001",
        question_id="q001",
        canonical_problem="Excelでの請求書管理が非効率",
        canonical_user="フリーランス",
        canonical_job="請求書・経理事務",
        canonical_root_cause="手動プロセスの非効率",
        tags=["manual_reentry", "monthly", "high_severity"],
    )
    defaults.update(kwargs)
    return NormalizedPain(**defaults)


class TestClusterer:
    """Clustererのテスト。"""

    def setup_method(self):
        self.c = Clusterer()

    def test_cluster_key_consistent(self):
        """同じペインは同じキーを返すこと。"""
        pain = make_normalized_pain()
        assert _cluster_key(pain) == _cluster_key(pain)

    def test_cluster_key_groups_similar(self):
        """job + root_cause が同じペインは同じキーになること。"""
        p1 = make_normalized_pain(pain_id="p001", canonical_job="請求書・経理事務", canonical_root_cause="手動プロセスの非効率")
        p2 = make_normalized_pain(pain_id="p002", canonical_job="請求書・経理事務", canonical_root_cause="手動プロセスの非効率")
        assert _cluster_key(p1) == _cluster_key(p2)

    def test_cluster_key_separates_different(self):
        """異なるjobは異なるキーになること。"""
        p1 = make_normalized_pain(canonical_job="請求書・経理事務")
        p2 = make_normalized_pain(canonical_job="税務申告・確定申告")
        assert _cluster_key(p1) != _cluster_key(p2)

    def test_tag_overlap_count(self):
        """タグ一致数が正しく計算されること。"""
        assert _tag_overlap(["a", "b", "c"], ["b", "c", "d"]) == 2
        assert _tag_overlap(["a"], ["b"]) == 0

    def test_run_groups_same_key(self, tmp_path, monkeypatch):
        """同じキーのペインは1クラスタにまとまること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))
        monkeypatch.setattr("src.config.config.LOOKBACK_DAYS", 0)

        pains = [
            make_normalized_pain(pain_id="p001", question_id="q001"),
            make_normalized_pain(pain_id="p002", question_id="q002"),
        ]
        clusters = self.c.run(pains, date_str="2026-04-05")

        assert len(clusters) == 1
        assert clusters[0].cluster_size == 2

    def test_run_separates_different_keys(self, tmp_path, monkeypatch):
        """異なるキーのペインは別クラスタになること（canonical_problemも異なる場合）。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))
        monkeypatch.setattr("src.config.config.LOOKBACK_DAYS", 0)

        pains = [
            make_normalized_pain(
                pain_id="p001", question_id="q001",
                canonical_job="請求書作成",
                canonical_problem="請求書作成の非効率",
            ),
            make_normalized_pain(
                pain_id="p002", question_id="q002",
                canonical_job="確定申告",
                canonical_problem="確定申告の手続き負荷",
            ),
        ]
        clusters = self.c.run(pains, date_str="2026-04-05")

        assert len(clusters) >= 2

    def test_run_saves_json(self, tmp_path, monkeypatch):
        """run()がJSONを保存すること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))
        monkeypatch.setattr("src.config.config.LOOKBACK_DAYS", 0)

        pains = [make_normalized_pain()]
        self.c.run(pains, date_str="2026-04-05")

        out_file = tmp_path / "clustered" / "2026-04-05.json"
        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert "cluster_id" in data[0]

    def test_run_empty_input(self, tmp_path, monkeypatch):
        """空入力でも正常終了すること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))
        monkeypatch.setattr("src.config.config.LOOKBACK_DAYS", 0)

        clusters = self.c.run([], date_str="2026-04-05")
        assert clusters == []
