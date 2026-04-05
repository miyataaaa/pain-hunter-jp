"""レポート生成モジュール。日次Markdownレポートを生成する。"""

import logging
from pathlib import Path

from src.config import config
from src.models import IdeaCandidate, PainCluster


class Report:
    """日次Markdownレポートを生成するクラス。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def _format_cluster(self, cluster: PainCluster, rank: int) -> str:
        """クラスタ情報をMarkdown形式で整形する。"""
        return (
            f"### #{rank} {cluster.cluster_label}\n"
            f"- **opportunity_score**: {cluster.opportunity_score:.3f}\n"
            f"- **課題**: {cluster.canonical_problem}\n"
            f"- **ユーザー**: {cluster.representative_user}  "
            f"**ジョブ**: {cluster.representative_job}\n"
            f"- **根本原因**: {cluster.root_cause_summary}\n"
            f"- **クラスタサイズ**: {cluster.cluster_size}件\n"
            f"- severity: {cluster.avg_severity:.1f} / "
            f"urgency: {cluster.avg_urgency:.1f} / "
            f"wtp: {cluster.avg_wtp_proxy:.1f} / "
            f"builder_fit: {cluster.avg_builder_fit:.1f}\n"
            f"- solution_gap: {cluster.solution_gap_score:.2f} / "
            f"recurrence: {cluster.recurrence_score:.2f} / "
            f"productability: {cluster.productability_score:.2f}\n"
        )

    def _format_idea(self, idea: IdeaCandidate, index: int) -> str:
        """アイデアをMarkdown形式で整形する。"""
        tech = ", ".join(idea.tech_stack)
        risks = "\n".join(f"  - {r}" for r in idea.key_risks)
        return (
            f"#### 💡 {index}. {idea.idea_title}\n"
            f"**{idea.one_liner}**\n\n"
            f"- **対象ユーザー**: {idea.target_user}\n"
            f"- **課題**: {idea.problem_statement}\n"
            f"- **解決策**: {idea.solution}\n"
            f"- **MVP範囲**: {idea.mvp_scope}\n"
            f"- **収益モデル**: {idea.revenue_model} / {idea.estimated_price}\n"
            f"- **技術**: {tech}\n"
            f"- **MVP日数**: {idea.mvp_days}日\n"
            f"- **参入障壁**: {idea.moat}\n"
            f"- **リスク**:\n{risks}\n"
            f"- **なぜ今**: {idea.why_now}\n"
        )

    def run(
        self,
        clusters: list[PainCluster],
        ideas: list[IdeaCandidate],
        date_str: str,
    ) -> Path:
        """日次Markdownレポートを生成する。

        Args:
            clusters: スコア済みPainClusterリスト（降順ソート済み）
            ideas: IdeaCandidateリスト
            date_str: 実行日付 (YYYY-MM-DD)

        Returns:
            レポートファイルのPath
        """
        # クラスタをcluster_idで引ける辞書
        idea_by_cluster: dict[str, list[IdeaCandidate]] = {}
        for idea in ideas:
            idea_by_cluster.setdefault(idea.cluster_id, []).append(idea)

        lines: list[str] = [
            f"# PainHunter JP — 日次レポート {date_str}",
            "",
            "## サマリー",
            f"- 分析クラスタ数: {len(clusters)}",
            f"- 生成アイデア数: {len(ideas)}",
            f"- OPPORTUNITYしきい値: {config.OPPORTUNITY_THRESHOLD}",
            "",
        ]

        # opportunity_scoreがしきい値超えのクラスタ
        above_threshold = [c for c in clusters if c.opportunity_score >= config.OPPORTUNITY_THRESHOLD]
        lines += [
            f"## 注目クラスタ（score >= {config.OPPORTUNITY_THRESHOLD}） — {len(above_threshold)}件",
            "",
        ]

        top_clusters = clusters[:config.TOP_CLUSTERS_FOR_IDEAS]

        # TOP3クラスタとアイデア
        lines.append("## TOP3 クラスタ詳細 + アイデア")
        lines.append("")

        for i, cluster in enumerate(top_clusters, 1):
            lines.append(self._format_cluster(cluster, i))
            cluster_ideas = idea_by_cluster.get(cluster.cluster_id, [])
            if cluster_ideas:
                lines.append("**生成アイデア**\n")
                for j, idea in enumerate(cluster_ideas, 1):
                    lines.append(self._format_idea(idea, j))
            lines.append("")

        # 全クラスタ一覧（スコア順）
        lines.append("## 全クラスタ一覧（score順）")
        lines.append("")
        lines.append("| # | ラベル | score | size | severity | solution_gap |")
        lines.append("|---|--------|-------|------|----------|--------------|")
        for i, c in enumerate(clusters, 1):
            lines.append(
                f"| {i} | {c.cluster_label} | {c.opportunity_score:.3f} | "
                f"{c.cluster_size} | {c.avg_severity:.1f} | {c.solution_gap_score:.2f} |"
            )

        report_content = "\n".join(lines) + "\n"

        out_dir = Path(config.REPORTS_DIR)
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"{date_str}.md"
        out_path.write_text(report_content, encoding="utf-8")

        self.logger.info("レポート生成: %s", out_path)
        return out_path
