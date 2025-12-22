from __future__ import annotations

import re


_STOP_TOKENS = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "at",
    "to",
    "for",
    "and",
    "station",
    "city",
    "prefecture",
    "district",
    "ward",
}


def normalize(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[\(\)\[\]\{\}]", " ", s)
    s = re.sub(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokens(s: str) -> list[str]:
    s = normalize(s)
    parts = re.split(r"[\s\-]+", s)
    out = []
    for p in parts:
        if len(p) < 2:
            continue
        if p in _STOP_TOKENS:
            continue
        out.append(p)
    return out


def mention_matches_candidate(
    mention: str, candidate_name: str | None, candidate_display: str | None
) -> bool:
    """
    Require that most meaningful mention tokens appear in the candidate name/address.
    This prevents 'Dotonbori, Kyoto' -> random Kyoto feature
    """
    m_tokens = tokens(mention)
    if not m_tokens:
        return False

    hay = normalize((candidate_name or "") + " " + (candidate_display or ""))
    hit = 0
    for t in m_tokens:
        if t in hay:
            hit += 1

    # require at least 60% token coverage, and at least 1 token
    return hit >= max(1, int(0.6 * len(m_tokens)))
