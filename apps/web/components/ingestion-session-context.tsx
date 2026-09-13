"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useWorkspace } from "@/components/workspace-context";
import type { IngestInteractionResponse } from "@/lib/api/types";

export type IngestionOperation = "preview" | "commit";

type IngestionSessionState = {
  text: string;
  idempotencyKey: string;
  scenarioId: string | null;
  result: IngestInteractionResponse | null;
  lastOperation: IngestionOperation | null;
};

type IngestionSessionContextValue = IngestionSessionState & {
  setText: (text: string) => void;
  setIdempotencyKey: (key: string) => void;
  setScenarioId: (scenarioId: string | null) => void;
  clearResult: () => void;
  complete: (
    result: IngestInteractionResponse,
    operation: IngestionOperation,
  ) => void;
  reset: () => void;
};

const IngestionSessionContext =
  createContext<IngestionSessionContextValue | null>(null);

function freshSessionState(
  scenarioId: string | null = null,
): IngestionSessionState {
  return {
    text: "",
    idempotencyKey: `memoryos-${Date.now()}`,
    scenarioId,
    result: null,
    lastOperation: null,
  };
}

export function IngestionSessionProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { sessionKey } = useWorkspace();
  const [state, setState] = useState<IngestionSessionState>(() =>
    freshSessionState(),
  );
  const previousSessionKey = useRef(sessionKey);

  useEffect(() => {
    if (previousSessionKey.current === sessionKey) return;
    previousSessionKey.current = sessionKey;
    setState(freshSessionState());
  }, [sessionKey]);

  const setText = useCallback((text: string) => {
    setState((current) => ({ ...current, text }));
  }, []);
  const setIdempotencyKey = useCallback((idempotencyKey: string) => {
    setState((current) => ({ ...current, idempotencyKey }));
  }, []);
  const setScenarioId = useCallback((scenarioId: string | null) => {
    setState((current) => ({ ...current, scenarioId }));
  }, []);
  const clearResult = useCallback(() => {
    setState((current) => ({
      ...current,
      result: null,
      lastOperation: null,
    }));
  }, []);
  const complete = useCallback(
    (result: IngestInteractionResponse, lastOperation: IngestionOperation) => {
      setState((current) => ({ ...current, result, lastOperation }));
    },
    [],
  );
  const reset = useCallback(() => {
    setState((current) => freshSessionState(current.scenarioId));
  }, []);

  const value = useMemo(
    () => ({
      ...state,
      setText,
      setIdempotencyKey,
      setScenarioId,
      clearResult,
      complete,
      reset,
    }),
    [
      state,
      setText,
      setIdempotencyKey,
      setScenarioId,
      clearResult,
      complete,
      reset,
    ],
  );

  return (
    <IngestionSessionContext.Provider value={value}>
      {children}
    </IngestionSessionContext.Provider>
  );
}

export function useIngestionSession() {
  const value = useContext(IngestionSessionContext);
  if (!value) {
    throw new Error(
      "useIngestionSession must be used inside IngestionSessionProvider",
    );
  }
  return value;
}
