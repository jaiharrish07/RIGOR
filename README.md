# RIGOR

**R**eproducibility **I**nspector for **G**rounded **O**pen **R**esearch — a web-based tool that audits ML research papers for reproducibility gaps using LLMs and grounded evidence extraction.

## What RIGOR does

Upload a research paper PDF. RIGOR parses it, then runs a 25-item reproducibility checklist against it using an LLM. Every finding is grounded in a verifiable quote from the paper itself — no hallucinated claims. Results include: which hyperparameters are reported, whether code is available, whether the paper cites any retracted work, and more.

## Team

- **Jaiharrish** ([@jaiharrish07](https://github.com/jaiharrish07)) — Backend, API, parsing pipeline
- **Lokesh** — Database, frontend, external integrations
- **Mohandoss** — LLM audit engine, checklist, evaluation harness

## Tech stack

- **Backend:** Python 3.11+, FastAPI, SQLAlchemy 2.0, Alembic
- **Database:** PostgreSQL 17 (via Docker Compose)
- **PDF parsing:** GROBID (containerized)
- **LLM:** Groq (Llama 3.3 70B), fallback OpenRouter
- **Frontend:** React + TypeScript (Week 2+)
- **Orchestration:** Docker Compose

## Getting started

Prerequisites: Python 3.11+, Docker Desktop, Git, Groq API key.

```bash
# 1. Clone
git clone https://github.com/jaiharrish07/RIGOR.git
cd RIGOR

# 2. Set up environment
cp .env.example .env
# Edit .env — paste your Groq API key

# 3. Start supporting services (Postgres + GROBID)
docker compose up -d

# 4. Set up Python
python -m venv .venv
.venv\Scripts\activate       # Windows
# source .venv/bin/activate  # Mac / Linux
pip install -e .

# 5. Run database migrations
alembic upgrade head

# 6. Start the backend
uvicorn app.main:app --reload

# Open http://localhost:8000/docs
```

## Documentation

- [Database schema](docs/database_schema.md) — the 5-table data model
- [API contract](docs/api_contract.md) — HTTP endpoint specification
- [Database setup](docs/database_setup.md) — bringing up Postgres, migrations, and rollback

## Project status

**Week 1** — Backend foundation, database, PDF upload + parse endpoint. In progress.

## License

TBD.
