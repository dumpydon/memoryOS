# MemoryOS

MemoryOS is a small, explainable long-term memory layer for AI agents. It decides which facts are worth remembering, tracks preference/semantic/episodic/procedural memories, preserves superseded history, and recalls memories with a transparent score instead of vector similarity alone.

The repository is intentionally split into a Next.js engineering dashboard and a Python service. Both REST and MCP call the same Python business services. The public demo uses recorded provider outputs and real policy/ranking execution so it does not require an LLM key.

## Repository map

- `apps/api`: FastAPI, Pydantic contracts, LangGraph orchestration, persistence adapters, and MCP tools.
- `apps/web`: Next.js App Router dashboard.
- `contracts`: API and domain contract notes shared by workers.
- `docs`: architecture, policy, and deployment notes.
- `fixtures`: demo interactions and evaluation cases.

## Local start

1. Copy `.env.example` to `.env`.
2. Start PostgreSQL/pgvector with `docker compose up -d postgres`.
3. Install Python dependencies with `uv sync` from `apps/api` (or `python -m pip install -e '.[dev]'`).
4. Apply migrations with `alembic upgrade head` from `apps/api` once migrations exist.
5. Start the API with `uv run uvicorn memoryos.main:app --reload --port 8000`.
6. In another terminal, run `pnpm --dir apps/web install` and `pnpm --dir apps/web dev`.

Demo mode is the default and does not call OpenAI. Live mode requires `OPENAI_API_KEY` and should be enabled deliberately.

## Design boundary

The model proposes candidate memories and relationships. Deterministic domain policies validate those proposals, calculate decay/ranking, and persist an auditable event. Read `docs/contracts.md` before changing shared request/response shapes.

