"""Extractorのテスト（モックAPI使用）。"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.extractor import Extractor, _make_question_id, _parse_extracted_pains
from src.models import ExtractedPain, RawQuestion


def make_question(url: str = "https://example.com/q1", title: str = "テスト", body: str = "テスト本文" * 10) -> RawQuestion:
    return RawQuestion(
        source="chiebukuro",
        category_major="ビジネス",
        category_minor="経理",
        title=title,
        body=body,
        url=url,
        answers_count=1,
        views=100,
        posted_at=None,
        scraped_at="2026-04-05T03:00:00Z",
    )


VALID_RESPONSE = json.dumps([
    {
        "question_id": _make_question_id("https://example.com/q1"),
        "is_pain": True,
        "pain_summary": "毎月のExcel手入力が非効率",
        "persona_type": "freelancer",
        "persona_detail": "個人事業主",
        "job_to_be_done": "請求書作成",
        "pain_stage": "月末処理",
        "pain_category": "manual_reentry",
        "current_workaround": "Excelで手動管理",
        "root_cause": "ツールが対応していない",
        "severity": 4,
        "urgency": 3,
        "recurrence_hint": "monthly",
        "willingness_to_pay_proxy": 3,
        "builder_fit": 4,
        "evidence_text": "毎月手動でExcelに入力しているのですが"
    }
])


class TestExtractor:
    """Extractorのテスト。"""

    def test_make_question_id_consistent(self):
        """同じURLなら常に同じIDが返ること。"""
        url = "https://example.com/q1"
        assert _make_question_id(url) == _make_question_id(url)

    def test_make_question_id_different(self):
        """異なるURLは異なるIDになること。"""
        assert _make_question_id("https://a.com/q1") != _make_question_id("https://a.com/q2")

    def test_parse_valid_response(self):
        """正常なJSONレスポンスをパースできること。"""
        pains = _parse_extracted_pains(VALID_RESPONSE, [])
        assert len(pains) == 1
        assert pains[0].is_pain is True
        assert pains[0].pain_category == "manual_reentry"
        assert pains[0].severity == 4

    def test_parse_invalid_json_returns_fallback(self):
        """不正JSONはフォールバック（is_pain=False）を返すこと。"""
        qids = ["abc123"]
        pains = _parse_extracted_pains("これはJSONではありません", qids)
        assert len(pains) == 1
        assert pains[0].is_pain is False
        assert pains[0].question_id == "abc123"

    def test_parse_json_with_codeblock(self):
        """```json ... ``` で囲まれたレスポンスもパースできること。"""
        response = f"```json\n{VALID_RESPONSE}\n```"
        pains = _parse_extracted_pains(response, [])
        assert len(pains) == 1
        assert pains[0].is_pain is True

    def test_dry_run_returns_all_pain(self, tmp_path, monkeypatch):
        """dry-run時は全件is_pain=Trueで返ること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        extractor = Extractor()
        questions = [make_question(url=f"https://example.com/q{i}") for i in range(3)]
        result = extractor.run(questions, date_str="2026-04-05", dry_run=True)

        assert len(result) == 3
        assert all(p.is_pain for p in result)

    def test_dry_run_saves_json(self, tmp_path, monkeypatch):
        """dry-run時にJSONが保存されること。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        extractor = Extractor()
        questions = [make_question()]
        extractor.run(questions, date_str="2026-04-05", dry_run=True)

        out_file = tmp_path / "extracted" / "2026-04-05.json"
        assert out_file.exists()

    @patch("src.extractor.anthropic.Anthropic")
    def test_run_calls_api_in_batches(self, mock_anthropic_cls, tmp_path, monkeypatch):
        """5件ずつバッチでAPIを呼ぶこと。"""
        monkeypatch.setattr("src.config.config.DATA_DIR", str(tmp_path))

        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        # API呼び出しのモックレスポンス
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="[]")]
        mock_client.messages.create.return_value = mock_response

        extractor = Extractor()
        extractor.client = mock_client

        questions = [make_question(url=f"https://example.com/q{i}") for i in range(7)]
        extractor.run(questions, date_str="2026-04-05", dry_run=False)

        # 7件 / バッチサイズ5 = 2回呼ばれる
        assert mock_client.messages.create.call_count == 2
