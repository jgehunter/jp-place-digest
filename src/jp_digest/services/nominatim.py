from __future__ import annotations

import os
from dataclasses import dataclass
from math import atan2, cos, pi, sin, sqrt
from typing import Iterable

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter


POI_USER_AGENT = os.environ.get("POI_USER_AGENT", "jp-digest/0.1")


@dataclass(frozen=True)
class PoiCandidate:
    poi_id: str
    name: str
    display_name: str | None
    lat: float
    lon: float
    address: str | None
    category: str | None
    place_type: str | None
    importance: float


def _format_viewbox(viewbox: Iterable[float] | None) -> str | None:
    if not viewbox:
        return None
    left, top, right, bottom = viewbox
    return f"{left},{top},{right},{bottom}"


@retry(wait=wait_exponential_jitter(initial=1, max=10), stop=stop_after_attempt(4))
def search(
    query: str,
    limit: int = 5,
    countrycodes: str | None = "jp",
    viewbox: Iterable[float] | None = None,
    bounded: bool = False,
) -> list[PoiCandidate]:
    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": limit,
    }
    if countrycodes:
        params["countrycodes"] = countrycodes
    viewbox_str = _format_viewbox(viewbox)
    if viewbox_str:
        params["viewbox"] = viewbox_str
        params["bounded"] = 1 if bounded else 0

    headers = {"User-Agent": POI_USER_AGENT}

    with httpx.Client(headers=headers, timeout=25.0) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    out: list[PoiCandidate] = []
    for d in data:
        osm_type = d.get("osm_type")
        osm_id = d.get("osm_id")
        poi_id = f"nominatim:{osm_type}:{osm_id}"
        display = d.get("display_name")
        out.append(
            PoiCandidate(
                poi_id=poi_id,
                name=d.get("name") or (display.split(",")[0] if display else query),
                display_name=display,
                lat=float(d["lat"]),
                lon=float(d["lon"]),
                address=display,
                category=str(d.get("class") or d.get("category") or ""),
                place_type=str(d.get("type") or ""),
                importance=float(d.get("importance") or 0.0),
            )
        )
    return out


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    p = pi / 180.0
    dlat = (lat2 - lat1) * p
    dlon = (lon2 - lon1) * p
    a = sin(dlat / 2) ** 2 + cos(lat1 * p) * cos(lat2 * p) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c
