"""ココナラ需要分析パイプライン エントリポイント。

実行例:
    python -m src.coconala.main
    python -m src.coconala.main --dry-run
    python -m src.coconala.main --categories "IT・プログラミング・開発" "ライティング・翻訳"
    python -m src.coconala.main --limit 10 --skip-notify
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.coconala import analyzer as analyzer_mod
from src.coconala import report as report_mod
from src.coconala.analyzer import Analyzer
from src.coconala.scraper import CATEGORIES, CoconalaScraper
from src.config import config
from src.models import AnalyzedListing, CoconalaListing

# ------------------------------------------------------------------ #
# ログ設定
# ------------------------------------------------------------------ #

def _setup_logging(date_str: str) -> None:
    """ログをコンソールとファイルに出力する。"""
    log_dir = Path(config.LOGS_DIR)
    log_dir.mkdir(exist_ok=True)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    log_file = log_dir / f"coconala_{date_str}.log"
    handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


# ------------------------------------------------------------------ #
# パイプライン
# ------------------------------------------------------------------ #

def run_pipeline(
    categories: list[dict] | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    skip_notify: bool = False,
) -> None:
    """ココナラ需要分析パイプラインを実行する。

    Args:
        categories: 対象カテゴリリスト。Noneの場合は全カテゴリ
        limit: 1カテゴリあたりの取得上限件数
        dry_run: Trueの場合はファイル保存・通知をスキップ
        skip_notify: Trueの場合は通知をスキップ
    """
    logger = logging.getLogger(__name__)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")

    logger.info("===== ココナラ需要分析 開始 =====")
    logger.info("date_str=%s  dry_run=%s  skip_notify=%s", date_str, dry_run, skip_notify)

    # Step 1: スクレイプ
    logger.info("----- Step1: Scraper -----")
    scraper = CoconalaScraper()
    listings: list[CoconalaListing] = scraper.run(
        categories=categories,
        max_listings=limit,
        dry_run=dry_run,
    )

    if not listings:
        logger.warning("出品データが0件。パイプラインを終了します。")
        return

    # Step 2: 分析
    logger.info("----- Step2: Analyzer -----")
    analyzer = Analyzer()
    analyzed: list[AnalyzedListing] = analyzer.run(
        listings=listings,
        date_str=date_str,
        dry_run=dry_run,
    )

    # Step 3: レポート
    logger.info("----- Step3: Report -----")
    report_text = report_mod.run(
        analyzed=analyzed,
        date_str=date_str,
        dry_run=dry_run,
    )

    # 通知
    if not skip_notify and not dry_run:
        _notify(report_text, analyzed, date_str)

    logger.info("===== ココナラ需要分析 完了 =====")


def _notify(report_text: str, analyzed: list[AnalyzedListing], date_str: str) -> None:
    """ntfy.shへ分析結果のサマリーを通知する。"""
    logger = logging.getLogger(__name__)
    if not config.NTFY_TOPIC:
        logger.info("NTFY_TOPIC未設定のため通知スキップ")
        return

    automatable = [a for a in analyzed if a.is_automatable]
    top3 = sorted(automatable, key=lambda a: a.sales_count, reverse=True)[:3]

    body_lines = [
        f"ココナラ需要分析 {date_str}",
        f"分析{len(analyzed)}件 / 自動化可能{len(automatable)}件",
        "",
    ]
    for i, a in enumerate(top3, 1):
        body_lines.append(f"#{i} {a.title[:20]}（{a.sales_count}件, {a.task_type}）")

    body = "\n".join(body_lines)

    try:
        import requests

        resp = requests.post(
            f"{config.NTFY_BASE_URL}/{config.NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={
                "Title": f"ココナラ分析完了 — 自動化候補{len(automatable)}件",
                "Content-Type": "text/plain; charset=utf-8",
            },
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("ntfy.sh通知送信完了")
    except Exception as e:
        logger.warning("ntfy.sh通知失敗: %s", e)


# ------------------------------------------------------------------ #
# CLI
# ------------------------------------------------------------------ #

def _parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(
        description="ココナラ需要分析パイプライン",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ファイル保存・通知をスキップして動作確認する",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        metavar="CATEGORY",
        help='対象カテゴリの major 名を指定（例: "IT・プログラミング・開発"）',
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="1カテゴリあたりの取得上限件数",
    )
    parser.add_argument(
        "--skip-notify",
        action="store_true",
        help="ntfy.shへの通知をスキップする",
    )
    return parser.parse_args()


def main() -> None:
    """メインエントリポイント。"""
    args = _parse_args()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M")
    _setup_logging(date_str)

    # カテゴリフィルタ
    target_categories: list[dict] | None = None
    if args.categories:
        target_categories = [
            cat for cat in CATEGORIES
            if cat["major"] in args.categories or cat["minor"] in args.categories
        ]
        if not target_categories:
            logging.getLogger(__name__).warning(
                "指定カテゴリが見つかりません: %s  全カテゴリで実行します", args.categories
            )

    run_pipeline(
        categories=target_categories,
        limit=args.limit,
        dry_run=args.dry_run,
        skip_notify=args.skip_notify,
    )


if __name__ == "__main__":
    main()
