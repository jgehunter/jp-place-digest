from __future__ import annotations

from jp_digest.core.config import BaseCfg


def expand_queries(base: BaseCfg) -> list[str]:
    """
    Generate search queries for a base location.
    Includes explicit 'Japan' keyword to filter results when searching general subreddits.
    """
    base_terms = [base.name] + list(base.aliases)

    # Templates now include 'Japan' to filter results
    templates = [
        "{base} cafe",
        "{base} restaurant",
        "{base} food",
        "{base} hidden gems",
        "{base} things to do",
        "{base} day trip",
        "{base} trip report",
        "{base} where to eat",
    ]

    queries = set(q.strip() for q in base.queries if q.strip())

    for t in templates:
        for name in base_terms:
            name = name.strip()
            if not name:
                continue
            queries.add(t.format(base=name))

    return sorted(queries)
