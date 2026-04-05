"""フィルターのテスト。"""

import json
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.filter import Filter
from src.models import RawQuestion


def make_question(**kwargs) -> RawQuestion:
    """テスト用RawQuestionを作成するヘルパー。"""
    defaults = dict(
        source="chiebukuro",
        category_major="ビジネス、経済とお金",
        category_minor="企業と経営",
        title="請求書の管理が大変で困っています",
        body="毎月手動でExcelに入力しているのですが、転記ミスが多く困っています。何かよいツールはないでしょうか。",
        url="https://chiebukuro.yahoo.co.jp/question/detail/q12345",
        answers_count=2,
        views=100,
        posted_at="2026-04-04T22:00:00Z",
        scraped_at="2026-04-05T03:00:00Z",
    )
    defaults.update(kwargs)
    return RawQuestion(**defaults)


class TestFilter:
    """Filterクラスのテスト。"""

    def setup_method(self):
        self.f = Filter()

    def test_too_short_body_excluded(self):
        """30文字未満の本文は除外される。"""
        q = make_question(body="短い本文")
        assert self.f._is_too_short(q) is True

    def test_sufficient_body_passes(self):
        """30文字以上の本文は通過する。"""
        q = make_question(body="これは十分な長さの本文です。具体的な困りごとが書かれています。毎月処理に困っています。")
        assert self.f._is_too_short(q) is False

    def test_spam_url_excluded(self):
        """URL3つ以上はスパムと判定される。"""
        q = make_question(body="http://a.com http://b.com http://c.com 稼げます")
        assert self.f._is_spam(q) is True

    def test_spam_promo_excluded(self):
        """宣伝文言を含む投稿はスパムと判定される。"""
        q = make_question(body="副業で稼げる方法を教えます。無料プレゼントあり。")
        assert self.f._is_spam(q) is True

    def test_clean_question_not_spam(self):
        """正常な投稿はスパムでない。"""
        q = make_question()
        assert self.f._is_spam(q) is False

    def test_knowledge_question_filtered(self):
        """「〜とは何ですか」型は除外される。"""
        q = make_question(title="インボイス制度とは何ですか")
        assert self.f._is_knowledge_question(q) is True

    def test_comparison_question_filtered(self):
        """「どちらが良い」型は除外される。"""
        q = make_question(title="freeeとマネーフォワードどちらが良いですか")
        assert self.f._is_comparison_question(q) is True

    def test_deduplication_removes_similar(self):
        """類似度0.8以上の投稿は重複除去される。"""
        body = "毎月手動でExcelに入力しているのですが、転記ミスが多く困っています。何かよいツールはないでしょうか。"
        q1 = make_question(body=body, url="https://example.com/q1")
        q2 = make_question(body=body, url="https://example.com/q2")  # ほぼ同一
        deduped = self.f._deduplicate([q1, q2])
        assert len(deduped) == 1

    def test_deduplication_keeps_different(self):
        """十分異なる投稿は両方残る。"""
        q1 = make_question(
            body="請求書の管理が大変です。毎月手動で作っています。Excelで管理していますが限界です。",
            url="https://example.com/q1"
        )
        q2 = make_question(
            body="確定申告でインボイスの処理が複雑で困っています。どう処理すればいいですか？",
            url="https://example.com/q2"
        )
        deduped = self.f._deduplicate([q1, q2])
        assert len(deduped) == 2

    def test_past_url_excluded(self, tmp_path, monkeypatch):
        """過去7日に取得済みURLは除外される。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        # 過去1日分のデータを作成
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        past_date = (date(2026, 4, 5) - timedelta(days=1)).isoformat()
        past_file = raw_dir / f"{past_date}.json"
        past_file.write_text(
            json.dumps([{"url": "https://chiebukuro.yahoo.co.jp/question/detail/q12345"}]),
            encoding="utf-8"
        )

        past_urls = self.f._load_past_urls(date(2026, 4, 5))
        assert "https://chiebukuro.yahoo.co.jp/question/detail/q12345" in past_urls

    def test_run_saves_json(self, tmp_path, monkeypatch):
        """run()がJSONを保存すること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        questions = [make_question()]
        result = self.f.run(questions, date_str="2026-04-05")

        out_file = tmp_path / "filtered" / "2026-04-05.json"
        assert out_file.exists()
        assert len(result) > 0
