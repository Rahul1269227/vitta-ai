.PHONY: install install-dev setup-first-time run-regular run runserver dev test lint sample classify train-ml migrate sync db-upgrade db-downgrade db-revision

install:
	uv sync

install-dev:
	uv sync --dev --extra ocr

setup-first-time:
	bash scripts/setup_first_time.sh

run-regular:
	bash scripts/run_regular.sh

runserver:
	uv run uvicorn sentinelfi.main:app --reload --host 0.0.0.0 --port 8000

run: runserver

dev:
	uv run python scripts/run_frontend_dev.py

test:
	uv run pytest -q

lint:
	uv run ruff check src tests scripts

sample:
	uv run python scripts/run_sample_audit.py

classify:
	uv run python scripts/evaluate_bge_m3.py --input data/upi_classifier_eval.csv

train-ml:
	uv run python scripts/train_ml_classifier.py

db-upgrade:
	uv run alembic upgrade head

migrate: db-upgrade

sync:
	git fetch origin main
	git merge --ff-only origin/main

db-downgrade:
	uv run alembic downgrade -1

db-revision:
	uv run alembic revision --autogenerate -m "$(m)"
