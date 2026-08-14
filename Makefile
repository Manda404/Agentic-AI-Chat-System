.PHONY: install install-backend install-frontend backend frontend dev test eval-retrieval

install: install-backend install-frontend

install-backend:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

install-frontend:
	cd frontend && npm install

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 backend frontend

test:
	cd backend && .venv/bin/python -m unittest discover -s tests

# Benchmark Precision/Recall/MRR/NDCG du retrieval (voir docs/EVALUATION.md).
# Nécessite MONGODB_URI valide et le jeu de données d'exemple déjà ingéré
# (POST /ingest/sample-data).
eval-retrieval:
	cd backend && .venv/bin/python -m app.evaluation.retrieval_benchmark --verbose
