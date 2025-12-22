from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select

from jp_digest.core.config import AppCfg
from jp_digest.services.ranking import rank_places_for_base
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import ContentItem, Experience, ExperiencePoi


def build_weekly_digest(cfg: AppCfg) -> str:
    lines: list[str] = []
    lines.append(f"# Weekly Digest: {cfg.trip.title}")
    lines.append(f"_Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z_")
    lines.append("")

    with session_scope() as s:
        for b in cfg.trip.bases:
            lines.append(f"## {b.name}")
            ranked = rank_places_for_base(cfg, b.name)[: cfg.digest.max_places_per_base]

            # Filter out obvious bad matches
            ranked = [
                r
                for r in ranked
                if not any(
                    bad in r.name.lower() for bad in ["beijing", "kathmandu", "lhasa"]
                )
                and r.score >= cfg.digest.min_place_score
            ]

            if not ranked:
                lines.append(
                    "- No grounded high-signal places yet. Try ingesting more or widening queries."
                )
                lines.append("")
                continue

            for i, rp in enumerate(ranked, 1):
                # Use address to extract English name if available
                display_name = rp.name
                if rp.address and "," in rp.address:
                    # Try to get English name from address
                    parts = [p.strip() for p in rp.address.split(",")]
                    # Look for parts with Latin characters
                    for part in parts[:3]:
                        if any(ord(c) < 128 for c in part) and len(part) > 2:
                            display_name = part
                            break

                lines.append(f"{i}. **{display_name}**")
                lines.append(
                    f"   - **Score**: {rp.score:.1f} | **Category**: {rp.category or 'place'} | **Distance**: {rp.reasons[3].split('=')[1]} km"
                )

                # Gather experiences
                stmt = (
                    select(ExperiencePoi)
                    .where(ExperiencePoi.poi_id == rp.poi_id)
                    .limit(30)
                )
                links = s.execute(stmt).scalars().all()

                # Group experiences by polarity
                positive_exps = []
                neutral_exps = []
                negative_exps = []

                seen_urls: set[str] = set()
                for l in links:
                    e = s.get(Experience, l.experience_id)
                    if not e:
                        continue
                    ci = s.get(ContentItem, e.content_item_id)
                    if not ci or ci.url in seen_urls:
                        continue

                    exp_data = {
                        "summary": e.summary,
                        "url": ci.url,
                        "score": ci.score,
                        "activity_type": e.activity_type,
                    }

                    if e.polarity == "positive":
                        positive_exps.append(exp_data)
                    elif e.polarity == "negative":
                        negative_exps.append(exp_data)
                    else:
                        neutral_exps.append(exp_data)

                    seen_urls.add(ci.url)

                # Show positive experiences first
                lines.append("")
                lines.append("   **Why Visit:**")
                shown = 0
                for exp in sorted(
                    positive_exps, key=lambda x: x["score"], reverse=True
                ):
                    if shown >= cfg.digest.max_experiences_per_place:
                        break
                    lines.append(f"   - {exp['summary']}")
                    lines.append(f"     _[Source]({exp['url']})_")
                    shown += 1

                # Add neutral if we need more
                for exp in sorted(neutral_exps, key=lambda x: x["score"], reverse=True):
                    if shown >= cfg.digest.max_experiences_per_place:
                        break
                    lines.append(f"   - {exp['summary']}")
                    lines.append(f"     _[Source]({exp['url']})_")
                    shown += 1

                # Show warnings if any
                if negative_exps:
                    lines.append("")
                    lines.append("   **Warnings:**")
                    for exp in negative_exps[:2]:
                        lines.append(f"   - {exp['summary']}")
                        lines.append(f"     _[Source]({exp['url']})_")

                lines.append("")

    return "\n".join(lines)
