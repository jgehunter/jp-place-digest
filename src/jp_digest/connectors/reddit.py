from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
import logging

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


def _headers() -> dict[str, str]:
    return {"User-Agent": "jp-digest/0.1 by u/jgehunter", "Accept": "application/json"}


@retry(
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=2, min=60, max=600),
    retry=retry_if_exception_type(
        (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def search_posts(
    subreddit: str, query: str, time_filter: str, limit: int
) -> list[dict]:
    url = f"https://www.reddit.com/r/{subreddit}/search.json"
    params = {
        "q": query,
        "restrict_sr": "1",
        "sort": "top",
        "t": (
            time_filter
            if time_filter in {"hour", "day", "week", "month", "year", "all"}
            else "year"
        ),
        "limit": str(limit),
    }
    with httpx.Client(headers=_headers(), timeout=25.0) as client:
        r = client.get(url, params=params)
        r.raise_for_status()
        data = r.json()

    # polite pacing
    time.sleep(3.0)
    return data.get("data", {}).get("children", [])


@retry(
    stop=stop_after_attempt(6),
    wait=wait_exponential(multiplier=2, min=60, max=600),
    retry=retry_if_exception_type(
        (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError)
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True,
)
def fetch_post_and_top_comments(
    permalink: str, max_comments: int
) -> tuple[RedditItem, list[RedditItem]]:
    url = f"https://www.reddit.com{permalink}.json"
    with httpx.Client(headers=_headers(), timeout=25.0) as client:
        r = client.get(url, params={"limit": max_comments, "sort": "top"})
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
        body=post_d.get("selftext") or "",
        score=int(post_d.get("score") or 0),
        num_comments=int(post_d.get("num_comments") or 0),
        created_utc=int(post_d.get("created_utc") or 0),
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
                score=int(cd.get("score") or 0),
                num_comments=0,
                created_utc=int(cd.get("created_utc") or 0),
            )
        )

    # polite pacing
    time.sleep(3.0)
    return post, comments
