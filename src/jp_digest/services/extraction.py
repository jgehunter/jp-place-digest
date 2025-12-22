from __future__ import annotations

from sqlalchemy import select

from jp_digest.services.llm import extract_experiences
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import ContentItem, Experience


def _content_to_prompt(ci: ContentItem) -> str:
    title = ci.title or ""
    # Fixed: concatenate strings properly
    return (
        f"SUBREDDIT: {ci.subreddit}\n"
        f"KIND: {ci.kind}\n"
        f"SCORE: {ci.score}\n"
        f"TITLE: {title}\n"
        f"TEXT:\n{ci.body}\n"
    )


def extract_for_new_content(limit: int = 120) -> int:
    """
    Extract experiences for content items that have none yet.
    """
    created = 0
    with session_scope() as s:
        # Find ContentItems without any Experience
        stmt = (
            select(ContentItem)
            .where(~ContentItem.experiences.any())
            .order_by(ContentItem.id.desc())
            .limit(limit)
        )
        items = s.execute(stmt).scalars().all()

        for ci in items:
            payload = extract_experiences(_content_to_prompt(ci))
            for e in payload.get("experiences", []):
                mentions = e.get("place_mentions") or []
                summary = str(e.get("summary") or "").strip()
                if not summary:
                    continue

                exp = Experience(
                    content_item_id=ci.id,
                    polarity=str(e.get("polarity") or "neutral")[
                        :16
                    ],  # Fixed typo: polarit -> polarity
                    activity_type=str(e.get("activity_type") or "other")[:32],
                    summary=summary,
                    confidence=float(e.get("confidence") or 0.5),
                    place_mentions="; ".join(
                        [str(m).strip() for m in mentions if str(m).strip()]
                    ),
                )
                s.add(exp)
                created += 1

    return created
