import assert from "node:assert/strict";
import test from "node:test";
import { QueryClient, QueryObserver } from "@tanstack/react-query";

import { refreshIngestionCaches, refreshMemoryViews } from "./cache.ts";

function freshClient() {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 15_000, retry: false } },
  });
}

test("consolidation refreshes secondary source details and an active recall result", async () => {
  const client = freshClient();
  const sourceKey = ["memory", "scope", "source-b"];
  const historyKey = ["memory-history", "scope", "source-b"];
  const recallKey = ["recall-compare", "scope", "demo", "DSA"];
  client.setQueryData(sourceKey, { status: "active" });
  client.setQueryData(historyKey, { events: ["created"] });
  client.setQueryData(recallKey, { ids: ["source-a", "source-b"] });
  const sourceObserver = new QueryObserver(client, {
    queryKey: sourceKey,
    queryFn: async () => ({ status: "superseded" }),
  });
  const recallObserver = new QueryObserver(client, {
    queryKey: recallKey,
    queryFn: async () => ({ ids: ["canonical"] }),
  });
  const offSource = sourceObserver.subscribe(() => {});
  const offRecall = recallObserver.subscribe(() => {});
  try {
    await refreshIngestionCaches(client, {
      status: "completed",
      memory_ids: ["canonical"],
      decisions: [
        {
          decision_type: "consolidated",
          memory_id: "canonical",
          related_memory_id: "source-a",
          source_memory_ids: ["source-a", "source-b"],
        },
      ],
    });
    assert.equal(client.getQueryData(sourceKey).status, "superseded");
    assert.deepEqual(client.getQueryData(recallKey).ids, ["canonical"]);
    assert.equal(client.getQueryState(historyKey).isInvalidated, true);
  } finally {
    offSource();
    offRecall();
    client.clear();
  }
});

test("forgetting refreshes recall and invalidates every version's inspection cache", async () => {
  const client = freshClient();
  const oldVersionKey = ["memory", "scope", "older-version"];
  const oldHistoryKey = ["memory-history", "scope", "older-version"];
  const recallKey = ["recall-compare", "scope", "demo", "preference"];
  client.setQueryData(oldVersionKey, { status: "superseded" });
  client.setQueryData(oldHistoryKey, { events: ["created"] });
  client.setQueryData(recallKey, { ids: ["current-version"] });
  const observer = new QueryObserver(client, {
    queryKey: recallKey,
    queryFn: async () => ({ ids: [] }),
  });
  const off = observer.subscribe(() => {});
  try {
    await refreshMemoryViews(client);
    assert.deepEqual(client.getQueryData(recallKey).ids, []);
    assert.equal(client.getQueryState(oldVersionKey).isInvalidated, true);
    assert.equal(client.getQueryState(oldHistoryKey).isInvalidated, true);
  } finally {
    off();
    client.clear();
  }
});

test("preview and rejected admission do not refresh memory or recall views", async () => {
  const client = freshClient();
  const key = ["recall-compare", "scope", "demo", "DSA"];
  client.setQueryData(key, { ids: ["current"] });
  try {
    await refreshIngestionCaches(client, {
      status: "preview",
      decisions: [{ decision_type: "created" }],
    });
    await refreshIngestionCaches(client, {
      status: "completed",
      decisions: [{ decision_type: "skipped" }],
    });
    assert.equal(client.getQueryState(key).isInvalidated, false);
  } finally {
    client.clear();
  }
});
