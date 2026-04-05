"""環境変数の読み込みと設定値の一元管理モジュール。"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """アプリケーション設定を一元管理するクラス。"""

    # Anthropic API
    ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
    ANTHROPIC_MODEL: str = "claude-sonnet-4-20250514"

    # 通知
    NTFY_TOPIC: str = os.getenv("NTFY_TOPIC", "")
    NTFY_BASE_URL: str = "https://ntfy.sh"
    SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")

    # スクレイピング
    SCRAPE_INTERVAL_SEC: float = float(os.getenv("SCRAPE_INTERVAL_SEC", "2"))
    MAX_QUESTIONS_PER_CATEGORY: int = int(os.getenv("MAX_QUESTIONS_PER_CATEGORY", "20"))
    MAX_BODY_LENGTH: int = 500  # LLMへ渡す本文の最大文字数

    # フィルタリング
    MIN_BODY_LENGTH: int = 30
    DUPLICATE_THRESHOLD: float = 0.8
    RECENT_URL_DAYS: int = 7

    # スコアリング・クラスタリング
    PAIN_THRESHOLD: int = int(os.getenv("PAIN_THRESHOLD", "3"))
    OPPORTUNITY_THRESHOLD: float = float(os.getenv("OPPORTUNITY_THRESHOLD", "3.8"))
    CLUSTER_SIMILARITY_THRESHOLD: float = float(os.getenv("CLUSTER_SIMILARITY_THRESHOLD", "0.82"))
    LOOKBACK_DAYS: int = int(os.getenv("LOOKBACK_DAYS", "7"))

    # アイデア生成
    TOP_CLUSTERS_FOR_IDEAS: int = 3

    # パス
    DATA_DIR: str = "data"
    REPORTS_DIR: str = "reports"
    LOGS_DIR: str = "logs"

    # User-Agent（スクレイピング）
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


config = Config()
