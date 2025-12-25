from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import re
from typing import Iterable

from rapidfuzz import fuzz
from sqlalchemy import delete, select

from jp_digest.core.config import AppCfg, BaseCfg
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import (
    ContentItem,
    ExperienceCluster,
    ExperienceClusterMention,
    ExperienceMention,
)

ASSIGNED_BASE_THRESHOLD = 0.65
FUZZY_STRONG = 92
FUZZY_WEAK = 85
ENGAGEMENT_CAP = 500
RECENCY_TAU_DAYS = 30.0
SANITY_MISMATCH_REJECT_CONF = 0.8

STOP_WORDS = {
    "cafe",
    "coffee",
    "restaurant",
    "bar",
    "shop",
    "store",
    "izakaya",
    "ramen",
    "sushi",
    "grill",
    "steak",
    "teahouse",
    "teahouse",
    "bakery",
    "bistro",
    "pub",
    "diner",
    "hotel",
    "inn",
    "ryokan",
    "museum",
    "gallery",
    "temple",
    "shrine",
    "park",
}

TYPE_GROUPS = [
    {
        "restaurant",
        "cafe",
        "bar",
        "coffee",
        "bakery",
        "bistro",
        "izakaya",
        "ramen",
        "sushi",
        "yakitori",
        "dessert",
    },
    {"museum", "gallery", "temple", "shrine", "landmark"},
    {"shop", "market", "store"},
]

BASE_CENTROIDS = {
    "Kyoto": (35.0116, 135.7681),
    "Takamatsu": (34.3428, 134.0466),
    "Iya Valley": (33.9057, 133.8281),
    "Matsuyama": (33.8394, 132.7657),
    "Tokyo": (35.6764, 139.65),
}


@dataclass
class ClusterBuilder:
    base_name: str
    entity_type: str
    normalized_key: str
    name_counts: dict[str, int] = field(default_factory=dict)
    mention_ids: list[int] = field(default_factory=list)
    location_tokens: set[str] = field(default_factory=set)
    confidence_sum: float = 0.0
    confidence_count: int = 0

    @property
    def canonical_name(self) -> str:
        if not self.name_counts:
            return ""
        return max(self.name_counts.items(), key=lambda x: (x[1], len(x[0])))[0]

    def add_mention(self, mention: ExperienceMention, confidence: float) -> None:
        name = mention.entity_name.strip()
        if name:
            self.name_counts[name] = self.name_counts.get(name, 0) + 1
        self.mention_ids.append(mention.id)
        self.location_tokens.update(_location_tokens(mention.location_hint))
        self.confidence_sum += confidence
        self.confidence_count += 1


def _normalize_entity_name(name: str) -> str:
    text = name.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [t for t in text.split() if t and t not in STOP_WORDS]
    return " ".join(tokens).strip()


def _location_tokens(text: str) -> set[str]:
    text = text.lower().strip()
    if not text:
        return set()
    parts = re.split(r"[\s,;/()\-]+", text)
    tokens = {p for p in parts if p and len(p) >= 3}
    tokens.add(text)
    return tokens


def _build_base_tokens(bases: list[BaseCfg]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for b in bases:
        tokens = {b.name.lower()}
        tokens.update(a.lower() for a in b.aliases)
        out[b.name] = {t for t in tokens if t}
    return out


def _types_compatible(a: str, b: str) -> bool:
    if a == b:
        return True
    for group in TYPE_GROUPS:
        if a in group and b in group:
            return True
    return False


def _strong_base_match(text: str, tokens: Iterable[str]) -> bool:
    haystack = text.lower()
    return any(t for t in tokens if t and t in haystack)


def _sanity_mismatch(
    location_hint: str, assigned_base: str, base_tokens: dict[str, set[str]]
) -> str | None:
    hint = location_hint.lower()
    for base, tokens in base_tokens.items():
        if base == assigned_base:
            continue
        if base not in BASE_CENTROIDS:
            continue
        if any(t for t in tokens if t and t in hint):
            return base
    return None


def _recency_weight(created_utc: int) -> float:
    if not created_utc:
        return 0.0
    created = datetime.fromtimestamp(created_utc, tz=timezone.utc)
    age_days = (datetime.now(tz=timezone.utc) - created).total_seconds() / 86400.0
    return math.exp(-age_days / RECENCY_TAU_DAYS)


def _cluster_for_mention(
    mention: ExperienceMention,
    builder: ClusterBuilder,
) -> bool:
    name = mention.entity_name.strip()
    if not name:
        return False

    if not _types_compatible(mention.entity_type, builder.entity_type):
        return False

    similarity = fuzz.token_set_ratio(name, builder.canonical_name)
    if similarity >= FUZZY_STRONG:
        return True

    if similarity >= FUZZY_WEAK:
        hint_tokens = _location_tokens(mention.location_hint)
        if hint_tokens & builder.location_tokens:
            return True

    return False


def ground_experiences(cfg: AppCfg, limit_mentions: int = 400) -> int:
    """
    Base assignment gate + entity resolution clustering.
    """
    base_names = [b.name for b in cfg.trip.bases]
    base_tokens = _build_base_tokens(cfg.trip.bases)

    created_clusters = 0
    total_mentions = 0
    accepted_mentions = 0
    skipped_unknown = 0
    skipped_low_conf = 0
    skipped_sanity = 0

    with session_scope() as s:
        mentions = (
            s.execute(
                select(ExperienceMention)
                .order_by(ExperienceMention.id.desc())
                .limit(limit_mentions)
            )
            .scalars()
            .all()
        )

        total_mentions = len(mentions)
        print(f"  Processing {total_mentions} mentions...")

        # Reset clusters each run to avoid stale data
        s.execute(delete(ExperienceClusterMention))
        s.execute(delete(ExperienceCluster))

        clusters_by_base: dict[str, list[ClusterBuilder]] = {
            base: [] for base in base_names
        }

        for idx, m in enumerate(mentions, 1):
            assigned_base = m.assigned_base
            if not assigned_base or assigned_base == "Unknown":
                skipped_unknown += 1
                continue
            if assigned_base not in base_names:
                skipped_unknown += 1
                continue

            confidence_gate = m.assigned_base_confidence >= ASSIGNED_BASE_THRESHOLD

            mention_text = " ".join(
                [
                    m.entity_name,
                    m.experience_text,
                    m.location_hint,
                    m.canonicalization_hint or "",
                ]
            )
            strong_token = _strong_base_match(
                mention_text, base_tokens.get(assigned_base, set())
            )

            if not (confidence_gate or strong_token):
                skipped_low_conf += 1
                continue

            mismatch = _sanity_mismatch(
                m.location_hint, assigned_base, base_tokens
            )
            if mismatch and m.assigned_base_confidence < SANITY_MISMATCH_REJECT_CONF:
                skipped_sanity += 1
                continue

            norm_key = _normalize_entity_name(m.entity_name)
            if not norm_key:
                norm_key = m.entity_name.lower().strip()

            mention_conf = (m.assigned_base_confidence + m.location_confidence) / 2.0
            if mismatch:
                mention_conf *= 0.7
            rec_score = float(getattr(m, "recommendation_score", 0.0) or 0.0)
            rec_norm = max(0.0, min(10.0, rec_score)) / 10.0
            mention_conf = (mention_conf * 0.7) + (rec_norm * 0.3)

            merged = False
            for builder in clusters_by_base[assigned_base]:
                if builder.normalized_key == norm_key and _types_compatible(
                    m.entity_type, builder.entity_type
                ):
                    builder.add_mention(m, mention_conf)
                    merged = True
                    break

            if not merged:
                for builder in clusters_by_base[assigned_base]:
                    if _cluster_for_mention(m, builder):
                        builder.add_mention(m, mention_conf)
                        merged = True
                        break

            if not merged:
                builder = ClusterBuilder(
                    base_name=assigned_base,
                    entity_type=m.entity_type,
                    normalized_key=norm_key,
                )
                builder.add_mention(m, mention_conf)
                clusters_by_base[assigned_base].append(builder)

            accepted_mentions += 1

            if idx % 50 == 0 or idx == 1:
                print(f"  [{idx}/{total_mentions}] Clustered mentions...")

        # Preload content items for metrics
        mention_map = {m.id: m for m in mentions}
        content_item_ids = {m.content_item_id for m in mentions}
        content_items = (
            s.execute(select(ContentItem).where(ContentItem.id.in_(content_item_ids)))
            .scalars()
            .all()
        )
        content_map = {ci.id: ci for ci in content_items}

        for base_name, builders in clusters_by_base.items():
            for builder in builders:
                if not builder.mention_ids:
                    continue

                authors: set[str] = set()
                source_ids: set[str] = set()
                engagement_sum = 0.0
                recency_scores: list[float] = []

                for mid in builder.mention_ids:
                    mention = mention_map.get(mid)
                    if not mention:
                        continue
                    ci = content_map.get(mention.content_item_id)
                    if not ci:
                        continue

                    source_ids.add(ci.source_id)
                    if ci.author:
                        authors.add(ci.author)

                    score = max(0, int(ci.score))
                    engagement_sum += min(score, ENGAGEMENT_CAP)
                    recency_scores.append(_recency_weight(ci.created_utc))

                support_count = len(authors) if authors else len(source_ids)
                recency_score = (
                    sum(recency_scores) / len(recency_scores)
                    if recency_scores
                    else 0.0
                )
                confidence = (
                    builder.confidence_sum / max(1, builder.confidence_count)
                )
                confidence = max(0.0, min(1.0, confidence))

                cluster = ExperienceCluster(
                    base_name=base_name,
                    canonical_name=builder.canonical_name or builder.normalized_key,
                    entity_type=builder.entity_type,
                    normalized_key=builder.normalized_key,
                    support_count=support_count,
                    engagement_sum=engagement_sum,
                    recency_score=recency_score,
                    confidence=confidence,
                )
                s.add(cluster)
                s.flush()

                for mid in builder.mention_ids:
                    s.add(
                        ExperienceClusterMention(
                            cluster_id=cluster.id,
                            mention_id=mid,
                        )
                    )

                created_clusters += 1

    print("\n  Clustering Summary:")
    print(f"    Accepted mentions: {accepted_mentions}")
    print(f"    Skipped Unknown base: {skipped_unknown}")
    print(f"    Skipped low confidence: {skipped_low_conf}")
    print(f"    Skipped sanity mismatch: {skipped_sanity}")
    print(f"    Created clusters: {created_clusters}")

    return created_clusters
