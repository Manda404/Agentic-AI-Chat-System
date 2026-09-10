.PHONY: install install-backend install-frontend backend frontend dev run stop test eval-retrieval

install: install-backend install-frontend

install-backend:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

install-frontend:
	cd frontend && npm install

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev: run

run:
	python3 scripts/dev.py run

stop:
	python3 scripts/dev.py stop

test:
	python3 -m unittest discover -s scripts/tests
	cd backend && .venv/bin/python -m unittest discover -s tests

# Retrieval Precision/Recall/MRR/NDCG benchmark (see docs/EVALUATION.md).
# Requires a valid MONGODB_URI and the ingested sample dataset
# (POST /ingest/sample-data).
eval-retrieval:
	cd backend && .venv/bin/python -m app.evaluation.retrieval_benchmark --verbose
