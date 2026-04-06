"""ココナラ出品一覧スクレイパー。

販売実績順に各カテゴリ上位30件を取得し、CoconalaListingとして保存する。
ページ取得にはrequests + BeautifulSoupを使用。
Nuxt.js製SSRサイトのため、HTMLを直接パースしてデータを取得する。
"""

import json
import logging
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.config import config
from src.models import CoconalaListing

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------ #
# 対象カテゴリ設定
# ※ カテゴリIDはcoconala.comのURLから確認すること
# ※ ?order=sales_count で販売実績順にソート
# ------------------------------------------------------------------ #
CATEGORIES: list[dict] = [
    # IT・開発: cid=232 (システム開発・制作), cid=237 (アプリ開発・制作)
    {"major": "IT・システム開発",            "minor": "システム開発・制作",          "cid": "232"},
    {"major": "IT・システム開発",            "minor": "アプリ開発・制作",            "cid": "237"},
    # Web制作: cid=500 (ホームページ作成・サイト制作)
    {"major": "Web制作・HP作成",             "minor": "ホームページ作成・サイト制作", "cid": "500"},
    # ビジネス代行: cid=13 (親カテゴリ), cid=429 (文字起こし・データ入力代行)
    {"major": "ビジネス代行・事務代行",      "minor": "ビジネス代行・事務代行",       "cid": "13"},
    {"major": "ビジネス代行・事務代行",      "minor": "データ入力代行",              "cid": "429"},
    # ライティング: cid=372 (記事・Webコンテンツ作成), cid=290 (外国語翻訳)
    {"major": "ライティング・翻訳",          "minor": "記事・Webコンテンツ作成",     "cid": "372"},
    {"major": "ライティング・翻訳",          "minor": "翻訳・通訳",                 "cid": "290"},
    # マーケティング: cid=311 (SNSアカウント運用・作成代行)
    {"major": "集客・マーケティング",        "minor": "SNSアカウント運用・作成代行", "cid": "311"},
]

BASE_URL = "https://coconala.com"
ROBOTS_PATH = "/robots.txt"
CATEGORY_URL_TEMPLATE = "{base}/categories/{cid}?order=sales_count&page={page}"

HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


# ------------------------------------------------------------------ #
# robots.txt チェック
# ------------------------------------------------------------------ #

def check_robots_txt() -> None:
    """robots.txtを取得してログに記録する。

    アクセス禁止パスが含まれる場合は警告を出す。
    取得失敗時も処理は継続する（サイトへのアクセス自体を止めない）。
    """
    try:
        resp = requests.get(
            urljoin(BASE_URL, ROBOTS_PATH),
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("robots.txt 取得成功:\n%s", resp.text[:2000])

        # /categories/ が Disallow になっていないか確認
        disallowed = [
            line.split(":", 1)[1].strip()
            for line in resp.text.splitlines()
            if line.lower().startswith("disallow:")
        ]
        for path in disallowed:
            if path == "/" or path.startswith("/categories"):
                logger.warning(
                    "robots.txt: /categories へのアクセスが制限されている可能性があります: %s",
                    path,
                )
    except Exception as e:
        logger.warning("robots.txt 取得失敗（処理継続）: %s", e)


# ------------------------------------------------------------------ #
# HTML取得・パース
# ------------------------------------------------------------------ #

def _fetch_html(url: str, session: requests.Session) -> str | None:
    """URLのHTMLを取得して返す。失敗時はNoneを返す。"""
    try:
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning("HTML取得失敗: url=%s  error=%s", url, e)
        return None



def _parse_listings_from_html(
    html: str,
    category_info: dict,
    scraped_at: str,
) -> list[CoconalaListing]:
    """BeautifulSoupでHTMLを直接パースして出品リストを返す。

    ページによって2種類のカードレイアウトが存在する（実際のHTMLを確認済み）:
    - c-serviceListItemList_inner: 一覧ビュー（リスト形式カテゴリ）
    - c-serviceBlockItemBlock_inner: ブロックビュー（グリッド形式カテゴリ）
    """
    listings: list[CoconalaListing] = []
    soup = BeautifulSoup(html, "html.parser")

    # レイアウト別のセレクタ設定（カード要素とフィールドの対応）
    LAYOUTS: list[dict] = [
        {
            "card": "div[class*='c-serviceListItemList_inner']",
            "title": "a[class*='c-serviceListItemColContentHeader_overview']",
            "desc": [
                "a[class*='c-serviceListItemColContentHeader_catchphrase']",
                "a[class*='c-serviceListItemColContentHeader_description']",
            ],
            "price": "a[class*='c-serviceListItemColContentFooterPrice_price'] strong",
            "score": "span[class*='c-serviceListItemColContentFooterPriceRating_score']",
            "count": "span[class*='c-serviceListItemColContentFooterPriceRating_count']",
            "seller": "div[class*='c-serviceListItemColContentFooterInfoUser_name'] a",
        },
        {
            "card": "div[class*='c-serviceBlockItemBlock_inner']",
            "title": "a[class*='c-serviceBlockItemContent_name']",
            "desc": [],
            "price": "a[class*='c-serviceBlockItemContentPrice_price'] strong",
            "score": "span[class*='c-serviceBlockItemContentPriceRating_score']",
            "count": "span[class*='c-serviceBlockItemContentPriceRating_count']",
            "seller": "div[class*='c-serviceBlockItemContentInfoUser_name'] a",
        },
    ]

    cards = []
    layout = None
    for lay in LAYOUTS:
        cards = soup.select(lay["card"])
        if cards:
            layout = lay
            logger.debug("HTMLパース: セレクタ '%s' で %d件ヒット", lay["card"], len(cards))
            break

    if not cards or layout is None:
        logger.warning("HTMLパース: 出品カードのセレクタにヒットなし（ページ構造要確認）")
        return listings

    for i, card in enumerate(cards):
        try:
            # タイトル & URL
            title_el = card.select_one(layout["title"])
            if not title_el:
                title_el = card.select_one("a[href*='/services/']")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue

            href = title_el.get("href", "") if title_el else ""
            url = urljoin(BASE_URL, href) if href and not href.startswith("http") else href
            svc_match = re.search(r"/services/(\d+)", href)
            listing_id = svc_match.group(1) if svc_match else str(i)

            # 説明文
            description = ""
            for desc_sel in layout["desc"]:
                desc_el = card.select_one(desc_sel)
                if desc_el:
                    description = desc_el.get_text(strip=True)[: config.MAX_BODY_LENGTH]
                    break

            # 価格: <strong>10,000</strong>円
            price_el = card.select_one(layout["price"])
            price = 0
            if price_el:
                price_text = re.sub(r"[^\d]", "", price_el.get_text())
                price = int(price_text) if price_text else 0

            # 評価スコア
            rating = 0.0
            score_el = card.select_one(layout["score"])
            if score_el:
                nums = re.findall(r"[\d.]+", score_el.get_text())
                if nums:
                    rating = float(nums[0])

            # レビュー件数
            review_count = 0
            count_el = card.select_one(layout["count"])
            if count_el:
                nums = re.findall(r"\d+", count_el.get_text())
                if nums:
                    review_count = int(nums[0])

            # 出品者名
            seller_el = card.select_one(layout["seller"])
            seller_name = seller_el.get_text(strip=True) if seller_el else ""

            # カード上に独立した販売件数フィールドはなく、評価数(review_count)で代用
            sales_count = review_count

            listings.append(
                CoconalaListing(
                    listing_id=listing_id,
                    title=title,
                    description=description,
                    category_major=category_info["major"],
                    category_minor=category_info["minor"],
                    price=price,
                    sales_count=sales_count,
                    review_count=review_count,
                    rating=rating,
                    seller_name=seller_name,
                    url=url,
                    scraped_at=scraped_at,
                )
            )
        except Exception as e:
            logger.debug("カードパーススキップ: %s", e)

    return listings


# ------------------------------------------------------------------ #
# メインスクレイパー
# ------------------------------------------------------------------ #

class CoconalaScraper:
    """ココナラ出品一覧スクレイパー。"""

    def __init__(self) -> None:
        """セッションとロガーを初期化する。"""
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.logger = logging.getLogger(__name__)

    def scrape_category(
        self,
        category_info: dict,
        max_listings: int | None = None,
    ) -> list[CoconalaListing]:
        """1カテゴリの出品一覧を取得して返す。

        Args:
            category_info: CATEGORIES内の1エントリ（major/minor/cid）
            max_listings: 取得上限件数。Noneの場合はconfig値を使用

        Returns:
            CoconalaListingのリスト
        """
        limit = max_listings or config.COCONALA_MAX_LISTINGS_PER_CATEGORY
        listings: list[CoconalaListing] = []
        page = 1
        scraped_at = datetime.now(timezone.utc).isoformat()

        self.logger.info(
            "カテゴリ取得開始: %s / %s (cid=%s)",
            category_info["major"],
            category_info["minor"],
            category_info["cid"],
        )

        while len(listings) < limit:
            url = CATEGORY_URL_TEMPLATE.format(
                base=BASE_URL,
                cid=category_info["cid"],
                page=page,
            )
            html = _fetch_html(url, self.session)
            if not html:
                break

            # Nuxt.js SSRのためHTMLを直接パース
            page_listings = _parse_listings_from_html(
                html, category_info, scraped_at
            )
            self.logger.debug(
                "HTMLパース: page=%d  件数=%d", page, len(page_listings)
            )

            if not page_listings:
                self.logger.info(
                    "カテゴリ %s: page=%d でデータ取得できず、終了",
                    category_info["minor"],
                    page,
                )
                break

            listings.extend(page_listings)
            self.logger.info(
                "カテゴリ %s: page=%d  取得=%d件（累計%d件）",
                category_info["minor"],
                page,
                len(page_listings),
                len(listings),
            )

            if len(page_listings) < 10:
                # ページ末尾に達した
                break

            page += 1
            time.sleep(config.SCRAPE_INTERVAL_SEC)

        return listings[:limit]

    def run(
        self,
        categories: list[dict] | None = None,
        max_listings: int | None = None,
        dry_run: bool = False,
    ) -> list[CoconalaListing]:
        """全カテゴリをスクレイプして保存する。

        Args:
            categories: 対象カテゴリリスト。Noneの場合は全カテゴリ
            max_listings: 1カテゴリあたりの取得上限
            dry_run: Trueの場合はファイル保存をスキップ

        Returns:
            全出品のCoconalaListingリスト
        """
        check_robots_txt()
        target_cats = categories or CATEGORIES
        all_listings: list[CoconalaListing] = []

        for cat in target_cats:
            try:
                listings = self.scrape_category(cat, max_listings)
                all_listings.extend(listings)
            except Exception as e:
                self.logger.error(
                    "カテゴリ %s のスクレイプ中にエラー: %s", cat.get("minor"), e
                )
            time.sleep(config.SCRAPE_INTERVAL_SEC)

        self.logger.info("スクレイプ完了: 合計 %d件", len(all_listings))

        if not dry_run:
            self._save(all_listings)

        return all_listings

    def _save(self, listings: list[CoconalaListing]) -> Path:
        """data/coconala/raw/{date}.json に保存して保存先パスを返す。"""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
        out_dir = Path(config.COCONALA_DATA_DIR) / "raw"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                [asdict(l) for l in listings],
                f,
                ensure_ascii=False,
                indent=2,
            )

        self.logger.info("raw保存完了: %s  %d件", out_path, len(listings))
        return out_path
