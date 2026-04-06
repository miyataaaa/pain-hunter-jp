"""Yahoo!知恵袋スクレイパー実装モジュール。

robots.txt確認結果（2026年時点）:
  - /category/{id}/question/list パス: アクセス許可
  - /qa/question_detail/ (detail.chiebukuro.yahoo.co.jp): アクセス許可
  - /api/, /auth/ 等の内部パス: アクセス禁止
  → カテゴリ一覧ページと質問個別ページのみアクセスする。

URL構成の変更（v1→v2）:
  - カテゴリ: https://chiebukuro.yahoo.co.jp/category/{new_cid}/question/list
  - 質問詳細: https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/{qid}
  旧 /ct/cid/{old_cid}/new/ は廃止（404）。
"""

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from src.config import config
from src.models import RawQuestion
from src.scraper.base import BaseScraper


# DESIGN.md「ジャンル探索方針」に記載の3ジャンル・13サブカテゴリ
# cid: 2026年4月時点の新カテゴリID
CATEGORIES: list[dict] = [
    # === 業務・フリーランス系（6） ===
    {"major": "職業とキャリア",       "minor": "仕事効率化・ノウハウ",         "cid": "2078297897"},
    {"major": "暮らしと生活ガイド",   "minor": "役所、手続き",               "cid": "2078297956"},
    {"major": "ビジネス、経済とお金", "minor": "インターネットビジネス、SOHO",  "cid": "2078297802"},
    {"major": "ビジネス、経済とお金", "minor": "会計、経理、財務",            "cid": "2078297803"},
    {"major": "ビジネス、経済とお金", "minor": "起業",                      "cid": "2078297806"},
    {"major": "ビジネス、経済とお金", "minor": "企業と経営",                 "cid": "2078297793"},
    # === 生活実務系（4） ===
    {"major": "暮らしと生活ガイド",   "minor": "郵便、宅配",                "cid": "2079822377"},
    {"major": "暮らしと生活ガイド",   "minor": "家事",                      "cid": "2078297950"},
    {"major": "暮らしと生活ガイド",   "minor": "料理、レシピ",               "cid": "2078297945"},
    {"major": "暮らしと生活ガイド",   "minor": "不動産",                    "cid": "2078297953"},
    # === 嗜好・パッション系（2） ===
    {"major": "暮らしと生活ガイド",   "minor": "ペット",                    "cid": "2078297852"},
    {"major": "健康、美容とファッション", "minor": "コスメ、美容",             "cid": "2078297855"},
]

MAIN_HOST = "chiebukuro.yahoo.co.jp"
DETAIL_HOST = "detail.chiebukuro.yahoo.co.jp"
CATEGORY_LIST_URL = f"https://{MAIN_HOST}/category/{{cid}}/question/list"
QUESTION_DETAIL_URL = f"https://{DETAIL_HOST}/qa/question_detail/{{qid}}"


class ChiebukuroScraper(BaseScraper):
    """Yahoo!知恵袋から質問を取得するスクレイパー。"""

    def __init__(self) -> None:
        super().__init__()
        self.logger = logging.getLogger(__name__)

    def scrape_category(self, category_major: str, category_minor: str, limit: int) -> list[RawQuestion]:
        """指定カテゴリの新着質問ページから質問を取得する。

        Args:
            category_major: 大カテゴリ名
            category_minor: 中カテゴリ名
            limit: 最大取得件数

        Returns:
            RawQuestionのリスト
        """
        cat_info = next(
            (c for c in CATEGORIES if c["major"] == category_major and c["minor"] == category_minor),
            None,
        )
        if not cat_info:
            self.logger.warning("未定義カテゴリ: %s > %s", category_major, category_minor)
            return []

        url = CATEGORY_LIST_URL.format(cid=cat_info["cid"])
        self.logger.info("カテゴリページ取得: %s > %s url=%s", category_major, category_minor, url)

        question_ids = self._get_question_ids(url, limit)
        self.logger.info("質問ID取得: %d件", len(question_ids))

        questions: list[RawQuestion] = []
        for qid in question_ids:
            q_url = QUESTION_DETAIL_URL.format(qid=qid)
            q = self._scrape_question(q_url, category_major, category_minor)
            if q:
                questions.append(q)

        return questions

    def _get_question_ids(self, category_url: str, limit: int) -> list[str]:
        """カテゴリ一覧ページからページに埋め込まれた質問IDを抽出する。

        質問詳細リンクはJSレンダリングのため、ページソースに埋め込まれた
        qXXXXXXXXXXX 形式のIDをregexで抽出する。
        """
        resp = self._get(category_url)
        if not resp:
            return []

        try:
            resp.raise_for_status()
        except ValueError as e:
            self.logger.warning("カテゴリページHTTPエラー url=%s error=%s", category_url, e)
            return []

        # 質問IDは「q + 11桁以上の数字」のパターンでページに埋め込まれている
        ids = list(dict.fromkeys(re.findall(r"q\d{11,}", resp.text)))
        return ids[:limit]

    def _scrape_question(
        self, url: str, category_major: str, category_minor: str
    ) -> RawQuestion | None:
        """質問個別ページ（detail.chiebukuro.yahoo.co.jp）からデータを抽出する。"""
        resp = self._get(url)
        if not resp:
            return None

        try:
            resp.raise_for_status()
        except ValueError as e:
            self.logger.debug("質問ページHTTPエラー url=%s error=%s", url, e)
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        scraped_at = datetime.now(timezone.utc).isoformat()

        try:
            # タイトル: <h1> が質問タイトルと同内容
            h1 = soup.find("h1")
            title = h1.get_text(strip=True) if h1 else ""

            # 質問本文: QuestionItem__Text クラスを持つ div
            q_item = soup.find("div", class_=re.compile(r"QuestionItem.*Item", re.I))
            body = ""
            answers_count: int | None = None
            posted_at: str | None = None
            views: int | None = None

            if q_item:
                text_div = q_item.find("div", class_=re.compile(r"QuestionItem.*Text", re.I))
                if text_div:
                    body = text_div.get_text(separator="\n", strip=True)

                # 回答数: QuestionItem__Answer クラスの <p> タグ（例: "3回答"）
                ans_el = q_item.find(class_=re.compile(r"QuestionItem.*Answer", re.I))
                if ans_el:
                    m = re.search(r"(\d+)回答", ans_el.get_text(strip=True))
                    if m:
                        answers_count = int(m.group(1))

                # 投稿日時: UserInfo__Date クラス（例: "2026/4/5 17:59"）
                date_el = q_item.find(class_=re.compile(r"UserInfo.*Date|Date.*UserInfo", re.I))
                if date_el:
                    posted_at = date_el.get_text(strip=True)

                # 閲覧数: QuestionItem__Sub 内の "N閲覧"
                sub_div = q_item.find("div", class_=re.compile(r"QuestionItem.*Sub", re.I))
                if sub_div:
                    m2 = re.search(r"(\d+)閲覧", sub_div.get_text(strip=True))
                    if m2:
                        views = int(m2.group(1))

            # タイトルも本文もなければスキップ
            if not title and not body:
                self.logger.debug("タイトル・本文なし: %s", url)
                return None

            return RawQuestion(
                source="chiebukuro",
                category_major=category_major,
                category_minor=category_minor,
                title=title,
                body=body[: config.MAX_BODY_LENGTH * 2],  # 保存時は緩め、LLM送信時に制限
                url=url,
                answers_count=answers_count,
                views=views,
                posted_at=posted_at,
                scraped_at=scraped_at,
            )

        except Exception as e:
            self.logger.warning("質問パースエラー url=%s error=%s", url, e)
            return None

    def _make_dry_run_data(self) -> list[RawQuestion]:
        """dry-run用サンプルデータを返す。"""
        scraped_at = datetime.now(timezone.utc).isoformat()
        return [
            RawQuestion(
                source="chiebukuro",
                category_major="ビジネス、経済とお金",
                category_minor="企業と経営",
                title="請求書の管理が煩雑で困っています",
                body=(
                    "個人事業主として3年ほど活動しています。"
                    "毎月10〜15枚の請求書をExcelで作成しているのですが、"
                    "顧客ごとにフォーマットが異なり、入金確認もバラバラで管理が大変です。"
                    "Freeeを試したのですが、自分のケースに合わず使いこなせませんでした。"
                    "何かよいツールや方法はありますか？"
                ),
                url="https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q999000001",
                answers_count=2,
                views=150,
                posted_at="2026-04-04T22:00:00Z",
                scraped_at=scraped_at,
            ),
            RawQuestion(
                source="chiebukuro",
                category_major="ビジネス、経済とお金",
                category_minor="税金、年金",
                title="確定申告でインボイスの処理が複雑すぎる",
                body=(
                    "フリーランスのエンジニアです。昨年からインボイス制度が始まり、"
                    "仕入れ額控除の計算が非常に複雑になりました。"
                    "経理ソフトを使っていますが、免税事業者からの仕入れの処理方法が分からず、"
                    "毎回税理士に確認しています。もっと簡単に処理できる方法はないでしょうか。"
                ),
                url="https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q999000002",
                answers_count=3,
                views=320,
                posted_at="2026-04-04T20:00:00Z",
                scraped_at=scraped_at,
            ),
            RawQuestion(
                source="chiebukuro",
                category_major="職業とキャリア",
                category_minor="仕事効率化・ノウハウ",
                title="議事録を毎回手動で作るのが辛い",
                body=(
                    "社内会議が週5〜6回あり、そのたびに議事録を手動で作成しています。"
                    "Zoomの文字起こし機能を使っても誤字が多く、結局手直しに30分以上かかります。"
                    "AIを使って自動化している方いますか？おすすめのツールがあれば教えてください。"
                ),
                url="https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q999000003",
                answers_count=5,
                views=480,
                posted_at="2026-04-03T18:00:00Z",
                scraped_at=scraped_at,
            ),
        ]

    def run(
        self,
        date_str: str,
        categories: list[str] | None,
        limit: int,
        dry_run: bool,
    ) -> list[RawQuestion]:
        """全カテゴリをスクレイプしてJSONに保存する。

        Args:
            date_str: 実行日付 (YYYY-MM-DD)
            categories: 絞り込む中カテゴリ名リスト（Noneなら全カテゴリ）
            limit: カテゴリあたりの最大件数
            dry_run: Trueならサンプルデータを返す

        Returns:
            収集したRawQuestionのリスト
        """
        if dry_run:
            self.logger.info("dry-run: サンプルデータを使用")
            results = self._make_dry_run_data()
        else:
            target_cats = CATEGORIES
            if categories:
                target_cats = [c for c in CATEGORIES if c["minor"] in categories or c["major"] in categories]
                self.logger.info("カテゴリ絞り込み: %s", [c["minor"] for c in target_cats])

            results: list[RawQuestion] = []
            for cat in target_cats:
                try:
                    qs = self.scrape_category(cat["major"], cat["minor"], limit)
                    results.extend(qs)
                    self.logger.info(
                        "取得完了: %s > %s  %d件 (累計: %d件)",
                        cat["major"], cat["minor"], len(qs), len(results),
                    )
                except Exception as e:
                    self.logger.error("カテゴリスクレイプエラー: %s > %s  error=%s", cat["major"], cat["minor"], e)

        # JSONに保存
        out_dir = Path(config.DATA_DIR) / "raw"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        data = [q.__dict__ for q in results]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.logger.info("raw保存: %s (%d件)", out_path, len(results))
        return results
