from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RedditItem:
    kind: str
    source_id: str
    url: str
    subreddit: str
    author: str | None
    title: str | None
    body: str
    score: int
    num_comments: int
    created_utc: int
    raw: dict[str, Any]


def _headers() -> dict[str, str]:
    return {
        "User-Agent": "jp-digest/0.1 by u/jgehunter",
        "Accept": "application/json",
    }


def _sleep(pause_seconds: float) -> None:
    if pause_seconds and pause_seconds > 0:
        time.sleep(pause_seconds)


@retry(
    stop=stop_after_attempt(8),
    wait=wait_exponential(multiplier=30, min=30, max=900),
    retry=retry_if_exception_type(
        (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def _search_page(
    subreddit: str,
    query: str,
    time_filter: str,
    limit: int,
    sort: str,
    after: str | None,
) -> tuple[list[dict], str | None]:
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {
        "q": query,
        "restrict_sr": "1",
        "sort": sort,
        "t": (
            time_filter
            if time_filter in {"hour", "day", "week", "month", "year", "all"}
            else "year"
        ),
        "limit": str(limit),
    }
    if after:
        params["after"] = after

    with httpx.Client(headers=_headers(), timeout=25.0) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    listing = data.get("data", {})
    children = listing.get("children", [])
    next_after = listing.get("after")
    return children, next_after


def search_posts(
    subreddit: str,
    query: str,
    time_filter: str,
    limit: int,
    pages: int = 1,
    sort: str = "top",
    pause_seconds: float = 3.0,
) -> list[dict]:
    results: list[dict] = []
    after: str | None = None

    for _ in range(max(1, pages)):
        children, after = _search_page(
            subreddit=subreddit,
            query=query,
            time_filter=time_filter,
            limit=limit,
            sort=sort,
            after=after,
        )
        results.extend(children)

        if not after:
            break
        _sleep(pause_seconds)

    return results


@retry(
    stop=stop_after_attempt(8),
    wait=wait_exponential(exp_base=10, multiplier=1, min=90, max=300),
    retry=retry_if_exception_type(
        (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def fetch_post_and_top_comments(
    permalink: str, max_comments: int, pause_seconds: float = 3.0
) -> tuple[RedditItem, list[RedditItem]]:
    """
    Fetch a post and its top comments.
    Now uses shorter delay (1 second) to speed up ingestion.
    """
    url = f"https://www.reddit.com{permalink}.json"
    with httpx.Client(headers=_headers(), timeout=25.0) as client:
        r = client.get(url, params={"limit": max_comments, "sort": "relevance"})
        r.raise_for_status()
        payload = r.json()

    post_d = payload[0]["data"]["children"][0]["data"]
    post = RedditItem(
        kind="post",
        source_id=f"t3_{post_d['id']}",
        url=f"https://www.reddit.com{post_d['permalink']}",
        subreddit=post_d.get("subreddit", ""),
        author=post_d.get("author"),
        title=post_d.get("title"),
        body=post_d.get("selftext", ""),
        score=int(post_d.get("score", 0)),
        num_comments=int(post_d.get("num_comments", 0)),
        created_utc=int(post_d.get("created_utc", 0)),
        raw=post_d,
    )

    comments: list[RedditItem] = []
    for c in payload[1]["data"]["children"]:
        if c.get("kind") != "t1":
            continue
        cd = c["data"]
        body = cd.get("body") or ""
        if body in {"", "[deleted]", "[removed]"}:
            continue
        comments.append(
            RedditItem(
                kind="comment",
                source_id=f"t1_{cd['id']}",
                url=f"https://www.reddit.com{cd['permalink']}",
                subreddit=cd.get("subreddit", ""),
                author=cd.get("author"),
                title=None,
                body=body,
                score=int(cd.get("score", 0)),
                created_utc=int(cd.get("created_utc", 0)),
                num_comments=0,
                raw=cd,
            )
        )

    # Reduced delay from 2-3 seconds to 1 second for faster ingestion
    _sleep(min(1.0, pause_seconds))
    return post, comments
