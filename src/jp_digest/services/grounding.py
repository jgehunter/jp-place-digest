from __future__ import annotations

from dataclasses import dataclass
from math import cos, pi

from sqlalchemy import select

from jp_digest.core.config import AppCfg, BaseCfg
from jp_digest.core.textnorm import normalize
from jp_digest.services.nominatim import haversine_km, search
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import (
    BaseAssignment,
    ContentItem,
    Experience,
    ExperiencePoi,
    Poi,
)

# Only exclude extremely obvious administrative/geographic entities
EXCLUDE_TYPES = {
    "administrative",
    "city",
    "county",
    "state",
    "region",
    "province",
    "country",
    "continent",
}

EXCLUDE_CATEGORIES = {
    "boundary",
    "place",  # Often just admin boundaries
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


def _is_obviously_wrong(category: str, place_type: str) -> bool:
    """Only filter out obvious administrative boundaries and generic places."""
    category = category.lower().strip()
    place_type = place_type.lower().strip()

    if category in EXCLUDE_CATEGORIES:
        return True
    if place_type in EXCLUDE_TYPES:
        return True

    return False


def _build_base_terms(cfg: AppCfg) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for b in cfg.trip.bases:
        terms = [normalize(b.name)]
        terms.extend([normalize(a) for a in b.aliases])
        out[b.name] = [t for t in terms if t]
    return out


def ground_experiences(cfg: AppCfg, limit_experiences: int = 400) -> int:
    """
    For each Experience with place_mentions:
    - resolve mention to a POI constrained to each base (mention + base name)
    - pick best match inside radius
    - link Experience -> POI
    - assign POI to base with distance

    Simplified version: trust Nominatim search and only exclude obvious errors.
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
    skipped_no_match = 0
    skipped_base_name = 0
    skipped_obvious_error = 0

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

        total = len(exps)
        print(f"  Processing {total} experiences...")

        for idx, e in enumerate(exps, 1):
            mentions = [
                m.strip() for m in (e.place_mentions or "").split(";") if m.strip()
            ]
            if not mentions:
                continue

            if idx % 10 == 0 or idx == 1:
                print(
                    f"  [{idx}/{total}] Grounding experience {e.id} with {len(mentions)} mentions"
                )

            for m in mentions:
                # Skip if already grounded
                existing = s.execute(
                    select(ExperiencePoi).where(
                        ExperiencePoi.experience_id == e.id,
                        ExperiencePoi.mention_text == m,
                    )
                ).scalar_one_or_none()
                if existing:
                    continue

                # Check if mention is just a base name
                norm_m = normalize(m)
                if norm_m in base_like:
                    skipped_base_name += 1
                    continue

                best = None  # (candidate, base_center, dist_km, importance)

                for bc in centers:
                    # Search for this mention near this base
                    q = f"{m}, {bc.base_name}, Japan"
                    viewbox = _viewbox_for_radius(bc.lat, bc.lon, bc.radius_km)
                    candidates = search(
                        q,
                        limit=10,
                        countrycodes="jp",
                        viewbox=viewbox,
                        bounded=True,
                    )

                    for c in candidates:
                        cand_category = c.category or ""
                        cand_type = c.place_type or ""

                        # Only filter out obvious errors
                        if _is_obviously_wrong(cand_category, cand_type):
                            continue

                        # Check distance
                        dist = haversine_km(bc.lat, bc.lon, c.lat, c.lon)
                        if dist > bc.radius_km:
                            continue

                        # Pick best by importance, then proximity
                        key = (c.importance, -dist)
                        if best is None or key > best[3]:
                            best = (c, bc, dist, key)

                if best is None:
                    skipped_no_match += 1
                    continue

                cand, bc, dist_km, _ = best

                # Create or get POI
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

                # Link experience to POI
                s.add(
                    ExperiencePoi(
                        experience_id=e.id,
                        poi_id=poi.poi_id,
                        mention_text=m,
                        link_confidence=0.7,
                    )
                )

                # Assign POI to base if not already assigned
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

    print(f"\n  Grounding Summary:")
    print(f"    ✓ Successfully grounded: {created}")
    print(f"    ⊙ No match found: {skipped_no_match}")
    print(f"    ⊙ Base names skipped: {skipped_base_name}")
    print(f"    ⊙ Obvious errors filtered: {skipped_obvious_error}")
    return created
