# LiveQuiz Makefile. All backend ops run inside the api-a container.

.PHONY: up down logs migrate seed db-reset clickhouse-migrate test lint typecheck load-test redpanda-reset

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose exec api-a alembic upgrade head

seed:
	docker compose exec api-a python -m app.db.seed

db-reset:
	docker compose down -v
	docker compose up -d postgres redis
	docker compose up -d --build api-a api-b
	docker compose exec api-a alembic upgrade head
	docker compose exec api-a python -m app.db.seed

clickhouse-migrate:
	docker compose exec -T clickhouse clickhouse-client --multiquery < migrations/clickhouse/001_events.sql

test:
	docker compose exec api-a pytest -q

lint:
	docker compose exec api-a ruff check .

typecheck:
	docker compose exec api-a mypy app

load-test:
	python scripts/load-test-rooms.py

redpanda-reset:
	docker compose exec redpanda rpk topic delete livequiz.events.room livequiz.events.match livequiz.events.answer livequiz.events.moderation livequiz.events.dead_letter || true
	bash ops/scripts/create-redpanda-topics.sh
