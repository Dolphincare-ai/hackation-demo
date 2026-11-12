PY := .venv/Scripts/python

setup:
	python -m venv .venv
	$(PY) -m pip install -r backend/requirements.txt
	cd frontend && npm install

seed:
	$(PY) scripts/seed.py

dev:
	cd backend && ../$(PY) -m uvicorn app.main:app --port 8000 --reload & cd frontend && npm run dev

test:
	cd backend && ../$(PY) -m pytest -q
