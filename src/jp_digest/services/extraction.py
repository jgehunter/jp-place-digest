from __future__ import annotations

import json

from sqlalchemy import delete, select

from jp_digest.core.textnorm import normalize, tokens
from jp_digest.services.llm import extract_experiences
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import ContentItem, Experience, ExperiencePoi


_GENERIC_NAMES = {
    "tokyo",
    "kyoto",
    "osaka",
    "japan",
    "shikoku",
    "kagawa",
    "ehime",
    "tokushima",
    "shibuya",
    "shinjuku",
    "asakusa",
    "gion",
}

_GENERIC_TOKENS = {
    "city",
    "prefecture",
    "ward",
    "district",
    "station",
    "area",
    "region",
    "neighborhood",
    "train",
    "shinkansen",
    "jr",
    "metro",
    "line",
    "bus",
}

_GENERIC_CHAINS = {
    "7 eleven",
    "7 11",
    "seven eleven",
    "familymart",
    "lawson",
    "uniqlo",
    "gu",
    "loft",
}

_ALLOWED_POLARITY = {"positive", "negative"}
_MIN_POSITIVE_SCORE = 6.0
_MIN_NEGATIVE_SCORE = 7.0
_MAX_EVIDENCE = 2


def _content_to_prompt(ci: ContentItem) -> str:
    title = ci.title or ""
    body = ci.body

    # Truncate body if too long (roughly 3000 tokens = ~12000 chars)
    if len(body) > 10000:
        body = body[:10000] + "\n\n[... content truncated ...]"

    return (
        f"""
SUBREDDIT: {ci.subreddit}
KIND: {ci.kind}
SCORE: {ci.score}
TITLE: {title}
TEXT:
{body}
""".strip()
        + "\n"
    )


def _is_actionable_mention(mention: str) -> bool:
    nm = normalize(mention)
    if not nm or nm in _GENERIC_NAMES:
        return False
    if any(t in _GENERIC_TOKENS for t in tokens(mention)):
        return False
    if len(tokens(mention)) == 0:
        return False
    for chain in _GENERIC_CHAINS:
        if chain in nm:
            return False
    return True


def _clamp_score(value: object) -> float:
    try:
        score = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(10.0, score))


def _clean_evidence(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            continue
        out.append(text)
        if len(out) >= _MAX_EVIDENCE:
            break
    return out


def extract_for_new_content(limit: int = 120, reextract_all: bool = False) -> int:
    """
    Extract experiences for content items that have none yet.
    """
    created = 0
    with session_scope() as s:
        stmt = select(ContentItem).order_by(ContentItem.id.desc())
        if not reextract_all:
            stmt = stmt.where(~ContentItem.experiences.any()).limit(limit)
        items = s.execute(stmt).scalars().all()

        total = len(items)
        print(f"  Processing {total} content items...")

        for idx, ci in enumerate(items, 1):
            print(
                f"  [{idx}/{total}] Extracting from {ci.kind} (score={ci.score}, id={ci.id})"
            )

            if reextract_all:
                exp_ids = (
                    s.execute(
                        select(Experience.id).where(Experience.content_item_id == ci.id)
                    )
                    .scalars()
                    .all()
                )
                if exp_ids:
                    s.execute(
                        delete(ExperiencePoi).where(
                            ExperiencePoi.experience_id.in_(exp_ids)
                        )
                    )
                s.execute(delete(Experience).where(Experience.content_item_id == ci.id))

            payload = extract_experiences(_content_to_prompt(ci))
            item_created = 0

            for e in payload.get("experiences", []):
                mentions = e.get("place_mentions") or []
                summary = str(e.get("summary") or "").strip()
                if not summary:
                    continue

                polarity = str(e.get("polarity") or "").lower().strip()
                if polarity not in _ALLOWED_POLARITY:
                    continue

                rec_score = _clamp_score(e.get("recommendation_score"))
                if polarity == "positive" and rec_score < _MIN_POSITIVE_SCORE:
                    continue
                if polarity == "negative" and rec_score < _MIN_NEGATIVE_SCORE:
                    continue

                mentions = [str(m).strip() for m in mentions if str(m).strip()]
                mentions = [m for m in mentions if _is_actionable_mention(m)]
                mentions = list(dict.fromkeys(mentions))
                if not mentions:
                    continue

                conf = float(e.get("confidence") or 0.5)
                conf = max(0.0, min(1.0, conf))

                evidence = _clean_evidence(e.get("evidence"))
                evidence_json = (
                    json.dumps(evidence, ensure_ascii=True) if evidence else None
                )

                exp = Experience(
                    content_item_id=ci.id,
                    polarity=polarity[:16],
                    activity_type=str(e.get("activity_type") or "other")[:32],
                    summary=summary,
                    confidence=conf,
                    recommendation_score=rec_score,
                    evidence=evidence_json,
                    place_mentions="; ".join(mentions),
                )
                s.add(exp)
                item_created += 1
                created += 1

            if item_created > 0:
                print(f"    ✓ Found {item_created} experiences (total: {created})")
            else:
                print(f"    ⊙ No valid experiences found")

    return created
