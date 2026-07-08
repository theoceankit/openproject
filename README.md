# OpenProject

AI assistant for product and project managers (working title). Connects to your project
documentation and answers questions grounded in the actual sources, with citations back to the
documents they came from.

**Current stage:** Stage 1, project documentation ingestion, memory, and chat. See
[`documentation/docs/product-vision/mvp-scope.mdx`](documentation/docs/product-vision/mvp-scope.mdx)
for the full roadmap.

## Prerequisites

- Python 3.12+ (developed against 3.14)
- Node.js 20+
- Docker (for Postgres with the pgvector extension)
- [Ollama](https://ollama.com/) (runs the LLM and embedding models locally, started separately)

## Quick start

### 1. Start Postgres

```bash
docker compose up -d
```

### 2. Pull the models

```bash
ollama pull qwen2.5:14b-instruct
ollama pull bge-m3
```

### 3. Set up and start the backend

```bash
cd backend
python3 -m venv .venv                        # first time only
.venv/bin/pip install -e .                   # install dependencies
.venv/bin/alembic upgrade head               # apply DB migrations
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1
```

The backend starts at `http://localhost:8000`. Copy `backend/.env.example` to `backend/.env` to
configure it; the defaults point at the Postgres instance above and a local Ollama instance.

> The `--host 127.0.0.1` flag keeps the backend local-only. The default CORS policy (`*`) is
> safe only when the backend is not reachable from the network.

### 4. Start the chat UI

```bash
cd frontend
npm install   # first time only
npm start
```

`npm start` builds the CSS first (via `prestart`), then opens the Electron chat window. Drag a
file or folder onto the window, or click the "+" button, to connect documents. Ask questions in
the chat input; answers are grounded in the connected documents with source citations.

### 5. Verify the backend

```bash
curl http://localhost:8000/health/model
```

This checks that the backend can reach Ollama and that both models are loaded.

## Repository layout

```
backend/            Python/FastAPI backend (Stage 1)
frontend/           Electron chat UI (Stage 1)
documentation/      Docusaurus documentation site
docker-compose.yml  Postgres + pgvector for local development
```

## Documentation

The `documentation/` directory is a [Docusaurus](https://docusaurus.io/) site covering the
product vision, architecture, reference, and contributing guides. To run it locally:

```bash
cd documentation
npm install   # first time only
npm start     # http://localhost:3000
```

## Running the backend tests

```bash
cd backend
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## Architecture (Stage 1)

- **Backend** (FastAPI + Python): document ingestion, LLM-based entity extraction, vector
  similarity retrieval via pgvector, and a chat endpoint. Configuration via `OPENPROJECT_*`
  environment variables (see `backend/.env.example`).
- **Frontend** (Electron): chat UI with document attachment, project resolution cards, and
  fact confirmation cards. No bundler or packaging yet.
- **Database** (Postgres + pgvector): stores documents, chunks, embeddings, and extracted
  entities.
- **Model runtime** (Ollama): LLM (`qwen2.5:14b-instruct` by default) and embedding model
  (`bge-m3` by default), run separately from the backend.

See [`documentation/docs/architecture/`](documentation/docs/architecture/) for the full
architecture documentation.

## Known limitations (Stage 1)

- Chat retrieval searches the whole document corpus, not scoped to a specific project.
- The frontend loads the Material Symbols icon font from Google Fonts CDN. Geist and JetBrains
  Mono fonts are self-hosted in `frontend/src/fonts/`.
- The orchestration layer (`backend/app/orchestration/`) is a foundation for future stages and
  is not used by any Stage 1 pipeline.
- The frontend has no packaging or process management yet; the backend is started separately.
