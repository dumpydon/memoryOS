import { Suspense } from "react";

import { LoadingState } from "@/components/status-state";
import { IngestionPlayground } from "@/features/ingestion/playground";

export default function IngestionPage() {
  return (
    <Suspense
      fallback={
        <div className="page-wrap">
          <LoadingState label="Loading ingestion playground" />
        </div>
      }
    >
      <IngestionPlayground />
    </Suspense>
  );
}
