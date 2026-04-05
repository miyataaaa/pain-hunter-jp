"""フィルタリングモジュール。スパム・重複・低品質投稿を除去する。"""

import difflib
import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

from src.config import config
from src.models import RawQuestion


# スパム検出用パターン
_SPAM_PROMO_PATTERNS = re.compile(
    r"(副業で稼げる|無料プレゼント|限定募集|LINE.*登録|今すぐクリック|アフィリエイト.*稼ぎ|完全無料で)",
    re.IGNORECASE,
)
_URL_PATTERN = re.compile(r"https?://")

# フィルタ対象の質問パターン（ペインではなく知識質問・比較質問）
_KNOWLEDGE_PATTERNS = re.compile(
    r"(とは何ですか|とはどういう意味|について教えてください|の意味を教えて|って何ですか|どういうものですか)"
)
_COMPARISON_PATTERNS = re.compile(
    r"(どちらが(良い|いい|おすすめ|お勧め)|どっちが(良い|いい)|AとBどちら|と比べて|を比較)"
)
_LOW_CONTENT_PATTERNS = re.compile(
    r"^(おすすめ(を|は)?教えて|いい(方法|ツール|サービス)はありますか|どうすれば(いい|良い)ですか)$"
)


class Filter:
    """スクレイプ済みデータのフィルタリングを行うクラス。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def _is_too_short(self, q: RawQuestion) -> bool:
        """本文が30文字未満なら除外。"""
        return len(q.body.strip()) < config.MIN_BODY_LENGTH

    def _is_spam(self, q: RawQuestion) -> bool:
        """スパムパターンを検出する。

        - URL3つ以上含む
        - 宣伝文言マッチ
        """
        url_count = len(_URL_PATTERN.findall(q.body))
        if url_count >= 3:
            return True
        if _SPAM_PROMO_PATTERNS.search(q.title + " " + q.body):
            return True
        return False

    def _is_knowledge_question(self, q: RawQuestion) -> bool:
        """「〜とは何ですか」型の知識質問を弱フィルタ（タイトルのみ対象）。"""
        return bool(_KNOWLEDGE_PATTERNS.search(q.title))

    def _is_comparison_question(self, q: RawQuestion) -> bool:
        """「どちらが良い」型の比較質問を除外。"""
        return bool(_COMPARISON_PATTERNS.search(q.title + " " + q.body[:100]))

    def _has_low_content(self, q: RawQuestion) -> bool:
        """具体的作業・不満記述が少ない投稿を除外する。

        本文がほぼタイトルと同じ、または汎用フレーズのみの場合。
        """
        body = q.body.strip()
        # 本文がタイトルとほぼ同一
        ratio = difflib.SequenceMatcher(None, q.title, body).ratio()
        if ratio > 0.85 and len(body) < 80:
            return True
        # 汎用質問パターンのみ
        if _LOW_CONTENT_PATTERNS.match(body):
            return True
        return False

    def _load_past_urls(self, today: date) -> set[str]:
        """過去RECENT_URL_DAYS日分のURLセットを読み込む。"""
        urls: set[str] = set()
        raw_dir = Path(config.DATA_DIR) / "raw"
        if not raw_dir.exists():
            return urls

        for i in range(1, config.RECENT_URL_DAYS + 1):
            past_date = today - timedelta(days=i)
            for past_file in sorted(raw_dir.glob(f"{past_date.isoformat()}*.json")):
                try:
                    with open(past_file, encoding="utf-8") as f:
                        past_data = json.load(f)
                    urls.update(item.get("url", "") for item in past_data)
                except Exception as e:
                    self.logger.warning("過去データ読み込みエラー: %s  error=%s", past_file, e)
        return urls

    def _deduplicate(self, questions: list[RawQuestion]) -> list[RawQuestion]:
        """difflib.SequenceMatcherで類似度0.8以上の重複を除去する。

        O(n^2)だが、1回あたり最大100件程度なので許容範囲。
        """
        deduped: list[RawQuestion] = []
        for q in questions:
            is_dup = False
            for existing in deduped:
                ratio = difflib.SequenceMatcher(None, q.body[:200], existing.body[:200]).ratio()
                if ratio >= config.DUPLICATE_THRESHOLD:
                    is_dup = True
                    self.logger.debug("重複除外 (%.2f): %s", ratio, q.url)
                    break
            if not is_dup:
                deduped.append(q)
        return deduped

    def run(self, questions: list[RawQuestion], date_str: str) -> list[RawQuestion]:
        """フィルタリングを実行してJSONに保存する。

        Args:
            questions: スクレイプ済みRawQuestionリスト
            date_str: 実行日付 (YYYY-MM-DD)

        Returns:
            フィルタリング済みRawQuestionリスト
        """
        today = date.fromisoformat(date_str[:10])
        past_urls = self._load_past_urls(today)
        self.logger.info("過去URL除外対象: %d件", len(past_urls))

        filtered: list[RawQuestion] = []
        stats = {
            "too_short": 0,
            "spam": 0,
            "knowledge": 0,
            "comparison": 0,
            "low_content": 0,
            "past_url": 0,
        }

        for q in questions:
            if self._is_too_short(q):
                stats["too_short"] += 1
                continue
            if self._is_spam(q):
                stats["spam"] += 1
                continue
            if q.url in past_urls:
                stats["past_url"] += 1
                continue
            if self._is_knowledge_question(q):
                stats["knowledge"] += 1
                continue
            if self._is_comparison_question(q):
                stats["comparison"] += 1
                continue
            if self._has_low_content(q):
                stats["low_content"] += 1
                continue
            filtered.append(q)

        self.logger.info("フィルタ統計: %s", stats)

        # 重複除去
        before_dedup = len(filtered)
        filtered = self._deduplicate(filtered)
        self.logger.info("重複除去: %d件 → %d件", before_dedup, len(filtered))

        # JSON保存
        out_dir = Path(config.DATA_DIR) / "filtered"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        data = [q.__dict__ for q in filtered]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.logger.info("filtered保存: %s (%d件)", out_path, len(filtered))
        return filtered
