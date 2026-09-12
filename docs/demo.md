# MemoryOS demo walkthrough

The public demo is designed to be useful without an OpenAI key. It uses authored fixture candidates, relationships, and deterministic `demo-fixture-v1` vectors, then runs the same persistence and recall policies used by live mode. The demo catalog is finite so arbitrary public input never silently triggers paid inference.

## Prepare the local demo

From the repository root, run the first-time setup once:

```bash
cp .env.example .env
pnpm run setup
```

Then start the daily development environment from one terminal:

```bash
pnpm dev
```

Open `http://127.0.0.1:3000`. If the API is waking or not started, the dashboard shows an actionable API state instead of fake metrics. See the README's advanced section for manual per-service startup when debugging.

## Suggested walkthrough

1. **Overview** — inspect the seeded type counts, recent events, disputed memories, and reinforcement activity.
2. **Memory Explorer** — filter by type/status, search content, and open a memory’s lineage.
3. **Memory detail** — read immutable versions and event reasons. Add an owner token in Settings before using forget or dispute resolution.
4. **Ingestion Playground** — choose a demo fixture scenario, run Preview, and inspect extracted candidates, policy decisions, and actual graph timings. Preview does not mutate the database.
5. **Recall Lab** — choose a demo fixture query and expand both rankings. The bars expose each API-returned contribution; the UI does not recalculate business ranking.
6. **Memory Review** — compare the seeded retention-policy conflict, inspect why automation paused, and see the available audited owner actions without changing data.
7. **How it works** — use the one-minute walkthrough to connect ingestion decisions, immutable history, and hybrid recall.

The catalog includes examples of a preference, a procedural runbook, reinforcement, a superseded preference, a disputed conflict, a stale episodic item, a skipped greeting, and a high-similarity comparison case. These are curated demonstrations of behavior, not a claim that MemoryOS universally beats cosine similarity.

## Live mode

Enter the owner token in Settings and switch to Live scope. Live ingestion and arbitrary recall use the configured OpenAI provider and the private scope. `OPENAI_API_KEY` is optional in demo mode and must never be placed in the web app environment.

Live model calls have not been verified in this repository without a provider key. The demo is the reproducible, no-key path; live mode is an explicit integration path with provider timeouts and bounded structured outputs.

## MCP smoke test

The MCP server exposes `remember`, `recall`, `forget`, and `list_memories` through the same services. Local stdio can be started with:

```bash
cd apps/api
OWNER_API_TOKEN=memoryos-local-token uv run memoryos-mcp
```

The deployed HTTP endpoint is `/mcp` on the FastAPI service. Use the owner token for mutations or private scopes. Public demo calls must use an allowlisted scenario/query and the demo scope.
