# Live memory intelligence

MemoryOS keeps two separate scopes: the authored public demo and private live memory.
Demo vectors never participate in live retrieval. Both modes use the same deterministic
mutation and ranking policies.

## Enable live mode

1. Add `OPENAI_API_KEY` to the repository `.env` (API server only).
2. Choose a structured-output-capable `OPENAI_MODEL` and an `EMBEDDING_MODEL`.
   The database uses 1536-dimensional vectors; keep `EMBEDDING_DIMENSIONS=1536`.
3. Run `pnpm run setup` on a new checkout, or restart `pnpm dev` after changing server settings.
4. In **Settings**, enter your `OWNER_API_TOKEN` and select **Live scope**.
5. Open **Ingestion playground**. Preview an arbitrary interaction, inspect the extracted
   candidates and decisions, then commit it to persist the result.

No OpenAI key is needed for the demo. Without a key, live operations report that the server
needs configuration; they never substitute fixture inference for arbitrary text. The
capabilities endpoint reports configuration readiness, not a successful remote API handshake.
Keys belong only on the server, never in `NEXT_PUBLIC_*` variables or browser storage.

Changing the embedding model does not automatically re-embed existing live memories. Use a
scope with a compatible model or perform an explicit migration; mixing vector spaces would
make similarity scores meaningless.

## Try a memory lifecycle

- New: “I prefer concise Python explanations.”
- Reinforcement: “Python examples are still what I prefer.”
- Supersession: “I used to prefer Python examples, but use TypeScript examples from now on.”
- Separate contexts: “I use Python for interviews but TypeScript at work.”
- An unclear conflicting statement should produce a reviewable decision rather than silently
  replacing the current memory.

The provider extracts atomic facts and proposes relationships through Pydantic structured
outputs. Python checks scope, source evidence, confidence, matching identity/context, and
temporal support before performing an atomic transaction. Model output is never executable
database instructions. See the [OpenAI structured outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Memory Review

Review shows the candidate, current memory, evidence, proposed relationship, confidence, and
the reason automatic resolution was withheld. Owners can keep both, use the new memory,
keep the existing memory, or mark the candidate invalid. Resolutions are recorded in history;
they do not erase the original interaction or memory versions. Public demo visitors can
inspect reviews, while mutations require an owner token.

Consolidation starts as an explicit proposal from three to eight source memories. It is
conservative and reviewable. Approval creates a linked memory and preserves the source
memories; it is not automatic compression or deletion. Unsupported combinations are refused.

## Explainability and recall

Stored memory details expose deterministic reasons derived from recorded decisions and
evidence. Recall returns semantic relevance, importance, recency, reinforcement, confidence,
and their weighted contributions. The explanation does not use another LLM call.

Recall Lab compares vector-only and MemoryOS ranking over the same eligible candidate set,
query embedding, relevance floor, and evaluation time. Superseded and forgotten memories
remain in history but are excluded from normal recall. Different contexts can coexist, so
the query should name the context it needs (for example, “Which language should interview
examples use?”).
