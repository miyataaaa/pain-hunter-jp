"""クラスタリングモジュール。類似ペインをPainClusterにまとめる。"""

import hashlib
import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from src.config import config
from src.models import NormalizedPain, PainCluster


def _cluster_key(pain: NormalizedPain) -> str:
    """クラスタリングキーを生成する（完全一致グルーピング用）。

    v0.1.1: canonical_job 単独をキーにする（root_causeの微妙な違いでクラスタが分裂しないよう）。
    """
    return pain.canonical_job


def _tag_overlap(tags_a: list[str], tags_b: list[str]) -> int:
    """2つのタグリストの一致数を返す。"""
    return len(set(tags_a) & set(tags_b))


def _load_past_normalized(today: date) -> list[NormalizedPain]:
    """過去LOOKBACK_DAYS日分のNormalizedPainを読み込む。"""
    logger = logging.getLogger(__name__)
    results: list[NormalizedPain] = []
    norm_dir = Path(config.DATA_DIR) / "normalized"
    if not norm_dir.exists():
        return results

    for i in range(1, config.LOOKBACK_DAYS + 1):
        past_date = today - timedelta(days=i)
        for past_file in sorted(norm_dir.glob(f"{past_date.isoformat()}*.json")):
            try:
                with open(past_file, encoding="utf-8") as f:
                    data = json.load(f)
                file_date = past_file.stem[:10]
                for item in data:
                    pain = NormalizedPain(**item)
                    if not pain.fetched_date:
                        pain.fetched_date = file_date
                    results.append(pain)
            except Exception as e:
                logger.warning("過去normalizedデータ読み込みエラー: %s  error=%s", past_file, e)
    return results


def _make_cluster_id(key: str) -> str:
    """クラスタIDを生成する。"""
    return "cl_" + hashlib.md5(key.encode()).hexdigest()[:10]


def _make_cluster_label(pains: list[NormalizedPain]) -> str:
    """クラスタのラベル（テーマ名）を生成する。

    v0.1.1: canonical_job のみを使用（10文字以内）。root_causeはラベルに含めない。
    """
    if not pains:
        return "不明なクラスタ"
    return pains[0].canonical_job or "不明なクラスタ"


class Clusterer:
    """NormalizedPainをPainClusterにまとめるクラス。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def _group_by_key(self, pains: list[NormalizedPain]) -> dict[str, list[NormalizedPain]]:
        """Phase 1: canonical_job + canonical_root_cause の完全一致でグルーピングする。"""
        groups: dict[str, list[NormalizedPain]] = defaultdict(list)
        for pain in pains:
            key = _cluster_key(pain)
            groups[key].append(pain)
        return dict(groups)

    def _merge_singleton_by_canonical_problem(
        self, groups: dict[str, list[NormalizedPain]]
    ) -> dict[str, list[NormalizedPain]]:
        """Phase 3: 残りシングルトンを canonical_problem 一致でグルーピングする。

        同じpain_categoryのシングルトン同士をまとめる。
        """
        singletons = {k: v for k, v in groups.items() if len(v) == 1}
        non_singletons = {k: v for k, v in groups.items() if len(v) > 1}

        # canonical_problem でグルーピング
        problem_groups: dict[str, list[str]] = {}
        for s_key, s_pains in singletons.items():
            problem = s_pains[0].canonical_problem
            if problem:
                problem_groups.setdefault(problem, []).append(s_key)

        merged: dict[str, list[NormalizedPain]] = {}
        consumed: set[str] = set()
        for problem, keys in problem_groups.items():
            if len(keys) >= 2:
                # 最初のキーを代表として他を合流
                primary_key = keys[0]
                merged_pains: list[NormalizedPain] = []
                for k in keys:
                    merged_pains.extend(singletons[k])
                    consumed.add(k)
                merged[primary_key] = merged_pains
                self.logger.debug("Phase3合流: problem=%s keys=%s", problem, keys)

        # 合流できなかったシングルトンをそのまま保持
        for k, v in singletons.items():
            if k not in consumed:
                merged[k] = v

        return {**non_singletons, **merged}

    def _merge_singleton_by_tags(
        self, groups: dict[str, list[NormalizedPain]], min_overlap: int = 1
    ) -> dict[str, list[NormalizedPain]]:
        """Phase 2: 件数1のクラスタを近傍（タグ一致数が多い）クラスタへ合流させる試み。

        min_overlap以上のタグが一致する場合のみ合流。
        シングルトン同士の合流は行わない（元々multi=2件以上のグループのみ合流先とする）。
        """
        singletons = {k: v for k, v in groups.items() if len(v) == 1}
        # 元々2件以上あるグループのみ合流先候補とする（スナップショット）
        multi = {k: v for k, v in groups.items() if len(v) > 1}
        unmerged_singletons: dict[str, list[NormalizedPain]] = {}

        for s_key, s_pains in singletons.items():
            best_key = None
            best_overlap = 0
            s_tags = s_pains[0].tags

            for m_key, m_pains in multi.items():
                overlap = _tag_overlap(s_tags, m_pains[0].tags)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_key = m_key

            if best_key and best_overlap >= min_overlap:
                multi[best_key].extend(s_pains)
                self.logger.debug(
                    "シングルトン合流: %s → %s (overlap=%d)", s_key, best_key, best_overlap
                )
            else:
                unmerged_singletons[s_key] = s_pains

        return {**multi, **unmerged_singletons}

    def _build_clusters(self, groups: dict[str, list[NormalizedPain]]) -> list[PainCluster]:
        """グループからPainClusterオブジェクトを生成する。"""
        clusters: list[PainCluster] = []
        for key, pains in groups.items():
            cluster_id = _make_cluster_id(key)
            label = _make_cluster_label(pains)
            rep = pains[0]

            date_count = len({p.fetched_date for p in pains if p.fetched_date}) or 1

            cluster = PainCluster(
                cluster_id=cluster_id,
                cluster_label=label,
                canonical_problem=rep.canonical_problem,
                representative_user=rep.canonical_user,
                representative_job=rep.canonical_job,
                root_cause_summary=rep.canonical_root_cause,
                question_ids=list({p.question_id for p in pains}),
                pain_ids=[p.pain_id for p in pains],
                cluster_size=len(pains),
                date_count=date_count,
                # スコアはScorer段階で計算するため仮値
                avg_severity=0.0,
                avg_urgency=0.0,
                avg_wtp_proxy=0.0,
                avg_builder_fit=0.0,
                recurrence_score=0.0,
                solution_gap_score=0.0,
                productability_score=0.0,
                opportunity_score=0.0,
            )
            clusters.append(cluster)

        # クラスタサイズ降順でソート
        clusters.sort(key=lambda c: c.cluster_size, reverse=True)
        return clusters

    def run(self, normalized: list[NormalizedPain], date_str: str) -> list[PainCluster]:
        """クラスタリングを実行してJSONに保存する。

        Args:
            normalized: NormalizedPainリスト（当日分）
            date_str: 実行日付 (YYYY-MM-DD)

        Returns:
            PainClusterのリスト
        """
        today = date.fromisoformat(date_str[:10])

        # 過去データを読み込んで合流
        past_pains = _load_past_normalized(today)
        self.logger.info("過去データ: %d件", len(past_pains))

        all_pains = normalized + past_pains
        self.logger.info("クラスタリング対象: %d件（当日%d件 + 過去%d件）", len(all_pains), len(normalized), len(past_pains))

        # Phase 1: キー完全一致グルーピング
        groups = self._group_by_key(all_pains)
        self.logger.info("Phase1グループ数: %d", len(groups))

        # Phase 2: シングルトンのタグ近傍合流（しきい値1以上）
        groups = self._merge_singleton_by_tags(groups)
        self.logger.info("Phase2グループ数: %d", len(groups))

        # Phase 3: 残りシングルトンをcanonical_problem一致でグルーピング
        groups = self._merge_singleton_by_canonical_problem(groups)
        self.logger.info("Phase3グループ数: %d", len(groups))

        clusters = self._build_clusters(groups)

        # JSON保存
        out_dir = Path(config.DATA_DIR) / "clustered"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{date_str}.json"

        data = []
        for c in clusters:
            d = c.__dict__.copy()
            data.append(d)

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.logger.info("clustered保存: %s (%dクラスタ)", out_path, len(clusters))
        return clusters
