"""通知モジュール。ntfy.shへのPOSTでレポートサマリーを送信する。"""

import logging
import urllib.parse
from pathlib import Path

import requests

from src.config import config
from src.models import IdeaCandidate, PainCluster


class Notifier:
    """ntfy.shへ通知を送信するクラス。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def _build_summary(self, clusters: list[PainCluster], ideas: list[IdeaCandidate]) -> str:
        """通知に収まる長さのサマリーテキストを生成する（最大4096文字）。"""
        top3 = clusters[:3]
        lines: list[str] = ["🔍 PainHunter JP 日次レポート\n"]

        for i, c in enumerate(top3, 1):
            lines.append(f"#{i} {c.cluster_label} [score:{c.opportunity_score:.2f}]")
            lines.append(f"  → {c.canonical_problem[:60]}")

        if ideas:
            lines.append(f"\n💡 アイデア {len(ideas)}件生成")
            for idea in ideas[:3]:
                lines.append(f"  • {idea.idea_title}: {idea.one_liner}")

        above = [c for c in clusters if c.opportunity_score >= config.OPPORTUNITY_THRESHOLD]
        lines.append(f"\n閾値超えクラスタ: {len(above)}件 / 総クラスタ: {len(clusters)}件")

        return "\n".join(lines)[:4096]

    def send(
        self,
        clusters: list[PainCluster],
        ideas: list[IdeaCandidate],
        report_path: Path,
    ) -> None:
        """ntfy.shへサマリーを送信する。

        Args:
            clusters: スコア済みPainClusterリスト
            ideas: IdeaCandidateリスト
            report_path: 生成されたレポートのPath（通知メッセージに含める）
        """
        if not config.NTFY_TOPIC:
            self.logger.warning("NTFY_TOPICが未設定のため通知をスキップ")
            return

        summary = self._build_summary(clusters, ideas)
        url = f"{config.NTFY_BASE_URL}/{config.NTFY_TOPIC}"

        try:
            resp = requests.post(
                url,
                data=summary.encode("utf-8"),
                headers={
                    "Title": urllib.parse.quote("PainHunter JP 日次レポート"),
                    "Priority": "default",
                    "Tags": "mag,bulb",
                },
                timeout=10,
            )
            resp.raise_for_status()
            self.logger.info("ntfy.sh通知送信完了: %s (status=%d)", url, resp.status_code)
        except requests.RequestException as e:
            self.logger.error("ntfy.sh通知失敗: %s", e)
