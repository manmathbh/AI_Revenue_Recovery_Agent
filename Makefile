.PHONY: dev batch seed load evaluate test lint typecheck demo-reset replay

# Local development against a running PostgreSQL (docker compose up -d postgres).
dev:
	uvicorn app.main:app --reload --port 8000

worker:
	python -m app.worker

# Generate the frozen 120-case dataset (seed 42) into data/.
seed:
	python scripts/generate_dataset.py --seed 42 --size 120 --out data/dataset_v1.jsonl

# Load the dataset into the DB (ingest only; dedupe exercised).
load: seed
	python scripts/load_dataset.py

# Full deterministic evaluation: load + pipeline + report.
batch:
	python scripts/load_dataset.py
	python scripts/batch.py --seed 42

# Show the most recent stored evaluation report.
evaluate:
	python scripts/evaluate.py

# Replay one webhook delivery N times (Demo 4 duplicate-attack).
replay:
	python scripts/replay_webhook.py --case S09-001 --times 3

# Live recovered-revenue ticker (Demo 1).
watch:
	python scripts/watch.py --db

test:
	pytest -q

lint:
	ruff check app scripts tests

typecheck:
	mypy app

demo-reset:
	python scripts/demo_reset.py