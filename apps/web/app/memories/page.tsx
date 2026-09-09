import { Suspense } from "react";

import { LoadingState } from "@/components/status-state";
import { MemoryExplorer } from "@/features/memories/explorer";

export default function MemoriesPage() {
  return (
    <Suspense
      fallback={
        <div className="page-wrap">
          <LoadingState label="Loading memory explorer" />
        </div>
      }
    >
      <MemoryExplorer />
    </Suspense>
  );
}
