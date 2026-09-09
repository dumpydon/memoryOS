"use client";

import { useWorkspace } from "@/components/workspace-context";

export function WorkspaceMain({ children }: { children: React.ReactNode }) {
  const { sessionKey } = useWorkspace();
  return (
    <main className="main-canvas">
      <div key={sessionKey}>{children}</div>
    </main>
  );
}
