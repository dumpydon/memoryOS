import { Suspense } from "react";

import { LoadingState } from "@/components/status-state";
import { RecallLab } from "@/features/recall/lab";

export default function RecallPage() {
  return (
    <Suspense
      fallback={
        <div className="page-wrap">
          <LoadingState label="Loading Recall Lab" />
        </div>
      }
    >
      <RecallLab />
    </Suspense>
  );
}
