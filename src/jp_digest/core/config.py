from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class BaseCfg(BaseModel):
    name: str
    radius_km: float = 30.0
    aliases: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)


class TripCfg(BaseModel):
    title: str = "Trip"
    bases: list[BaseCfg] = Field(default_factory=list)


class RedditCfg(BaseModel):
    subreddits: list[str] = Field(default_factory=lambda: ["JapanTravel"])
    time_filter: str = "year"
    time_filters: list[str] = Field(default_factory=list)
    limit_per_query: int = 25
    search_pages: int = 2
    sort: str = "top"
    pause_seconds: float = 2.0
    max_comments_per_post: int = 20
    min_comment_length: int = 150
    min_comment_score: int = 5


class DigestCfg(BaseModel):
    max_places_per_base: int = 8
    max_experiences_per_place: int = 3
    min_place_score: float = 1.5


class AppCfg(BaseModel):
    trip: TripCfg
    reddit: RedditCfg = RedditCfg()
    digest: DigestCfg = DigestCfg()


def load_config(path: str | None) -> AppCfg:
    p = Path(path)
    data: dict[str, Any] = yaml.safe_load(p.read_text(encoding="utf-8"))
    return AppCfg.model_validate(data)
