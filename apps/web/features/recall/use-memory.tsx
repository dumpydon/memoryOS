"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowRight, ArrowUpRight, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import {
  ErrorState,
  InlineNotice,
  LoadingState,
} from "@/components/status-state";
import { TypeBadge } from "@/components/type-badge";
import { useWorkspace } from "@/components/workspace-context";
import { postRecallContext } from "@/lib/api/queries";
import { CorrectMemory } from "./correct-memory";

const demoRequest = "Explain binary search to me.";

export function RecallUseMemory({
  available,
  checking,
}: {
  available: boolean;
  checking: boolean;
}) {
  const { mode, scopeId, token, isOwner } = useWorkspace();
  const [query, setQuery] = useState(demoRequest);
  const [correctingId, setCorrectingId] = useState<string | null>(null);
  const [correctionNotice, setCorrectionNotice] = useState<string | null>(null);
  const generation = useMutation({
    mutationFn: () =>
      postRecallContext(
        { scope_id: scopeId, query: query.trim(), mode },
        token,
      ),
    retry: false,
  });
  const demoAllowed = query.trim().toLowerCase() === demoRequest.toLowerCase();
  const canGenerate =
    Boolean(query.trim()) &&
    !generation.isPending &&
    (mode === "demo" ? demoAllowed : isOwner && available && !checking);
  const result = generation.data;

  return (
    <>
      <section
        className="panel recall-query-panel"
        aria-label="Request with memory"
      >
        <div className="query-heading context-request-heading">
          <h2>Request</h2>
          <span className="context-mode-label">
            {mode === "demo"
              ? "Recorded demo · no AI calls"
              : "Live generation"}
          </span>
        </div>
        <form
          className="recall-query-form"
          onSubmit={(event) => {
            event.preventDefault();
            if (canGenerate) {
              setCorrectingId(null);
              setCorrectionNotice(null);
              generation.mutate();
            }
          }}
        >
          <div className="search-field">
            <input
              aria-label="Request with memory"
              value={query}
              disabled={generation.isPending}
              maxLength={2000}
              onChange={(event) => {
                setQuery(event.target.value);
                generation.reset();
                setCorrectingId(null);
                setCorrectionNotice(null);
              }}
            />
            <button
              className="search-submit"
              type="submit"
              disabled={!canGenerate}
            >
              {generation.isPending ? "Working…" : "Generate with memory"}{" "}
              <ArrowRight size={14} />
            </button>
          </div>
        </form>
        {mode === "demo" ? (
          <p className="context-request-note">
            Current memories are retrieved; the answer uses recorded demo text.
            {!demoAllowed ? (
              <button
                type="button"
                onClick={() => {
                  setQuery(demoRequest);
                  generation.reset();
                }}
              >
                Use binary search example
              </button>
            ) : null}
          </p>
        ) : (
          <p className="context-request-note">
            One response using your scope’s recalled memories. Generated only
            when you submit.
          </p>
        )}
      </section>

      {mode === "live" && (!isOwner || (!checking && !available)) ? (
        <InlineNotice tone="warning">
          <ShieldAlert size={15} />
          {!isOwner
            ? "Add an owner token in Settings to generate a live response."
            : "Configure OPENAI_API_KEY on the API server to generate a live response."}
        </InlineNotice>
      ) : null}
      {mode === "live" && checking ? (
        <LoadingState label="Checking live provider readiness" />
      ) : null}
      {generation.isPending ? (
        <LoadingState
          label={
            mode === "demo"
              ? "Retrieving current memories"
              : "Recalling memories and generating a response"
          }
        />
      ) : null}
      {generation.isError ? (
        <ErrorState
          error={generation.error}
          onRetry={() => generation.mutate()}
        />
      ) : null}

      {correctionNotice ? (
        <InlineNotice>{correctionNotice}</InlineNotice>
      ) : null}
      {correctingId ? (
        <CorrectMemory
          key={correctingId}
          memoryId={correctingId}
          onClose={() => setCorrectingId(null)}
          onCommitted={(response) => {
            generation.reset();
            setCorrectingId(null);
            setCorrectionNotice(
              response.decisions.some(
                (decision) => decision.decision_type === "disputed",
              )
                ? "Correction saved for Memory Review. Open the review inbox to resolve the conflict."
                : "Correction saved with its history. Generate again to use the updated memory state.",
            );
          }}
        />
      ) : null}

      {result ? (
        <div className="context-results">
          <section
            className="panel context-memories"
            aria-label="Memories supplied to response"
          >
            <h2>Memories supplied</h2>
            {result.memories_used.length ? (
              <ol>
                {result.memories_used.map((memory) => (
                  <li key={memory.id}>
                    <Link
                      href={`/memories/${memory.id}`}
                      title="View evidence and history"
                    >
                      <span className="context-memory-type">
                        <TypeBadge type={memory.memory_type} />
                        <ArrowUpRight size={13} aria-hidden="true" />
                      </span>
                      <strong>{memory.content}</strong>
                    </Link>
                    <button
                      className="context-correct-button"
                      type="button"
                      onClick={() => setCorrectingId(memory.id)}
                    >
                      Correct memory
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <p>
                No relevant current memories fit this request. The response
                receives no memory context.
              </p>
            )}
          </section>
          <section
            className="panel context-response"
            aria-label="Response with memory"
          >
            <div className="context-response-heading">
              <h2>Response</h2>
              <span className="demo-pill">
                {result.mode === "demo"
                  ? "Recorded demo"
                  : `Live · ${result.model}`}
              </span>
            </div>
            <div className="context-response-body">
              <ResponseText text={result.answer} />
            </div>
          </section>
        </div>
      ) : !generation.isPending && !generation.isError && !correctionNotice ? (
        <div className="panel recall-empty context-empty">
          <strong>See what remembered context changes</strong>
          <p>
            Submit a request to see the memories supplied and the resulting
            answer.
          </p>
        </div>
      ) : null}
    </>
  );
}

// Render prose and fenced code as escaped React text; no generated HTML is executed.
function ResponseText({ text }: { text: string }) {
  return text.split(/```[^\n]*\n([\s\S]*?)```/g).map((part, index) =>
    index % 2 ? (
      <pre key={index}>
        <code>{part.trimEnd()}</code>
      </pre>
    ) : (
      part
        .trim()
        .split(/\n\s*\n/)
        .filter(Boolean)
        .map((paragraph, paragraphIndex) => {
          const heading = paragraph.match(/^#{1,3}\s+([^\n]+)$/);
          const Block = heading ? "h3" : "p";
          return (
            <Block key={`${index}:${paragraphIndex}`}>
              {(heading ? heading[1] : paragraph)
                .split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
                .map((piece, pieceIndex) =>
                  piece.startsWith("**") ? (
                    <strong key={pieceIndex}>{piece.slice(2, -2)}</strong>
                  ) : piece.startsWith("`") ? (
                    <code key={pieceIndex}>{piece.slice(1, -1)}</code>
                  ) : (
                    piece
                  ),
                )}
            </Block>
          );
        })
    ),
  );
}
