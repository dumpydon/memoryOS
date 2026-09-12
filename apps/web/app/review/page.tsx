import { Suspense } from "react";

import { LoadingState } from "@/components/status-state";
import { MemoryReview } from "@/features/review/inbox";

export default function ReviewPage() {
  return (
    <Suspense
      fallback={
        <div className="page-wrap">
          <LoadingState label="Loading memory review" />
        </div>
      }
    >
      <MemoryReview />
    </Suspense>
  );
}
