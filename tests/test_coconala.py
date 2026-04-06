"""ココナラモジュールのテスト。"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.coconala.analyzer import Analyzer, _fallback_analyzed, _parse_analyzed
from src.coconala.report import generate
from src.coconala.scraper import (
    CoconalaScraper,
    _extract_next_data,
    _item_to_listing,
    _parse_listings_from_html,
    _parse_listings_from_next_data,
)
from src.models import AnalyzedListing, CoconalaListing

# ------------------------------------------------------------------ #
# ヘルパー
# ------------------------------------------------------------------ #

SCRAPED_AT = "2026-04-06T03:00:00+00:00"
CATEGORY_INFO = {"major": "IT・プログラミング・開発", "minor": "システム開発・アプリ開発", "cid": "91"}


def make_listing(
    listing_id: str = "1001",
    title: str = "データ入力代行します",
    sales_count: int = 50,
    price: int = 5000,
    is_automatable: bool = True,
) -> CoconalaListing:
    return CoconalaListing(
        listing_id=listing_id,
        title=title,
        description="Excelへのデータ入力を承ります。",
        category_major=CATEGORY_INFO["major"],
        category_minor=CATEGORY_INFO["minor"],
        price=price,
        sales_count=sales_count,
        review_count=20,
        rating=4.5,
        seller_name="テスト出品者",
        url=f"https://coconala.com/services/{listing_id}",
        scraped_at=SCRAPED_AT,
    )


def make_analyzed(
    listing_id: str = "1001",
    is_automatable: bool = True,
    sales_count: int = 50,
    task_type: str = "データ入力",
) -> AnalyzedListing:
    return AnalyzedListing(
        listing_id=listing_id,
        title="データ入力代行します",
        category_major=CATEGORY_INFO["major"],
        category_minor=CATEGORY_INFO["minor"],
        price=5000,
        sales_count=sales_count,
        review_count=20,
        rating=4.5,
        url=f"https://coconala.com/services/{listing_id}",
        is_automatable=is_automatable,
        automation_summary="PythonとOpenPyXLで自動化できる。",
        task_type=task_type,
        automation_difficulty=2,
        builder_fit=4,
        monthly_demand_estimate="medium",
        saas_price_suggestion=1000,
    )


# ------------------------------------------------------------------ #
# Scraper テスト
# ------------------------------------------------------------------ #

class TestExtractNextData:
    """_extract_next_data のテスト。"""

    def test_valid_next_data(self) -> None:
        """__NEXT_DATA__スクリプトタグからJSONを抽出できる。"""
        payload = {"props": {"pageProps": {"services": []}}, "page": "/categories/91"}
        html = (
            f'<html><head>'
            f'<script id="__NEXT_DATA__" type="application/json">'
            f'{json.dumps(payload)}'
            f'</script></head><body></body></html>'
        )
        result = _extract_next_data(html)
        assert result is not None
        assert result["page"] == "/categories/91"

    def test_no_next_data(self) -> None:
        """__NEXT_DATA__がない場合はNoneを返す。"""
        html = "<html><body><p>普通のHTML</p></body></html>"
        assert _extract_next_data(html) is None

    def test_invalid_json(self) -> None:
        """不正なJSONはNoneを返す。"""
        html = '<script id="__NEXT_DATA__">{invalid json}</script>'
        assert _extract_next_data(html) is None


class TestItemToListing:
    """_item_to_listing のテスト。"""

    def test_full_item(self) -> None:
        """すべてのフィールドが揃ったitemを変換できる。"""
        item = {
            "id": "1001",
            "title": "データ入力代行",
            "description": "Excelへの入力",
            "min_price": 5000,
            "sales_count": 100,
            "review_count": 30,
            "rating": 4.8,
            "provider": {"name": "出品者A"},
            "url": "/services/1001",
        }
        result = _item_to_listing(item, CATEGORY_INFO, SCRAPED_AT)
        assert result is not None
        assert result.listing_id == "1001"
        assert result.sales_count == 100
        assert result.price == 5000
        assert result.url == "https://coconala.com/services/1001"

    def test_missing_id_returns_none(self) -> None:
        """idがないitemはNoneを返す。"""
        item = {"title": "タイトルのみ"}
        assert _item_to_listing(item, CATEGORY_INFO, SCRAPED_AT) is None

    def test_description_truncated(self) -> None:
        """説明文が500文字で切り捨てられる。"""
        item = {
            "id": "1",
            "title": "タイトル",
            "description": "あ" * 1000,
        }
        result = _item_to_listing(item, CATEGORY_INFO, SCRAPED_AT)
        assert result is not None
        assert len(result.description) <= 500

    def test_invalid_price_defaults_to_zero(self) -> None:
        """価格が不正値の場合は0になる。"""
        item = {"id": "1", "title": "テスト", "min_price": "not_a_number"}
        result = _item_to_listing(item, CATEGORY_INFO, SCRAPED_AT)
        assert result is not None
        assert result.price == 0


class TestParseListingsFromNextData:
    """_parse_listings_from_next_data のテスト。"""

    def test_services_key(self) -> None:
        """pageProps.services キーから出品リストを取得できる。"""
        next_data = {
            "props": {
                "pageProps": {
                    "services": [
                        {"id": "101", "title": "出品A", "min_price": 3000, "sales_count": 10,
                         "review_count": 5, "rating": 4.0, "url": "/services/101"},
                        {"id": "102", "title": "出品B", "min_price": 5000, "sales_count": 20,
                         "review_count": 8, "rating": 4.5, "url": "/services/102"},
                    ]
                }
            }
        }
        results = _parse_listings_from_next_data(next_data, CATEGORY_INFO, SCRAPED_AT)
        assert len(results) == 2
        assert results[0].listing_id == "101"
        assert results[1].listing_id == "102"

    def test_empty_page_props(self) -> None:
        """pagePropsが空の場合は空リストを返す。"""
        next_data = {"props": {"pageProps": {}}}
        results = _parse_listings_from_next_data(next_data, CATEGORY_INFO, SCRAPED_AT)
        assert results == []

    def test_unknown_structure(self) -> None:
        """未知の構造でも空リストを返す（クラッシュしない）。"""
        next_data = {"unknown_key": "unknown_value"}
        results = _parse_listings_from_next_data(next_data, CATEGORY_INFO, SCRAPED_AT)
        assert results == []


class TestParseListingsFromHtml:
    """_parse_listings_from_html フォールバックのテスト。"""

    def test_no_matching_selector(self) -> None:
        """マッチするセレクタがない場合は空リストを返す（クラッシュしない）。"""
        html = "<html><body><p>ヒットするセレクタなし</p></body></html>"
        results = _parse_listings_from_html(html, CATEGORY_INFO, SCRAPED_AT)
        assert results == []


# ------------------------------------------------------------------ #
# Analyzer テスト
# ------------------------------------------------------------------ #

VALID_ANALYZE_RESPONSE = json.dumps([
    {
        "listing_id": "1001",
        "is_automatable": True,
        "automation_summary": "PythonとOpenPyXLで自動化できる。",
        "task_type": "データ入力",
        "automation_difficulty": 2,
        "builder_fit": 4,
        "monthly_demand_estimate": "medium",
        "saas_price_suggestion": 1000,
    }
])


class TestParseAnalyzed:
    """_parse_analyzed のテスト。"""

    def test_valid_response(self) -> None:
        """正常なLLMレスポンスをパースできる。"""
        listings = [make_listing("1001")]
        results = _parse_analyzed(VALID_ANALYZE_RESPONSE, listings)
        assert len(results) == 1
        assert results[0].is_automatable is True
        assert results[0].task_type == "データ入力"
        assert results[0].builder_fit == 4

    def test_invalid_json_falls_back(self) -> None:
        """不正なJSONはフォールバックでis_automatable=Falseになる。"""
        listings = [make_listing("1001")]
        results = _parse_analyzed("invalid json", listings)
        assert len(results) == 1
        assert results[0].is_automatable is False

    def test_task_type_truncated(self) -> None:
        """task_typeが10文字で切り捨てられる。"""
        response = json.dumps([{
            "listing_id": "1001",
            "is_automatable": True,
            "automation_summary": "概要",
            "task_type": "あ" * 20,
            "automation_difficulty": 1,
            "builder_fit": 5,
            "monthly_demand_estimate": "high",
            "saas_price_suggestion": 2000,
        }])
        listings = [make_listing("1001")]
        results = _parse_analyzed(response, listings)
        assert len(results[0].task_type) <= 10

    def test_demand_clamped(self) -> None:
        """monthly_demand_estimateが不正値の場合はlowになる。"""
        response = json.dumps([{
            "listing_id": "1001",
            "is_automatable": True,
            "automation_summary": "概要",
            "task_type": "入力",
            "automation_difficulty": 1,
            "builder_fit": 5,
            "monthly_demand_estimate": "invalid_value",
            "saas_price_suggestion": 2000,
        }])
        listings = [make_listing("1001")]
        results = _parse_analyzed(response, listings)
        assert results[0].monthly_demand_estimate == "low"

    def test_saas_price_clamped(self) -> None:
        """saas_price_suggestionが500〜10000に収まる。"""
        response = json.dumps([{
            "listing_id": "1001",
            "is_automatable": True,
            "automation_summary": "概要",
            "task_type": "入力",
            "automation_difficulty": 1,
            "builder_fit": 5,
            "monthly_demand_estimate": "high",
            "saas_price_suggestion": 999999,
        }])
        listings = [make_listing("1001")]
        results = _parse_analyzed(response, listings)
        assert results[0].saas_price_suggestion == 10000

    def test_missing_listing_id_fills_fallback(self) -> None:
        """LLMが一部のlisting_idを返さなかった場合はフォールバックで補完される。"""
        response = json.dumps([])  # LLMが何も返さなかった
        listings = [make_listing("1001"), make_listing("1002")]
        results = _parse_analyzed(response, listings)
        assert len(results) == 2
        assert all(not r.is_automatable for r in results)


class TestAnalyzerBatch:
    """Analyzer.analyze_batch のテスト（APIモック）。"""

    def test_analyze_batch_success(self) -> None:
        """APIが正常に返した場合、AnalyzedListingのリストが返る。"""
        analyzer = Analyzer()
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=VALID_ANALYZE_RESPONSE)]

        with patch.object(analyzer.client.messages, "create", return_value=mock_response):
            listings = [make_listing("1001")]
            results = analyzer.analyze_batch(listings)

        assert len(results) == 1
        assert results[0].is_automatable is True

    def test_analyze_batch_api_error_returns_fallback(self) -> None:
        """APIエラー時はフォールバック（is_automatable=False）が返る。"""
        import anthropic as _anthropic

        analyzer = Analyzer()
        with patch.object(
            analyzer.client.messages,
            "create",
            side_effect=_anthropic.APIError("error", request=MagicMock(), body=None),
        ):
            listings = [make_listing("1001")]
            results = analyzer.analyze_batch(listings)

        assert len(results) == 1
        assert results[0].is_automatable is False


# ------------------------------------------------------------------ #
# Report テスト
# ------------------------------------------------------------------ #

class TestReport:
    """report.generate のテスト。"""

    def test_generate_basic(self) -> None:
        """基本的なレポートが生成できる。"""
        analyzed = [
            make_analyzed("1001", is_automatable=True, sales_count=100, task_type="データ入力"),
            make_analyzed("1002", is_automatable=False, sales_count=50, task_type=""),
            make_analyzed("1003", is_automatable=True, sales_count=80, task_type="文書作成"),
        ]
        report = generate(analyzed, "2026-04-06_0300")
        assert "ココナラ需要分析レポート" in report
        assert "分析出品数: 3件" in report
        assert "自動化可能: 2件" in report
        assert "データ入力代行します" in report

    def test_generate_empty(self) -> None:
        """出品が0件でもクラッシュしない。"""
        report = generate([], "2026-04-06_0300")
        assert "ココナラ需要分析レポート" in report
        assert "分析出品数: 0件" in report

    def test_generate_top10_limit(self) -> None:
        """自動化可能な出品が10件を超えても正常にレポートが生成される。"""
        analyzed = [
            make_analyzed(str(i), is_automatable=True, sales_count=i * 10)
            for i in range(1, 16)
        ]
        report = generate(analyzed, "2026-04-06_0300")
        # TOP10のみ掲載されることを確認（#11以降はランク外）
        assert "#10" in report
        assert "#11" not in report

    def test_generate_sort_by_sales(self) -> None:
        """販売実績順でソートされている。"""
        analyzed = [
            make_analyzed("low", is_automatable=True, sales_count=10),
            make_analyzed("high", is_automatable=True, sales_count=200),
        ]
        report = generate(analyzed, "2026-04-06_0300")
        pos_high = report.find("#1")
        pos_low = report.find("#2")
        assert pos_high < pos_low
