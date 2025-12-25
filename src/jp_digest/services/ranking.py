from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
from math import log1p

from sqlalchemy import select

from jp_digest.core.config import AppCfg
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import (
    ContentItem,
    ExperienceCluster,
    ExperienceClusterMention,
    ExperienceMention,
)

W_SUPPORT = 2.2
W_ENGAGEMENT = 1.5
W_RECENCY = 1.2
W_TYPE = 0.8
W_RECOMMEND = 1.0
W_DIVERSITY = 0.6
W_FEEDBACK = 0.0

TYPE_PRIOR = {
    "restaurant": 1.2,
    "cafe": 1.15,
    "bar": 1.05,
    "onsen": 1.15,
    "museum": 0.9,
    "temple": 0.85,
    "shrine": 0.85,
    "hike": 1.0,
    "shop": 1.0,
    "activity": 1.0,
    "hotel": 0.95,
    "landmark": 0.95,
}

DIVERSITY_TYPES = {"temple", "shrine", "museum"}


@dataclass(frozen=True)
class RankedCluster:
    base_name: str
    cluster_id: int
    canonical_name: str
    entity_type: str
    score: float
    reasons: list[str]
    support_count: int
    engagement_sum: float
    recency_score: float
    confidence: float
    rec_avg: float


def _thread_key(ci: ContentItem) -> str:
    if ci.kind == "post":
        return ci.source_id
    if ci.raw_json:
        try:
            data = json.loads(ci.raw_json)
            link_id = data.get("link_id")
            if link_id:
                return str(link_id)
        except json.JSONDecodeError:
            pass
    return ci.source_id


def rank_clusters_for_base(cfg: AppCfg, base_name: str) -> list[RankedCluster]:
    with session_scope() as s:
        clusters = (
            s.execute(
                select(ExperienceCluster).where(
                    ExperienceCluster.base_name == base_name
                )
            )
            .scalars()
            .all()
        )
        if not clusters:
            return []

        cluster_ids = [c.id for c in clusters]
        links = (
            s.execute(
                select(ExperienceClusterMention).where(
                    ExperienceClusterMention.cluster_id.in_(cluster_ids)
                )
            )
            .scalars()
            .all()
        )

        mention_ids = {l.mention_id for l in links}
        mentions = (
            s.execute(
                select(ExperienceMention).where(ExperienceMention.id.in_(mention_ids))
            )
            .scalars()
            .all()
        )
        mention_map = {m.id: m for m in mentions}

        content_item_ids = {m.content_item_id for m in mentions}
        content_items = (
            s.execute(select(ContentItem).where(ContentItem.id.in_(content_item_ids)))
            .scalars()
            .all()
        )
        content_map = {ci.id: ci for ci in content_items}

        mention_ids_by_cluster: dict[int, list[int]] = defaultdict(list)
        for l in links:
            mention_ids_by_cluster[l.cluster_id].append(l.mention_id)

        type_counts: dict[str, int] = defaultdict(int)
        for c in clusters:
            type_counts[c.entity_type] += 1

        results: list[RankedCluster] = []
        for c in clusters:
            authors: set[str] = set()
            threads: set[str] = set()
            sources: set[str] = set()
            rec_scores: list[float] = []

            for mid in mention_ids_by_cluster.get(c.id, []):
                m = mention_map.get(mid)
                if not m:
                    continue
                ci = content_map.get(m.content_item_id)
                if not ci:
                    continue
                sources.add(ci.source_id)
                if ci.author:
                    authors.add(ci.author)
                threads.add(_thread_key(ci))
                rec_scores.append(float(m.recommendation_score or 0.0))

            support_metric = max(len(authors), len(threads), len(sources))
            support_term = log1p(support_metric)
            engagement_term = log1p(max(0.0, float(c.engagement_sum)))
            recency_term = max(0.0, float(c.recency_score))
            type_prior = TYPE_PRIOR.get(c.entity_type, 1.0)
            rec_avg = sum(rec_scores) / len(rec_scores) if rec_scores else 0.0
            rec_term = max(0.0, min(10.0, rec_avg)) / 10.0

            base_score = (
                W_SUPPORT * support_term
                + W_ENGAGEMENT * engagement_term
                + W_RECENCY * recency_term
                + W_TYPE * type_prior
                + W_RECOMMEND * rec_term
                + W_FEEDBACK * 0.0
            )

            penalty = 0.0
            if c.entity_type in DIVERSITY_TYPES and type_counts[c.entity_type] > 2:
                penalty = W_DIVERSITY * (type_counts[c.entity_type] - 2)

            score = base_score - penalty

            reasons = [
                f"support={support_metric}",
                f"engagement={c.engagement_sum:.1f}",
                f"recency={recency_term:.2f}",
                f"type_prior={type_prior:.2f}",
                f"rec_avg={rec_avg:.2f}",
                f"penalty={penalty:.2f}",
            ]

            results.append(
                RankedCluster(
                    base_name=base_name,
                    cluster_id=c.id,
                    canonical_name=c.canonical_name,
                    entity_type=c.entity_type,
                    score=score,
                    reasons=reasons,
                    support_count=int(c.support_count or 0),
                    engagement_sum=float(c.engagement_sum or 0.0),
                    recency_score=float(c.recency_score or 0.0),
                    confidence=float(c.confidence or 0.0),
                    rec_avg=rec_avg,
                )
            )

    results.sort(key=lambda x: x.score, reverse=True)
    return [r for r in results if r.score >= cfg.digest.min_place_score]
