"""アイデア生成モジュール。上位クラスタからMVPアイデア候補を生成する。"""

import json
import logging
import time
from pathlib import Path

import anthropic

from src.config import config
from src.models import IdeaCandidate, PainCluster


_IDEA_SYSTEM_PROMPT = """あなたはスタートアップのプロダクトマネージャーです。
与えられた「構造的業務ペインのクラスタ」情報をもとに、実際に作れるMVPプロダクトアイデアを複数の切り口で提案してください。

提案する切り口:
1. 自動化型: 繰り返し作業をスクリプト/APIで自動化するツール
2. 情報整理型: 散在する情報を構造化・検索可能にするツール
3. ワークフロー統合型: 既存ツール間を繋いで転記・連携を削減するツール
4. ニッチSaaS型: 特定ユーザー向けに特化した軽量Webアプリ

出力形式は必ずJSON配列で返してください:

[
  {
    "idea_title": "プロダクト名（〇〇Bot, 〇〇Sync等）",
    "one_liner": "1行説明（15〜30文字）",
    "target_user": "具体的なターゲットユーザー",
    "problem_statement": "解決する課題（2〜3文）",
    "solution": "解決策の概要（2〜3文）",
    "mvp_scope": "MVP最小機能（3〜5個の箇条書き）",
    "revenue_model": "収益モデル（例: 月額SaaS, 従量課金）",
    "estimated_price": "想定価格帯（例: 月額3,000〜8,000円）",
    "tech_stack": ["Python", "FastAPI", "Claude API"],
    "mvp_days": MVP開発にかかる日数（整数）,
    "moat": "参入障壁・差別化ポイント",
    "key_risks": ["リスク1", "リスク2"],
    "why_now": "なぜ今作るべきか"
  }
]

注意:
- 技術スタックはPython/LLM/API/クラウドベースで実現可能なものにする
- mvp_daysは7〜30日の範囲で現実的に設定する
- 1クラスタにつき2〜4個のアイデアを出す
"""


class IdeaGenerator:
    """上位PainClusterからIdeaCandidateを生成するクラス。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def _build_cluster_message(self, cluster: PainCluster) -> str:
        """クラスタ情報をLLMへの入力メッセージに変換する。"""
        return (
            f"## クラスタ情報\n"
            f"- ラベル: {cluster.cluster_label}\n"
            f"- 課題: {cluster.canonical_problem}\n"
            f"- ユーザー: {cluster.representative_user}\n"
            f"- ジョブ: {cluster.representative_job}\n"
            f"- 根本原因: {cluster.root_cause_summary}\n"
            f"- クラスタサイズ: {cluster.cluster_size}件\n"
            f"- opportunity_score: {cluster.opportunity_score}\n"
            f"- severity平均: {cluster.avg_severity}\n"
            f"- solution_gap_score: {cluster.solution_gap_score}\n"
            f"- builder_fit平均: {cluster.avg_builder_fit}\n"
        )

    def _call_api_with_retry(self, cluster: PainCluster) -> str | None:
        """APIを最大3回リトライして呼び出す。"""
        user_msg = self._build_cluster_message(cluster)
        for attempt in range(3):
            try:
                response = self.client.messages.create(
                    model=config.ANTHROPIC_MODEL,
                    max_tokens=3000,
                    system=_IDEA_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_msg}],
                )
                return response.content[0].text
            except anthropic.RateLimitError as e:
                wait = 2 ** attempt * 5
                self.logger.warning("レートリミット (attempt %d): %s  %d秒待機", attempt + 1, e, wait)
                time.sleep(wait)
            except anthropic.APIError as e:
                wait = 2 ** attempt * 3
                self.logger.warning("APIエラー (attempt %d): %s  %d秒待機", attempt + 1, e, wait)
                time.sleep(wait)
        return None

    def _parse_ideas(self, response_text: str, cluster_id: str) -> list[IdeaCandidate]:
        """LLMレスポンスをIdeaCandidateリストにパースする。"""
        import re
        try:
            text = response_text.strip()
            if text.startswith("```"):
                text = re.sub(r"^```[a-z]*\n?", "", text)
                text = re.sub(r"\n?```$", "", text)

            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("JSON配列でない")

            ideas: list[IdeaCandidate] = []
            for item in parsed:
                idea = IdeaCandidate(
                    cluster_id=cluster_id,
                    idea_title=str(item.get("idea_title", "")),
                    one_liner=str(item.get("one_liner", "")),
                    target_user=str(item.get("target_user", "")),
                    problem_statement=str(item.get("problem_statement", "")),
                    solution=str(item.get("solution", "")),
                    mvp_scope=str(item.get("mvp_scope", "")),
                    revenue_model=str(item.get("revenue_model", "")),
                    estimated_price=str(item.get("estimated_price", "")),
                    tech_stack=list(item.get("tech_stack", [])),
                    mvp_days=int(item.get("mvp_days", 14)),
                    moat=str(item.get("moat", "")),
                    key_risks=list(item.get("key_risks", [])),
                    why_now=str(item.get("why_now", "")),
                )
                ideas.append(idea)
            return ideas
        except Exception as e:
            self.logger.warning("アイデアパースエラー cluster_id=%s  error=%s", cluster_id, e)
            return []

    def _make_dry_run_ideas(self, cluster: PainCluster) -> list[IdeaCandidate]:
        """dry-run用サンプルアイデア。"""
        return [
            IdeaCandidate(
                cluster_id=cluster.cluster_id,
                idea_title=f"[dry-run] {cluster.representative_job}Bot",
                one_liner=f"{cluster.representative_job}を自動化するツール",
                target_user=cluster.representative_user,
                problem_statement=cluster.canonical_problem,
                solution="LLM APIと連携して自動処理を実現",
                mvp_scope="基本機能のみ",
                revenue_model="月額SaaS",
                estimated_price="月額3,000円",
                tech_stack=["Python", "FastAPI", "Claude API"],
                mvp_days=14,
                moat="ドメイン特化による精度",
                key_risks=["既存SaaS競合", "法規制変更"],
                why_now="LLM APIが安価になった今が好機",
            )
        ]

    def run(
        self, clusters: list[PainCluster], date_str: str, dry_run: bool = False
    ) -> list[IdeaCandidate]:
        """opportunity_score上位クラスタからアイデアを生成してJSONに保存する。

        Args:
            clusters: スコア済みPainClusterリスト（降順ソート済み前提）
            date_str: 実行日付 (YYYY-MM-DD)
            dry_run: Trueならダミーアイデアを返す

        Returns:
            IdeaCandidateのリスト
        """
        top_clusters = clusters[:config.TOP_CLUSTERS_FOR_IDEAS]
        self.logger.info("アイデア生成対象: %d クラスタ", len(top_clusters))

        all_ideas: list[IdeaCandidate] = []

        for cluster in top_clusters:
            try:
                if dry_run:
                    ideas = self._make_dry_run_ideas(cluster)
                else:
                    response_text = self._call_api_with_retry(cluster)
                    if response_text is None:
                        self.logger.warning("アイデア生成スキップ: cluster_id=%s", cluster.cluster_id)
                        continue
                    ideas = self._parse_ideas(response_text, cluster.cluster_id)

                all_ideas.extend(ideas)
                self.logger.info("クラスタ %s: %d アイデア生成", cluster.cluster_id, len(ideas))
            except Exception as e:
                self.logger.error("アイデア生成エラー cluster_id=%s  error=%s", cluster.cluster_id, e)

        # JSON保存
        out_dir = Path(config.DATA_DIR) / "ideas"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        data = [i.__dict__ for i in all_ideas]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.logger.info("ideas保存: %s (%d件)", out_path, len(all_ideas))
        return all_ideas
