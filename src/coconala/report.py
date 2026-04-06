"""ココナラ需要分析レポート生成モジュール。

分析済みの出品データをMarkdownレポートに整理し、
data/coconala/reports/{date}.md に保存する。
"""

import logging
from collections import defaultdict
from pathlib import Path

from src.config import config
from src.models import AnalyzedListing

logger = logging.getLogger(__name__)

TOP_N = 10  # レポートに掲載する上位件数


def _demand_label(demand: str) -> str:
    """monthly_demand_estimateを日本語ラベルに変換する。"""
    return {"high": "高", "medium": "中", "low": "低"}.get(demand, demand)


def _stars(rating: float) -> str:
    """評価値を★表示に変換する。"""
    filled = round(rating)
    return "★" * filled + "☆" * (5 - filled)


def generate(analyzed: list[AnalyzedListing], date_str: str) -> str:
    """分析結果からMarkdownレポート文字列を生成する。

    Args:
        analyzed: AnalyzedListingのリスト
        date_str: レポート日付文字列（YYYY-MM-DD_HHMM形式）

    Returns:
        Markdownレポート文字列
    """
    automatable = [a for a in analyzed if a.is_automatable]
    automatable_sorted = sorted(automatable, key=lambda a: a.sales_count, reverse=True)

    # 作業タイプ別集計
    task_type_map: dict[str, list[AnalyzedListing]] = defaultdict(list)
    for a in automatable:
        key = a.task_type or "未分類"
        task_type_map[key].append(a)

    task_type_summary = sorted(
        task_type_map.items(),
        key=lambda kv: len(kv[1]),
        reverse=True,
    )

    lines: list[str] = []

    # ヘッダー
    lines.append(f"# ココナラ需要分析レポート — {date_str}")
    lines.append("")

    # サマリー
    lines.append("## サマリー")
    lines.append("")
    lines.append(f"- 分析出品数: {len(analyzed)}件")
    lines.append(f"- 自動化可能: {len(automatable)}件")

    top_task_types = ", ".join(
        f"{task}（{len(lst)}件）" for task, lst in task_type_summary[:5]
    )
    lines.append(f"- 上位作業タイプ: {top_task_types}")
    lines.append("")

    # TOP10
    lines.append(f"## 自動化可能な出品 TOP{TOP_N}（販売実績順）")
    lines.append("")

    for rank, a in enumerate(automatable_sorted[:TOP_N], start=1):
        lines.append(f"### #{rank} {a.title}")
        lines.append("")
        lines.append(
            f"- **販売実績**: {a.sales_count}件"
            f" / **価格**: ¥{a.price:,}"
            f" / **評価**: {_stars(a.rating)} ({a.rating:.1f})"
        )
        lines.append(f"- **作業タイプ**: {a.task_type}")
        lines.append(f"- **自動化の方法**: {a.automation_summary}")
        lines.append(
            f"- **builder_fit**: {a.builder_fit}/5"
            f" / **難易度**: {a.automation_difficulty}/5"
            f" / **需要**: {_demand_label(a.monthly_demand_estimate)}"
        )
        lines.append(f"- **SaaS化した場合の月額**: ¥{a.saas_price_suggestion:,}")
        lines.append(f"- **URL**: {a.url}")
        lines.append("")

    # 作業タイプ別集計
    lines.append("## 作業タイプ別集計")
    lines.append("")
    lines.append("| 作業タイプ | 出品数 | 平均販売実績 | 平均価格 | SaaS化余地 |")
    lines.append("|---|---|---|---|---|")

    for task_type, lst in task_type_summary:
        avg_sales = int(sum(a.sales_count for a in lst) / len(lst)) if lst else 0
        avg_price = int(sum(a.price for a in lst) / len(lst)) if lst else 0
        avg_saas = int(sum(a.saas_price_suggestion for a in lst) / len(lst)) if lst else 0
        demand_counts: dict[str, int] = defaultdict(int)
        for a in lst:
            demand_counts[a.monthly_demand_estimate] += 1
        top_demand = _demand_label(
            max(demand_counts, key=lambda k: demand_counts[k], default="low")
        )
        lines.append(
            f"| {task_type} | {len(lst)} | {avg_sales}件"
            f" | ¥{avg_price:,} | ¥{avg_saas:,}/月（需要:{top_demand}） |"
        )

    lines.append("")

    # 知恵袋クロス参照（将来実装プレースホルダー）
    lines.append("## 知恵袋クラスタとのクロス参照")
    lines.append("")
    lines.append(
        "> 将来実装：同じ task_type が知恵袋でもクラスタ化されていれば、"
        "事業機会の確度が上がるため表示予定。"
    )
    lines.append("")

    return "\n".join(lines)


def run(
    analyzed: list[AnalyzedListing],
    date_str: str,
    dry_run: bool = False,
) -> str:
    """レポートを生成し、ファイルに保存して内容を返す。

    Args:
        analyzed: AnalyzedListingのリスト
        date_str: ファイル名用の日付文字列（YYYY-MM-DD_HHMM形式）
        dry_run: Trueの場合はファイル保存をスキップ

    Returns:
        生成したMarkdownレポート文字列
    """
    report_text = generate(analyzed, date_str)

    if not dry_run:
        out_dir = Path(config.COCONALA_DATA_DIR) / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.md"
        out_path.write_text(report_text, encoding="utf-8")
        logger.info("レポート保存完了: %s", out_path)

    return report_text
