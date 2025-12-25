from __future__ import annotations

from datetime import datetime
import json
import re

from sqlalchemy import select

from jp_digest.core.config import AppCfg
from jp_digest.services.ranking import rank_clusters_for_base
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import (
    ContentItem,
    ExperienceClusterMention,
    ExperienceMention,
)


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


def _normalize_text(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _dedupe_texts(items: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = _normalize_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def build_weekly_digest(cfg: AppCfg) -> str:
    lines: list[str] = []
    lines.append(f"# Weekly Digest: {cfg.trip.title}")
    lines.append(f"_Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z_")
    lines.append("")

    with session_scope() as s:
        for b in cfg.trip.bases:
            lines.append(f"## {b.name}")
            ranked = rank_clusters_for_base(cfg, b.name)[: cfg.digest.max_places_per_base]

            if not ranked:
                lines.append(
                    "- No high-signal clusters yet. Try ingesting more or widening queries."
                )
                lines.append("")
                continue

            for i, rc in enumerate(ranked, 1):
                lines.append(f"{i}. **{rc.canonical_name}**")
                lines.append(
                    f"   - **Type**: {rc.entity_type} | **Score**: {rc.score:.1f} | **Rec**: {rc.rec_avg:.1f}/10"
                )

                links = (
                    s.execute(
                        select(ExperienceClusterMention).where(
                            ExperienceClusterMention.cluster_id == rc.cluster_id
                        )
                    )
                    .scalars()
                    .all()
                )
                mention_ids = [l.mention_id for l in links]
                mentions = (
                    s.execute(
                        select(ExperienceMention).where(
                            ExperienceMention.id.in_(mention_ids)
                        )
                    )
                    .scalars()
                    .all()
                )
                content_item_ids = {m.content_item_id for m in mentions}
                content_items = (
                    s.execute(
                        select(ContentItem).where(ContentItem.id.in_(content_item_ids))
                    )
                    .scalars()
                    .all()
                )
                content_map = {ci.id: ci for ci in content_items}

                mentions_sorted = sorted(
                    mentions,
                    key=lambda m: (
                        float(m.recommendation_score or 0.0),
                        content_map.get(m.content_item_id).score
                        if content_map.get(m.content_item_id)
                        else 0,
                    ),
                    reverse=True,
                )

                authors: set[str] = set()
                threads: set[str] = set()
                sources: set[str] = set()

                why_texts: list[str] = []
                tips_texts: list[str] = []
                evidence_items: list[tuple[str, str, int]] = []

                for m in mentions_sorted:
                    ci = content_map.get(m.content_item_id)
                    if not ci:
                        continue

                    sources.add(ci.source_id)
                    if ci.author:
                        authors.add(ci.author)
                    threads.add(_thread_key(ci))

                    if m.experience_text:
                        why_texts.append(m.experience_text)

                    if m.negative_or_caution:
                        tips_texts.append(m.negative_or_caution)

                    if m.evidence_spans:
                        try:
                            spans = json.loads(m.evidence_spans)
                        except json.JSONDecodeError:
                            spans = []
                        if spans:
                            evidence_items.append((spans[0], ci.url, ci.score))

                why = _dedupe_texts(why_texts, cfg.digest.max_experiences_per_place)
                tips = _dedupe_texts(tips_texts, 2)

                evidence_items.sort(key=lambda x: x[2], reverse=True)
                evidence_items = evidence_items[:3]

                people_count = len(authors) if authors else len(sources)
                thread_count = len(threads) if threads else len(sources)

                lines.append(
                    f"   - **Support**: mentioned by {people_count} people across {thread_count} threads"
                )

                lines.append("")
                lines.append("   **Why people recommend it:**")
                if why:
                    for text in why:
                        lines.append(f"   - {text}")
                else:
                    lines.append("   - No clear reasons extracted yet.")

                if tips:
                    lines.append("")
                    lines.append("   **Tips/Cautions:**")
                    for text in tips:
                        lines.append(f"   - {text}")

                if evidence_items:
                    lines.append("")
                    lines.append("   **Evidence:**")
                    for snippet, url, _score in evidence_items:
                        lines.append(f"   - {snippet} _[Source]({url})_")

                lines.append("")

    return "\n".join(lines)
