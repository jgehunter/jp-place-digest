from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi

from sqlalchemy import select

from jp_digest.core.config import AppCfg, BaseCfg
from jp_digest.core.textnorm import mention_matches_candidate, normalize
from jp_digest.services.nominatim import haversine_km, search
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import (
    BaseAssignment,
    ContentItem,
    Experience,
    ExperiencePoi,
    Poi,
)

BAD_TYPES = {
    "administrative",
    "city",
    "county",
    "state",
    "region",
    "province",
    "neighbourhood",
    "suburb",
    "hamlet",
    "locality",
    "yes",
    "stop",
}
BAD_CATEGORY = {"boundary", "place", "administrative", "railway", "highway", "waterway"}

ALLOWED_CATEGORIES = {"tourism", "leisure", "historic", "shop"}
ALLOWED_TYPES = {
    "restaurant",
    "cafe",
    "fast_food",
    "bar",
    "pub",
    "izakaya",
    "bakery",
    "confectionery",
    "museum",
    "gallery",
    "attraction",
    "viewpoint",
    "park",
    "garden",
    "zoo",
    "aquarium",
    "temple",
    "shrine",
    "castle",
    "marketplace",
    "spa",
    "hot_spring",
    "trail",
    "bridge",
    "monument",
    "hotel",
    "hostel",
    "guest_house",
    "theatre",
    "cinema",
}


@dataclass(frozen=True)
class BaseCenter:
    base_name: str
    lat: float
    lon: float
    radius_km: float


def _viewbox_for_radius(
    lat: float, lon: float, radius_km: float
) -> tuple[float, float, float, float]:
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * cos(lat * pi / 180.0))
    left = lon - lon_delta
    right = lon + lon_delta
    top = lat + lat_delta
    bottom = lat - lat_delta
    return (left, top, right, bottom)


def _base_center(base: BaseCfg) -> BaseCenter | None:
    candidates = search(f"{base.name}, Japan", limit=1, countrycodes="jp")
    if not candidates:
        return None
    c = candidates[0]
    return BaseCenter(
        base_name=base.name, lat=c.lat, lon=c.lon, radius_km=base.radius_km
    )


def _allowed_candidate(category: str, place_type: str) -> bool:
    if category in BAD_CATEGORY or place_type in BAD_TYPES:
        return False
    if place_type in ALLOWED_TYPES:
        return True
    if category in ALLOWED_CATEGORIES:
        return True
    return False


def _build_base_terms(cfg: AppCfg) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for b in cfg.trip.bases:
        terms = [normalize(b.name)]
        terms.extend([normalize(a) for a in b.aliases])
        out[b.name] = [t for t in terms if t]
    return out


def _content_mentions_any(content_norm: str, terms: list[str]) -> bool:
    return any(t in content_norm for t in terms)


def _content_mentions_other_base(
    content_norm: str, base_terms: dict[str, list[str]], target_base: str
) -> bool:
    if _content_mentions_any(content_norm, base_terms.get(target_base, [])):
        return False
    for name, terms in base_terms.items():
        if name == target_base:
            continue
        if _content_mentions_any(content_norm, terms):
            return True
    return False


def ground_experiences(cfg: AppCfg, limit_experiences: int = 400) -> int:
    """
    For each Experience with place_mentions:
    - resolve mention to a POI constrained to each base (mention + base name)
    - pick best match inside radius
    - link Experience -> POI
    - assign POI to base with distance
    """
    centers = []
    base_like = set()
    base_terms = _build_base_terms(cfg)
    for b in cfg.trip.bases:
        base_like.add(normalize(b.name))
        for a in b.aliases:
            base_like.add(normalize(a))
        bc = _base_center(b)
        if bc:
            centers.append(bc)

    if not centers:
        raise RuntimeError("Could not resolve any base centers via Nominatim.")

    created = 0
    with session_scope() as s:
        seen_base_pois = set()
        existing_assignments = s.execute(select(BaseAssignment)).scalars().all()
        for ba in existing_assignments:
            seen_base_pois.add((ba.base_name, ba.poi_id))

        exps = (
            s.execute(
                select(Experience)
                .order_by(Experience.id.desc())
                .limit(limit_experiences)
            )
            .scalars()
            .all()
        )

        for e in exps:
            mentions = [
                m.strip() for m in (e.place_mentions or "").split(";") if m.strip()
            ]
            if not mentions:
                continue

            ci = s.get(ContentItem, e.content_item_id)
            content_norm = normalize(((ci.title or "") + " " + (ci.body or ""))) if ci else ""

            for m in mentions:
                existing = s.execute(
                    select(ExperiencePoi).where(
                        ExperiencePoi.experience_id == e.id,
                        ExperiencePoi.mention_text == m,
                    )
                ).scalar_one_or_none()
                if existing:
                    continue

                best = None  # (candidate, base_center, dist_km, key)
                for bc in centers:
                    if content_norm and _content_mentions_other_base(
                        content_norm, base_terms, bc.base_name
                    ):
                        continue

                    q = f"{m}, {bc.base_name}, Japan"
                    viewbox = _viewbox_for_radius(bc.lat, bc.lon, bc.radius_km)
                    candidates = search(
                        q,
                        limit=6,
                        countrycodes="jp",
                        viewbox=viewbox,
                        bounded=True,
                    )
                    for c in candidates:
                        cand_category = (c.category or "").lower()
                        cand_type = (c.place_type or "").lower()
                        if not _allowed_candidate(cand_category, cand_type):
                            continue
                        if not mention_matches_candidate(m, c.name, c.display_name):
                            continue
                        dist = haversine_km(bc.lat, bc.lon, c.lat, c.lon)
                        if dist > bc.radius_km:
                            continue
                        key = (c.importance, -dist)
                        if best is None or key > best[3]:
                            best = (c, bc, dist, key)

                if best is None:
                    continue

                cand, bc, dist_km, _ = best

                norm_m = normalize(m)
                if norm_m == normalize(bc.base_name):
                    continue
                if norm_m in base_like:
                    continue

                poi = s.get(Poi, cand.poi_id)
                if poi is None:
                    poi = Poi(
                        poi_id=cand.poi_id,
                        provider="nominatim",
                        name=cand.name,
                        lat=cand.lat,
                        lon=cand.lon,
                        address=cand.address,
                        category=cand.category,
                    )
                    s.add(poi)
                    s.flush()

                s.add(
                    ExperiencePoi(
                        experience_id=e.id,
                        poi_id=poi.poi_id,
                        mention_text=m,
                        link_confidence=0.7,
                    )
                )

                base_poi_key = (bc.base_name, poi.poi_id)
                if base_poi_key not in seen_base_pois:
                    s.add(
                        BaseAssignment(
                            base_name=bc.base_name,
                            poi_id=poi.poi_id,
                            distance_km=float(dist_km),
                        )
                    )
                    seen_base_pois.add(base_poi_key)

                created += 1

    return created
