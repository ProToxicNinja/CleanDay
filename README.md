# Plant Breeder Sim — Day 1

Minimal playable scaffold:
- FastAPI + SQLite
- Jinja2 + HTMX via CDN (no frontend build)
- Starter seeds → plant → tick → view greenhouse

## Quickstart (Local)
```bash
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install fastapi uvicorn jinja2 python-multipart pydantic itsdangerous
uvicorn app.main:app --reload --port 5000 --host 0.0.0.0
