from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from jp_digest.connectors.reddit import fetch_post_and_top_comments, search_posts
from jp_digest.core.config import load_config
from jp_digest.core.queries import expand_queries
from jp_digest.services.digest import build_weekly_digest
from jp_digest.services.extraction import extract_for_new_content
from jp_digest.services.grounding import ground_experiences
from jp_digest.storage.db import session_scope
from jp_digest.storage.models import ContentItem


def cmd_ingest(cfg_path: str) -> None:
    cfg = load_config(cfg_path)
    added = 0
    skipped_comments = 0
    skipped_existing_posts = 0
    time_filters = cfg.reddit.time_filters or [cfg.reddit.time_filter]

    total_queries = sum(
        len(list(expand_queries(base))) * len(time_filters) for base in cfg.trip.bases
    ) * len(cfg.reddit.subreddits)

    query_count = 0

    with session_scope() as s:
        for sr in cfg.reddit.subreddits:
            for base in cfg.trip.bases:
                for q in expand_queries(base):
                    for t in time_filters:
                        query_count += 1
                        print(
                            f"\n[{query_count}/{total_queries}] Searching r/{sr} for: '{q}' (time={t})"
                        )

                        hits = search_posts(
                            sr,
                            q,
                            t,
                            cfg.reddit.limit_per_query,
                            pages=cfg.reddit.search_pages,
                            sort=cfg.reddit.sort,
                            pause_seconds=cfg.reddit.pause_seconds,
                        )
                        print(f"  OK: Found {len(hits)} posts")

                        for idx, h in enumerate(hits, 1):
                            if h.get("kind") != "t3":
                                continue
                            d = h["data"]
                            post_id = d.get("id")
                            permalink = d.get("permalink")
                            if not permalink or not post_id:
                                continue

                            # Check if this post already exists before fetching comments
                            post_source_id = f"t3_{post_id}"
                            existing_post = s.execute(
                                select(ContentItem).where(
                                    ContentItem.source == "reddit",
                                    ContentItem.source_id == post_source_id,
                                )
                            ).scalar_one_or_none()

                            if existing_post:
                                skipped_existing_posts += 1
                                print(
                                    f"  [{idx}/{len(hits)}] SKIP: Already have {permalink}"
                                )
                                continue

                            print(f"  [{idx}/{len(hits)}] Fetching: {permalink}")

                            post, comments = fetch_post_and_top_comments(
                                permalink,
                                max_comments=cfg.reddit.max_comments_per_post,
                                pause_seconds=cfg.reddit.pause_seconds,
                            )

                            new_items = 0
                            for item in [post, *comments]:
                                # Filter low-quality comments based on config
                                if item.kind == "comment":
                                    if len(item.body) < cfg.reddit.min_comment_length:
                                        skipped_comments += 1
                                        continue

                                    if item.score < cfg.reddit.min_comment_score:
                                        skipped_comments += 1
                                        continue

                                # Double-check individual items (comments might still be new)
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
                                        raw_json=json.dumps(item.raw, ensure_ascii=True),
                                        score=item.score,
                                        num_comments=item.num_comments,
                                        created_utc=item.created_utc,
                                    )
                                )
                                new_items += 1
                                added += 1

                            # Commit after each post to save progress incrementally
                            s.commit()
                            if new_items > 0:
                                print(
                                    f"  OK: Saved {new_items} new items (total: {added})"
                                )
                            else:
                                print("  OK: No new items from this post")

    print("\nOK: Ingestion complete")
    print(f"   Added {added} new content items.")
    if skipped_existing_posts > 0:
        print(
            f"   Skipped {skipped_existing_posts} posts already in database (saved time)."
        )
    if skipped_comments > 0:
        print(f"   Filtered out {skipped_comments} low-quality comments.")


def cmd_extract(cfg_path: str, reextract_all: bool = False) -> None:
    print("Starting mention extraction...")
    cfg = load_config(cfg_path)
    n = extract_for_new_content(cfg, limit=140, reextract_all=reextract_all)
    print(f"OK: Extraction complete. Extracted {n} mentions.")


def cmd_ground(cfg_path: str) -> None:
    print("Starting base gating + clustering...")
    cfg = load_config(cfg_path)
    n = ground_experiences(cfg, limit_mentions=500)
    print(f"OK: Clustering complete. Created {n} clusters.")


def cmd_digest(cfg_path: str, out: str | None) -> None:
    print("Starting digest build...")
    cfg = load_config(cfg_path)
    md = build_weekly_digest(cfg)
    if out:
        Path(out).write_text(md, encoding="utf-8")
        print(f"OK: Digest written to: {out}")
    else:
        print("\n" + "=" * 80)
        print(md)
        print("=" * 80)


def main() -> None:
    ap = argparse.ArgumentParser(prog="jp-digest")
    ap.add_argument("--config", default="trip.yaml")

    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ingest")
    p_extract = sub.add_parser("extract")
    p_extract.add_argument(
        "--reextract-all",
        action="store_true",
        help="Re-extract mentions for all content items.",
    )
    sub.add_parser("ground")

    p = sub.add_parser("digest")
    p.add_argument("--out", default=None)

    args = ap.parse_args()

    if args.cmd == "ingest":
        cmd_ingest(args.config)
    elif args.cmd == "extract":
        cmd_extract(args.config, reextract_all=args.reextract_all)
    elif args.cmd == "ground":
        cmd_ground(args.config)
    elif args.cmd == "digest":
        cmd_digest(args.config, args.out)
    else:
        raise SystemExit(f"Unknown cmd: {args.cmd}")
