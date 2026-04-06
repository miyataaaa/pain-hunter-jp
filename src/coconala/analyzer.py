"""ココナラ出品自動化可能性分析モジュール。

Claude APIを使って各出品が「Python/LLM/APIで自動化できるか」を判定し、
AnalyzedListingとして保存する。
"""

import json
import logging
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from src.config import config
from src.models import AnalyzedListing, CoconalaListing

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
MAX_RETRIES = 3

_SYSTEM_PROMPT = """\
あなたは業務自動化の専門家です。
ココナラの出品（人が手作業で提供しているサービス）を読み、
「Python / LLM / API を使って自動化できるか」を判定してください。

【判定基準 — is_automatable の true/false】

is_automatable: true にする条件:
- データ入力・転記・変換作業（Excel、CSV、PDF→データ化など）
- 文書作成・テンプレート埋め（契約書、請求書、メール文面など）
- リサーチ・情報収集・まとめ作業
- 翻訳・校正・リライト
- 画像の簡単な加工（リサイズ、背景除去、フォーマット変換）
- データ分析・レポート作成
- SNS投稿の作成・スケジューリング

is_automatable: false にする条件:
- 高度なデザイン・イラスト制作（人のクリエイティビティが必要）
- 対面コンサルティング・カウンセリング
- 写真撮影・動画撮影（物理的作業）
- 法律・税務・医療の専門的助言
- ナレーション・声優（声の個性が価値）

【フィールド制約】

■ task_type: **10文字以内**の作業名。
  良い例: データ入力、文書作成、翻訳、リサーチ、画像加工、SNS運用
  悪い例: Excelデータの入力と整理と分析（長すぎる）

■ automation_difficulty: 1〜5の整数
  1=既存ライブラリで即実装可 3=API連携やプロンプト設計が必要 5=ML/専門知識が必要

■ builder_fit: 1〜5の整数
  1=専門知識が必要 3=汎用スキルで可能 5=Python/LLM/APIで十分

■ monthly_demand_estimate: high / medium / low
  販売実績と価格から推定。sales_count > 100かつprice >= 3000 なら high。

■ saas_price_suggestion: 月額SaaS化した場合の推定価格（円）
  出品価格の1/3〜1/5が目安。最低500円、最高10000円。

出力は必ずJSON配列で返す。各要素のスキーマ:

[
  {
    "listing_id": "<listing_id>",
    "is_automatable": true or false,
    "automation_summary": "どう自動化できるか（1〜2文）",
    "task_type": "10文字以内の作業名",
    "automation_difficulty": 1〜5,
    "builder_fit": 1〜5,
    "monthly_demand_estimate": "high / medium / low",
    "saas_price_suggestion": 月額円（整数）
  }
]

is_automatable=false の場合、automation_summary以外は空文字列・0でよい。
"""

_VALID_DEMAND = {"high", "medium", "low"}


def _parse_analyzed(
    response_text: str,
    listings: list[CoconalaListing],
) -> list[AnalyzedListing]:
    """LLMレスポンスのJSONをパースしてAnalyzedListingリストに変換する。

    JSONパース失敗時はis_automatable=Falseのフォールバックを返す。
    """
    listing_map = {l.listing_id: l for l in listings}
    results: list[AnalyzedListing] = []

    try:
        text = response_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-z]*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError("レスポンスがJSON配列でない")

    except Exception as e:
        logger.warning("LLMレスポンスのJSONパース失敗: %s  fallbackを使用", e)
        return _fallback_analyzed(listings)

    for item in parsed:
        try:
            lid = str(item.get("listing_id", ""))
            src = listing_map.get(lid)
            if src is None:
                logger.debug("listing_id不一致: %s  スキップ", lid)
                continue

            is_auto = bool(item.get("is_automatable", False))
            summary = str(item.get("automation_summary", ""))[:200]

            task_type = str(item.get("task_type", ""))
            if len(task_type) > 10:
                task_type = task_type[:10]

            difficulty = max(1, min(5, int(item.get("automation_difficulty", 3))))
            builder_fit = max(1, min(5, int(item.get("builder_fit", 3))))

            demand = str(item.get("monthly_demand_estimate", "low"))
            if demand not in _VALID_DEMAND:
                demand = "low"

            saas_price = max(500, min(10000, int(item.get("saas_price_suggestion", 500))))

            results.append(
                AnalyzedListing(
                    listing_id=src.listing_id,
                    title=src.title,
                    category_major=src.category_major,
                    category_minor=src.category_minor,
                    price=src.price,
                    sales_count=src.sales_count,
                    review_count=src.review_count,
                    rating=src.rating,
                    url=src.url,
                    is_automatable=is_auto,
                    automation_summary=summary,
                    task_type=task_type,
                    automation_difficulty=difficulty,
                    builder_fit=builder_fit,
                    monthly_demand_estimate=demand,
                    saas_price_suggestion=saas_price,
                )
            )
        except Exception as e:
            logger.debug("アイテム変換スキップ: %s  error=%s", item.get("listing_id"), e)

    # LLMが一部IDを返さなかった場合のフォールバック補完
    found_ids = {a.listing_id for a in results}
    for lst in listings:
        if lst.listing_id not in found_ids:
            results.append(_make_fallback(lst))

    return results


def _make_fallback(lst: CoconalaListing) -> AnalyzedListing:
    """フォールバック用のAnalyzedListing（is_automatable=False）を生成する。"""
    return AnalyzedListing(
        listing_id=lst.listing_id,
        title=lst.title,
        category_major=lst.category_major,
        category_minor=lst.category_minor,
        price=lst.price,
        sales_count=lst.sales_count,
        review_count=lst.review_count,
        rating=lst.rating,
        url=lst.url,
        is_automatable=False,
        automation_summary="",
        task_type="",
        automation_difficulty=0,
        builder_fit=0,
        monthly_demand_estimate="low",
        saas_price_suggestion=0,
    )


def _fallback_analyzed(listings: list[CoconalaListing]) -> list[AnalyzedListing]:
    """全件フォールバック。"""
    return [_make_fallback(l) for l in listings]


class Analyzer:
    """Claude APIでコナラ出品の自動化可能性を分析するクラス。"""

    def __init__(self) -> None:
        """Anthropicクライアントを初期化する。"""
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        self.logger = logging.getLogger(__name__)

    def _build_user_message(self, listings: list[CoconalaListing]) -> str:
        """バッチ用ユーザーメッセージを構築する。"""
        items = []
        for lst in listings:
            items.append(
                f"listing_id: {lst.listing_id}\n"
                f"タイトル: {lst.title}\n"
                f"説明: {lst.description[:300]}\n"
                f"カテゴリ: {lst.category_major} / {lst.category_minor}\n"
                f"価格: {lst.price}円\n"
                f"販売実績: {lst.sales_count}件\n"
                f"レビュー数: {lst.review_count}\n"
                f"評価: {lst.rating}"
            )
        return "以下の出品を分析してください。\n\n" + "\n\n---\n\n".join(items)

    def _call_api(self, user_message: str, attempt: int = 0) -> str:
        """Claude APIを呼び出し、レスポンステキストを返す。

        失敗時はexponential backoffで最大MAX_RETRIESまでリトライする。
        """
        try:
            response = self.client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        except anthropic.RateLimitError as e:
            if attempt >= MAX_RETRIES:
                raise
            wait = 2 ** (attempt + 1)
            self.logger.warning("RateLimit: %d秒後にリトライ（attempt=%d）", wait, attempt + 1)
            time.sleep(wait)
            return self._call_api(user_message, attempt + 1)
        except anthropic.APIError as e:
            if attempt >= MAX_RETRIES:
                raise
            wait = 2 ** (attempt + 1)
            self.logger.warning("APIエラー: %s  %d秒後にリトライ（attempt=%d）", e, wait, attempt + 1)
            time.sleep(wait)
            return self._call_api(user_message, attempt + 1)

    def analyze_batch(self, listings: list[CoconalaListing]) -> list[AnalyzedListing]:
        """1バッチ（最大BATCH_SIZE件）を分析して返す。"""
        user_message = self._build_user_message(listings)
        try:
            response_text = self._call_api(user_message)
            return _parse_analyzed(response_text, listings)
        except Exception as e:
            self.logger.error("バッチ分析失敗: %s  fallbackを使用", e)
            return _fallback_analyzed(listings)

    def run(
        self,
        listings: list[CoconalaListing],
        date_str: str,
        dry_run: bool = False,
    ) -> list[AnalyzedListing]:
        """全出品をバッチ分析して保存する。

        Args:
            listings: 分析対象のCoconalaListingリスト
            date_str: ファイル名用の日付文字列（YYYY-MM-DD_HHMM形式）
            dry_run: Trueの場合はファイル保存をスキップ

        Returns:
            AnalyzedListingのリスト
        """
        self.logger.info("分析開始: %d件 / バッチサイズ=%d", len(listings), BATCH_SIZE)
        all_analyzed: list[AnalyzedListing] = []

        for i in range(0, len(listings), BATCH_SIZE):
            batch = listings[i: i + BATCH_SIZE]
            self.logger.info(
                "バッチ %d/%d  (%d〜%d件目)",
                i // BATCH_SIZE + 1,
                (len(listings) + BATCH_SIZE - 1) // BATCH_SIZE,
                i + 1,
                min(i + BATCH_SIZE, len(listings)),
            )
            analyzed = self.analyze_batch(batch)
            all_analyzed.extend(analyzed)

            if i + BATCH_SIZE < len(listings):
                time.sleep(1)

        self.logger.info(
            "分析完了: 合計%d件（自動化可能=%d件）",
            len(all_analyzed),
            sum(1 for a in all_analyzed if a.is_automatable),
        )

        if not dry_run:
            self._save(all_analyzed, date_str)

        return all_analyzed

    def _save(self, analyzed: list[AnalyzedListing], date_str: str) -> Path:
        """data/coconala/analyzed/{date}.json に保存して保存先パスを返す。"""
        out_dir = Path(config.COCONALA_DATA_DIR) / "analyzed"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                [asdict(a) for a in analyzed],
                f,
                ensure_ascii=False,
                indent=2,
            )

        self.logger.info("analyzed保存完了: %s  %d件", out_path, len(analyzed))
        return out_path
