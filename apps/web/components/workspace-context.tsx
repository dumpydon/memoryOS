"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { PRIVATE_LIVE_SCOPE, PUBLIC_DEMO_SCOPE } from "@/lib/api/client";
import type { ExecutionMode } from "@/lib/api/types";

type WorkspaceContextValue = {
  token: string;
  mode: ExecutionMode;
  scopeId: string;
  isOwner: boolean;
  setToken: (token: string) => void;
  clearToken: () => void;
  setMode: (mode: ExecutionMode) => void;
  sessionKey: string;
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [token, setTokenState] = useState("");
  const [mode, setMode] = useState<ExecutionMode>("demo");
  const [sessionVersion, setSessionVersion] = useState(0);
  const previousAccess = useRef({ token: "", mode: "demo" as ExecutionMode });
  const setToken = (nextToken: string) => {
    setTokenState(nextToken);
    setSessionVersion((version) => version + 1);
  };

  useEffect(() => {
    if (
      previousAccess.current.token !== token ||
      previousAccess.current.mode !== mode
    )
      queryClient.clear();
    previousAccess.current = { token, mode };
  }, [mode, queryClient, token]);

  const value = useMemo(
    () => ({
      token,
      mode,
      scopeId: mode === "live" ? PRIVATE_LIVE_SCOPE : PUBLIC_DEMO_SCOPE,
      isOwner: Boolean(token.trim()),
      setToken,
      clearToken: () => setToken(""),
      setMode,
      sessionKey: `${mode}:${sessionVersion}`,
    }),
    [mode, sessionVersion, token],
  );
  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value)
    throw new Error("useWorkspace must be used inside WorkspaceProvider");
  return value;
}
