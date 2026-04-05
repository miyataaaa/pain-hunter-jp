"""PainHunter JP v2 — メインエントリーポイント。パイプライン全体を制御する。"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from src.config import config


def setup_logging(date_str: str) -> None:
    """ログ設定を初期化する。"""
    log_dir = Path(config.LOGS_DIR)
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / f"{date_str}.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def parse_args() -> argparse.Namespace:
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(description="PainHunter JP v2 — ペイン探索パイプライン")
    parser.add_argument("--dry-run", action="store_true", help="データ取得・API呼び出しをスキップしてテスト実行")
    parser.add_argument("--categories", nargs="+", metavar="CAT", help="対象カテゴリを絞り込む（例: '企業と経営' '税金、年金'）")
    parser.add_argument("--limit", type=int, default=None, help="カテゴリあたりの最大質問取得数を上書き")
    parser.add_argument("--skip-notify", action="store_true", help="ntfy.sh通知をスキップする")
    return parser.parse_args()


def run_pipeline(
    date_str: str,
    dry_run: bool,
    categories: list[str] | None,
    limit: int | None,
    skip_notify: bool,
) -> None:
    """パイプライン全体を実行する。

    実行順序:
        1. Scraper  → data/raw/{date}.json
        2. Filter   → data/filtered/{date}.json
        3. Extractor → data/extracted/{date}.json
        4. Normalizer → data/normalized/{date}.json
        5. Clusterer → data/clustered/{date}.json
        6. Scorer   → data/scored/{date}.json
        7. Idea Generator → data/ideas/{date}.json
        8. Report + Notify → reports/{date}.md + ntfy.sh
    """
    logger = logging.getLogger(__name__)
    logger.info("=== PainHunter JP v2 開始 date=%s dry_run=%s ===", date_str, dry_run)

    # Step 1: Scraper
    from src.scraper.chiebukuro import ChiebukuroScraper
    scraper = ChiebukuroScraper()
    raw_questions = scraper.run(
        date_str=date_str,
        categories=categories,
        limit=limit or config.MAX_QUESTIONS_PER_CATEGORY,
        dry_run=dry_run,
    )
    logger.info("Step1 Scraper完了: %d件", len(raw_questions))

    # Step 2: Filter
    from src.filter import Filter
    filt = Filter()
    filtered = filt.run(raw_questions, date_str=date_str)
    logger.info("Step2 Filter完了: %d件 → %d件", len(raw_questions), len(filtered))

    # Step 3: Extractor
    from src.extractor import Extractor
    extractor = Extractor()
    extracted = extractor.run(filtered, date_str=date_str, dry_run=dry_run)
    logger.info("Step3 Extractor完了: %d件", len(extracted))

    # Step 4: Normalizer
    from src.normalizer import Normalizer
    normalizer = Normalizer()
    normalized = normalizer.run(extracted, date_str=date_str)
    logger.info("Step4 Normalizer完了: %d件", len(normalized))

    # Step 5: Clusterer
    from src.clusterer import Clusterer
    clusterer = Clusterer()
    clusters = clusterer.run(normalized, date_str=date_str)
    logger.info("Step5 Clusterer完了: %d クラスタ", len(clusters))

    # Step 6: Scorer
    from src.scorer import Scorer
    scorer = Scorer()
    scored_clusters = scorer.run(clusters, normalized, extracted, date_str=date_str)
    logger.info("Step6 Scorer完了")

    # Step 7: Idea Generator
    from src.idea_generator import IdeaGenerator
    idea_gen = IdeaGenerator()
    ideas = idea_gen.run(scored_clusters, date_str=date_str, dry_run=dry_run)
    logger.info("Step7 IdeaGenerator完了: %d アイデア", len(ideas))

    # Step 8: Report + Notify
    from src.report import Report
    reporter = Report()
    report_path = reporter.run(scored_clusters, ideas, date_str=date_str)
    logger.info("Step8 Report生成完了: %s", report_path)

    if not skip_notify:
        from src.notifier import Notifier
        notifier = Notifier()
        notifier.send(scored_clusters, ideas, report_path)
        logger.info("Step8 通知送信完了")
    else:
        logger.info("Step8 通知スキップ")

    logger.info("=== PainHunter JP v2 完了 ===")


def main() -> None:
    """エントリーポイント。"""
    args = parse_args()
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    setup_logging(date_str)

    run_pipeline(
        date_str=date_str,
        dry_run=args.dry_run,
        categories=args.categories,
        limit=args.limit,
        skip_notify=args.skip_notify,
    )


if __name__ == "__main__":
    main()
