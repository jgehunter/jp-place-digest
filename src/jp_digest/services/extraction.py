from __future__ import annotations

import json
import re

from sqlalchemy import delete, select

from jp_digest.core.config import AppCfg, BaseCfg
from jp_digest.services.llm import extract_experiences
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import (
    ContentItem,
    ExperienceClusterMention,
    ExperienceMention,
)

_MAX_EVIDENCE = 2

_GENERIC_ENTITY_NAMES = {
    "japan",
    "nihon",
    "nippon",
}


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


def _clean_evidence_spans(value: object) -> list[str]:
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


def _clean_location_hint(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return "; ".join(parts)
    return str(value).strip()


def _clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_float(value: object, default: float = 0.5) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_token(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^\w\s]", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _build_base_tokens(bases: list[BaseCfg]) -> set[str]:
    tokens: set[str] = set()
    for b in bases:
        tokens.add(_normalize_token(b.name))
        for alias in b.aliases:
            tokens.add(_normalize_token(alias))
    tokens = {t for t in tokens if t}
    return tokens


def _is_generic_entity_name(value: str, base_tokens: set[str]) -> bool:
    norm = _normalize_token(value)
    if not norm:
        return True
    if norm in base_tokens:
        return True
    if norm in _GENERIC_ENTITY_NAMES:
        return True
    return False


def _bases_payload(cfg: AppCfg) -> list[dict[str, list[str]]]:
    return [
        {
            "name": b.name,
            "aliases": list(b.aliases),
        }
        for b in cfg.trip.bases
    ]


def extract_for_new_content(
    cfg: AppCfg, limit: int = 120, reextract_all: bool = False
) -> int:
    """
    Extract experience mentions for content items that have none yet.
    """
    created = 0
    base_tokens = _build_base_tokens(cfg.trip.bases)
    base_names = {b.name for b in cfg.trip.bases}
    base_lookup = {b.name.lower(): b.name for b in cfg.trip.bases}
    bases_payload = _bases_payload(cfg)

    with session_scope() as s:
        stmt = select(ContentItem).order_by(ContentItem.id.desc())
        if not reextract_all:
            stmt = stmt.where(~ContentItem.mentions.any()).limit(limit)
        items = s.execute(stmt).scalars().all()

        total = len(items)
        print(f"  Processing {total} content items...")

        for idx, ci in enumerate(items, 1):
            print(
                f"  [{idx}/{total}] Extracting from {ci.kind} (score={ci.score}, id={ci.id})"
            )

            if reextract_all:
                mention_ids = (
                    s.execute(
                        select(ExperienceMention.id).where(
                            ExperienceMention.content_item_id == ci.id
                        )
                    )
                    .scalars()
                    .all()
                )
                if mention_ids:
                    s.execute(
                        delete(ExperienceClusterMention).where(
                            ExperienceClusterMention.mention_id.in_(mention_ids)
                        )
                    )
                s.execute(
                    delete(ExperienceMention).where(
                        ExperienceMention.content_item_id == ci.id
                    )
                )

            payload = extract_experiences(_content_to_prompt(ci), bases_payload)
            item_created = 0

            for m in payload.get("mentions", []):
                entity_name = str(m.get("entity_name") or "").strip()
                if not entity_name or _is_generic_entity_name(entity_name, base_tokens):
                    continue

                entity_type = str(m.get("entity_type") or "other").lower().strip()
                if not entity_type:
                    continue

                experience_text = str(m.get("experience_text") or "").strip()
                if not experience_text:
                    continue

                location_hint = _clean_location_hint(m.get("location_hint"))
                if not location_hint:
                    continue

                location_confidence = _parse_float(m.get("location_confidence"), 0.5)
                location_confidence = max(0.0, min(1.0, location_confidence))

                assigned_base_raw = str(m.get("assigned_base") or "").strip()
                if not assigned_base_raw or assigned_base_raw == "Unknown":
                    continue
                assigned_base = base_lookup.get(assigned_base_raw.lower())
                if not assigned_base or assigned_base not in base_names:
                    continue

                assigned_base_confidence = _parse_float(
                    m.get("assigned_base_confidence"), 0.5
                )
                assigned_base_confidence = max(
                    0.0, min(1.0, assigned_base_confidence)
                )

                rec_score = _parse_float(m.get("recommendation_score"), 0.0)
                rec_score = max(0.0, min(10.0, rec_score))

                evidence_spans = _clean_evidence_spans(m.get("evidence_spans"))
                evidence_json = (
                    json.dumps(evidence_spans, ensure_ascii=True)
                    if evidence_spans
                    else None
                )

                negative_or_caution = _clean_optional_text(m.get("negative_or_caution"))
                canonicalization_hint = _clean_optional_text(
                    m.get("canonicalization_hint")
                )

                mention = ExperienceMention(
                    content_item_id=ci.id,
                    entity_name=entity_name[:256],
                    entity_type=entity_type[:48],
                    experience_text=experience_text,
                    recommendation_score=rec_score,
                    location_hint=location_hint,
                    location_confidence=location_confidence,
                    evidence_spans=evidence_json,
                    negative_or_caution=negative_or_caution,
                    canonicalization_hint=canonicalization_hint,
                    assigned_base=assigned_base[:128],
                    assigned_base_confidence=assigned_base_confidence,
                )
                s.add(mention)
                item_created += 1
                created += 1

            if item_created > 0:
                print(f"    OK: Found {item_created} mentions (total: {created})")
            else:
                print("    OK: No valid mentions found")

    return created
