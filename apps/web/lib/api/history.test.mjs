import assert from "node:assert/strict";
import test from "node:test";

import { compareLifecycleEvents, sourceEvidence } from "./history.ts";

test("backdated consolidation evidence cannot appear before the source was created", () => {
  const created = {
    id: "source-created",
    event_type: "created",
    created_at: "2026-09-30T10:00:00Z",
    source_occurred_at: null,
    after: { reinforcement_count: 0 },
  };
  const retired = {
    id: "source-retired",
    event_type: "superseded",
    created_at: "2026-09-30T10:01:00Z",
    source_occurred_at: "2026-09-30T09:00:00Z",
    after: { status: "superseded" },
  };
  assert.deepEqual([retired, created].sort(compareLifecycleEvents), [
    created,
    retired,
  ]);
  assert.equal(retired.source_occurred_at, "2026-09-30T09:00:00Z");
});

test("seed events sharing a transaction timestamp preserve creation and confirmation order", () => {
  const created_at = "2026-09-30T10:00:00Z";
  const events = [
    {
      id: "a",
      event_type: "reinforced",
      created_at,
      after: { reinforcement_count: 2 },
    },
    {
      id: "z",
      event_type: "created",
      created_at,
      after: { reinforcement_count: 0 },
    },
    {
      id: "b",
      event_type: "reinforced",
      created_at,
      after: { reinforcement_count: 1 },
    },
  ];
  assert.deepEqual(
    events.sort(compareLifecycleEvents).map((event) => event.id),
    ["z", "b", "a"],
  );
});

test("review shows the correction that established memory A and excludes later or retirement evidence", () => {
  const correction = {
    event_type: "superseded",
    reason_code: "explicit_replacement",
    created_at: "2026-09-30T10:00:00Z",
    evidence_excerpt:
      "I switched from concise to detailed DSA explanations. From now on, I prefer detailed explanations.",
  };
  const events = [
    correction,
    {
      ...correction,
      reason_code: "consolidation_source_preserved",
      created_at: "2026-09-30T10:01:00Z",
      evidence_excerpt: "A separate retirement operation.",
    },
    {
      ...correction,
      event_type: "reinforced",
      created_at: "2026-09-30T10:03:00Z",
      evidence_excerpt: "Evidence received after the review.",
    },
  ];
  assert.equal(sourceEvidence(events, "2026-09-30T10:02:00Z"), correction);
});
