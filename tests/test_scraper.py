"""スクレイパーのテスト。"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.models import RawQuestion
from src.scraper.chiebukuro import ChiebukuroScraper, CATEGORIES


class TestChiebukuroScraper:
    """ChiebukuroScraperのテスト。"""

    def test_dry_run_returns_sample_data(self, tmp_path, monkeypatch):
        """dry-run時にサンプルデータが返ること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        scraper = ChiebukuroScraper()
        results = scraper.run(date_str="2026-04-05", categories=None, limit=5, dry_run=True)

        assert len(results) > 0
        for q in results:
            assert isinstance(q, RawQuestion)
            assert q.source == "chiebukuro"
            assert q.url.startswith("https://")
            assert len(q.body) > 0

    def test_dry_run_saves_json(self, tmp_path, monkeypatch):
        """dry-run時にJSONが保存されること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        scraper = ChiebukuroScraper()
        scraper.run(date_str="2026-04-05", categories=None, limit=5, dry_run=True)

        out_file = tmp_path / "raw" / "2026-04-05.json"
        assert out_file.exists()

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) > 0

    def test_categories_defined(self):
        """CATEGORIESに13カテゴリが定義されていること。"""
        assert len(CATEGORIES) == 13
        for cat in CATEGORIES:
            assert "major" in cat
            assert "minor" in cat
            assert "cid" in cat

    def test_scrape_category_unknown_returns_empty(self):
        """未定義カテゴリは空リストを返すこと。"""
        scraper = ChiebukuroScraper()
        result = scraper.scrape_category("存在しない", "カテゴリ", 5)
        assert result == []

    def test_get_question_ids_empty_on_error(self):
        """HTTP失敗時は空リストを返すこと。"""
        scraper = ChiebukuroScraper()
        with patch.object(scraper, "_get", return_value=None):
            ids = scraper._get_question_ids("https://example.com", 10)
        assert ids == []
