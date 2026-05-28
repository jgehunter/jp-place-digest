# jp-place-digest

> ⚠️ **MOTHBALLED** — This project is paused and not under active development as of 2026-05-28.
>
> The code remains for reference. Issues and PRs may not be addressed.

A weekly digest pipeline that surfaces grounded travel points-of-interest from Reddit.

**Pipeline stages** (see `Makefile`):
1. `ingest` — pull Reddit posts matching trip-config queries (`trip.yaml`)
2. `extract` — LLM (OpenAI) extracts candidate POIs from post text
3. `ground` — fuzzy dedupe + grounding against a places database (RapidFuzz)
4. `digest` — emit a ranked weekly markdown digest

**Stack**

- Python 3.11+, CLI entry point `jp-digest` (defined in `src/jp_digest/cli.py`)
- Pydantic / Pydantic Settings for config
- SQLAlchemy 2.0 + Alembic migrations on PostgreSQL (via psycopg)
- OpenAI for LLM extraction
- Docker Compose for the local DB (`make up` / `make down`)
- uv for env management

Sample outputs preserved in `digest_full.md` (Japan/Shikoku, 2025-12-25) and `digest_additions.md` (Tokyo, 2026-04-04).
