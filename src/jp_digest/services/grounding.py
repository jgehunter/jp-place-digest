from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from jp_digest.core.config import AppCfg, BaseCfg
from jp_digest.services.nominatim import haversine_km, search
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import (
    BaseAssignment,
    ContentItem,
    Experience,
    ExperiencePoi,
    Poi,
)


@dataclass(frozen=True)
class BaseCenter:
    base_name: str
    lat: float
    lon: float
    radius_km: float


def _base_center(base: BaseCfg) -> BaseCenter | None:
    # Resolve base city once per run
    candidates = search(f"{base.name}, Japan", limit=1)
    if not candidates:
        return None
    c = candidates[0]
    return BaseCenter(
        base_name=base.name, lat=c.lat, lon=c.lon, radius_km=base.radius_km
    )


def ground_experiences(cfg: AppCfg, limit_experiences: int = 400) -> int:
    """
    For each Experience with place_mentions:
    - resolve mention to a POI constrained to each base (mention + base name)
    - pick best match inside radius
    - link Experience -> POI
    - assign POI to base with distance
    """
    centers = []
    for b in cfg.trip.bases:
        bc = _base_center(b)
        if bc:
            centers.append(bc)

    if not centers:
        raise RuntimeError("Could not resolve any base centers bia Nominatim.")

    created = 0
    with session_scope() as s:
        # Track base assignments we've added in this session to avoid duplicates
        seen_base_pois = set()

        # Pre-load existing base assignments into the set
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

            for m in mentions:
                # Already linked?
                existing = s.execute(
                    select(ExperiencePoi).where(
                        ExperiencePoi.experience_id == e.id,
                        ExperiencePoi.mention_text == m,
                    )
                ).scalar_one_or_none()
                if existing:
                    continue

                best = None  # (candiate, base_center, dist_km, key)
                for bc in centers:
                    q = f"{m}, {bc.base_name}, Japan"
                    candidates = search(q, limit=4)
                    for c in candidates:
                        dist = haversine_km(bc.lat, bc.lon, c.lat, c.lon)
                        if dist > bc.radius_km:
                            continue
                        key = (c.importance, -dist)
                        if best is None or key > best[3]:
                            best = (c, bc, dist, key)

                if best is None:
                    continue

                cand, bc, dist_km, _ = best

                # Upsert POI
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
                    # Flush immediately so the POI exists before we reference it
                    s.flush()

                s.add(
                    ExperiencePoi(
                        experience_id=e.id,
                        poi_id=poi.poi_id,
                        mention_text=m,
                        link_confidence=0.7,
                    )
                )

                # Check if we've already added this base assignment (in DB or in this session)
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
