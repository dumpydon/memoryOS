# MemoryOS

MemoryOS is an explainable long-term memory layer for AI agents. It decides which interaction details are worth remembering, classifies them as preference/semantic/episodic/procedural, preserves superseded history, and recalls memories with a transparent score that combines similarity, importance, recency, reinforcement, and confidence.

It is a portfolio-sized engineering system, not a chatbot. The Next.js dashboard shows the memory lifecycle and Recall Lab exposes why a result moved. FastAPI, PostgreSQL/pgvector, LangGraph, REST, and MCP share one Python service layer.

## What to explore

- **Overview** — live counts, memory type composition, disputes, reinforcement, and recent events.
- **Memory Explorer** — search/filter active and historical memories.
- **Memory detail** — immutable lineage versions, evidence, and audit timeline.
- **Ingestion Playground** — demo fixture scenarios, preview/commit behavior, structured candidates, policy decisions, and node timings.
- **Recall Lab** — a fair comparison between naive cosine retrieval and MemoryOS ranking with component contributions.
- **MCP** — `remember`, `recall`, `forget`, and `list_memories` over the same services as REST.

## Five-minute local start

Requirements: Python 3.12, uv, Node 22, pnpm 11.19, and Docker with a PostgreSQL/pgvector image.

First time, from the repository root:

```bash
cp .env.example .env
pnpm setup
```

For normal daily development:

```bash
pnpm dev
```

This starts the existing PostgreSQL/pgvector service, applies pending migrations, and runs FastAPI
and Next.js together with `[db]`, `[api]`, and `[web]` log prefixes. Open
[http://127.0.0.1:3000](http://127.0.0.1:3000). Demo mode uses authored deterministic fixture providers
and requires no OpenAI key. Copy `apps/web/.env.example` only when the API runs at a non-default origin.

Press `Ctrl-C` to stop the API and web processes; PostgreSQL stays running for faster restarts. To
stop PostgreSQL without deleting its volume, run:

```bash
pnpm dev:stop
```

`pnpm setup` installs the web and API dependencies, starts PostgreSQL, applies migrations, and seeds
the idempotent demo fixtures. It is intended for first-time setup or after dependency changes; the
daily `pnpm dev` command does not reinstall dependencies or reseed data.

### Advanced / manual startup

For debugging each service separately, use the underlying commands:

```bash
docker compose up -d postgres
cd apps/api
uv run --no-sync alembic upgrade head
uv run --no-sync uvicorn memoryos.main:app --reload --host 0.0.0.0 --port 8000
```

In another terminal:

```bash
pnpm --dir apps/web dev
```

## API and MCP

The REST API is versioned under `/v1`:

| Surface                         | Purpose                                        |
| ------------------------------- | ---------------------------------------------- |
| `POST /v1/interactions`         | Preview or commit one interaction              |
| `GET /v1/memories`              | Explore scoped memories                        |
| `GET /v1/memories/{id}/history` | Read immutable versions/events                 |
| `POST /v1/recall`               | Explainable MemoryOS retrieval                 |
| `POST /v1/recall/compare`       | Same-snapshot naive vs MemoryOS ranking        |
| `POST /v1/memories/{id}/forget` | Soft-forget a lineage while preserving history |
| `GET /v1/overview`              | Dashboard metrics and recent events            |
| `GET /v1/demo/scenarios`        | Finite public fixture catalog                  |

Run the local MCP stdio server from `apps/api`:

```bash
OWNER_API_TOKEN=memoryos-local-token uv run memoryos-mcp
```

The deployed Streamable HTTP endpoint is `/mcp`. Public demo access is limited to the fixed demo scope and allowlisted scenarios/queries. Mutations, arbitrary input, live mode, and the private live scope require the owner token.

## Architecture and policy

Read [docs/architecture.md](docs/architecture.md) for the service boundaries and graph. The core recall policy is:

```text
score = 0.55 similarity + 0.15 importance + 0.10 recency
        + 0.10 reinforcement + 0.10 confidence
```

Half-lives start at 180 days for preferences, 365 for semantic facts, 30 for episodic memories, and 180 for procedures. Confidence is a bounded heuristic evidence-strength score, not a calibrated probability. Forgetting is a soft lineage state; it preserves audit history and is not privacy erasure.

## Tests and checks

```bash
cd apps/api
uv run ruff check src tests
uv run mypy src
uv run pytest -q

cd ../..
pnpm --dir apps/web lint
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
```

The PostgreSQL integration tests use `TEST_DATABASE_URL` when supplied. CI starts a pgvector PostgreSQL 17 service and sets that variable, so database tests do not silently skip there. OpenAPI is exported from the FastAPI app and TypeScript types are generated with `openapi-typescript`; the generated files are checked for drift.

## Free-tier deployment

Use Vercel for the frontend, Render Free for the Dockerized API/MCP service, and Neon for PostgreSQL/pgvector. Follow [docs/deployment.md](docs/deployment.md) for Neon TLS configuration, one-time migrations/seed, Render environment variables, Vercel `NEXT_PUBLIC_API_BASE_URL`, and CORS.

The repository does not claim a completed cloud deployment or verified live model calls without a provider key. Render cold starts and provider costs are expected; demo mode keeps the public walkthrough deterministic and no-key.
