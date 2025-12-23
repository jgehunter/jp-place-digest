from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import log1p

from sqlalchemy import select

from jp_digest.core.config import AppCfg
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import (
    BaseAssignment,
    ContentItem,
    Experience,
    ExperiencePoi,
    Poi,
)


@dataclass(frozen=True)
class RankedPlace:
    base_name: str
    poi_id: str
    name: str
    address: str | None
    category: str | None
    score: float
    reasons: list[str]


def rank_places_for_base(cfg: AppCfg, base_name: str) -> list[RankedPlace]:
    with session_scope() as s:
        assigned = (
            s.execute(
                select(BaseAssignment).where(BaseAssignment.base_name == base_name)
            )
            .scalars()
            .all()
        )
        if not assigned:
            return []

        poi_ids = [a.poi_id for a in assigned]
        dist_by_poi = {a.poi_id: float(a.distance_km) for a in assigned}

        links = (
            s.execute(select(ExperiencePoi).where(ExperiencePoi.poi_id.in_(poi_ids)))
            .scalars()
            .all()
        )

        freq = defaultdict(int)
        exp_ids_by_poi = defaultdict(list)
        for l in links:
            freq[l.poi_id] += 1
            exp_ids_by_poi[l.poi_id].append(l.experience_id)

        results: list[RankedPlace] = []
        for poi_id, count in freq.items():
            poi = s.get(Poi, poi_id)
            if not poi:
                continue

            exp_ids = exp_ids_by_poi[poi_id]
            exps = [s.get(Experience, eid) for eid in exp_ids]
            exps = [e for e in exps if e is not None]

            pop = 0.0
            conf = 0.0
            pol = 0.0
            rec = 0.0
            for e in exps[: cfg.digest.max_experiences_per_place * 2]:
                ci = s.get(ContentItem, e.content_item_id)
                pop += log1p(max(0, int(ci.score if ci else 0)))
                conf += float(e.confidence or 0.5)
                rec += float(getattr(e, "recommendation_score", 0.0) or 0.0)
                if e.polarity == "positive":
                    pol += 1.0
                elif e.polarity == "negative":
                    pol -= 2.0

            dist = dist_by_poi.get(poi_id, 999.0)
            proximity = max(0.0, 1.0 - (dist / 50.0))
            rec_avg = rec / max(1, len(exps))

            # Simple deterministic baseline score:
            score = (
                0.9 * count
                + 1.2 * pop
                + 0.8 * conf
                + 1.6 * rec_avg
                + 1.0 * proximity
                + pol
            )

            reasons = [
                f"mentions={count}",
                f"pop={pop:.2f}",
                f"conf={conf:.2f}",
                f"rec_avg={rec_avg:.2f}",
                f"dist_km={dist:.2f}",
                f"pol={pol:.2f}",
            ]

            results.append(
                RankedPlace(
                    base_name=base_name,
                    poi_id=poi_id,
                    name=poi.name,
                    address=poi.address,
                    category=poi.category,
                    score=score,
                    reasons=reasons,
                )
            )

    results.sort(key=lambda x: x.score, reverse=True)
    return [r for r in results if r.score >= cfg.digest.min_place_score]
