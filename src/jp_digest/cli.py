from __future__ import annotations

import argparse
from pathlib import Path
import time

from sqlalchemy import select

from jp_digest.connectors.reddit import fetch_post_and_top_comments, search_posts
from jp_digest.core.config import load_config
from jp_digest.services.extraction import extract_for_new_content
from jp_digest.services.digest import build_weekly_digest
from jp_digest.services.grounding import ground_experiences
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import ContentItem


def cmd_ingest(cfg_path: str) -> None:
    cfg = load_config(cfg_path)
    added = 0

    with session_scope() as s:
        for sr in cfg.reddit.subreddits:
            for base in cfg.trip.bases:
                for q in base.queries:
                    print(f"Searching {sr} for: {q}")
                    hits = search_posts(
                        sr,
                        q,
                        cfg.reddit.time_filter,
                        cfg.reddit.limit_per_query,
                    )
                    print(f"Found {len(hits)} posts")

                    for h in hits:
                        if h.get("kind") != "t3":
                            continue
                        d = h["data"]
                        permalink = d.get("permalink")
                        if not permalink:
                            continue

                        post, comments = fetch_post_and_top_comments(
                            permalink,
                            max_comments=cfg.reddit.max_comments_per_post,
                        )

                        for item in [post, *comments]:
                            exists = s.execute(
                                select(ContentItem).where(
                                    ContentItem.source == "reddit",
                                    ContentItem.source_id == item.source_id,
                                )
                            ).scalar_one_or_none()
                            if exists:
                                continue

                            s.add(
                                ContentItem(
                                    source="reddit",
                                    source_id=item.source_id,
                                    kind=item.kind,
                                    url=item.url,
                                    subreddit=item.subreddit,
                                    author=item.author,
                                    title=item.title,
                                    body=item.body,
                                    score=item.score,
                                    num_comments=item.num_comments,
                                    created_utc=item.created_utc,
                                )
                            )
                            added += 1

                        # Commit after each post to save progress incrementally
                        s.commit()
                        print(
                            f"✓ Saved post + {len(comments)} comments (total: {added})"
                        )

    print(f"Ingested {added} new content items.")


def cmd_extract() -> None:
    n = extract_for_new_content(limit=140)
    print(f"Extracted {n} experiences.")


def cmd_ground(cfg_path: str) -> None:
    cfg = load_config(cfg_path)
    n = ground_experiences(cfg, limit_experiences=500)
    print(f"Created {n} experience->POI links (and base assignments).")


def cmd_digest(cfg_path: str, out: str | None) -> None:
    cfg = load_config(cfg_path)
    md = build_weekly_digest(cfg)
    if out:
        Path(out).write_text(md, encoding="utf-8")
        print(f"Wrote digest to {out}")
    else:
        print(md)


def main() -> None:
    ap = argparse.ArgumentParser(prog="jp-digest")
    ap.add_argument("--config", default="trip.yaml")

    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ingest")
    sub.add_parser("extract")
    sub.add_parser("ground")

    p = sub.add_parser("digest")
    p.add_argument("--out", default=None)

    args = ap.parse_args()

    if args.cmd == "ingest":
        cmd_ingest(args.config)
    elif args.cmd == "extract":
        cmd_extract()
    elif args.cmd == "ground":
        cmd_ground(args.config)
    elif args.cmd == "digest":
        cmd_digest(args.config, args.out)
    else:
        raise SystemExit(f"Unknown cmd: {args.cmd}")
