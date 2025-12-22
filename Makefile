.PHONY: up down logs fmt lint migrate revision seed ingest extract ground digest

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f db

fmt:
	uv run ruff format .

lint:
	uv run ruff check .

revision:
	uv run alembic revision --autogenerate -m "$(m)"

migrate:
	uv run alembic upgrade head

ingest:
	uv run jp-digest ingest --config trip.yaml

extract:
	uv run jp-digest extract --config trip.yaml

ground:
	uv run jp-digest ground --config trip.yaml

digest:
	uv run jp-digest digest --config trip.yaml --out digest.md