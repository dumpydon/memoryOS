import { Suspense } from "react";

import { LoadingState } from "@/components/status-state";
import { MemoryDetail } from "@/features/memories/detail";

export default async function MemoryDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <Suspense
      fallback={
        <div className="page-wrap">
          <LoadingState label="Loading memory history" />
        </div>
      }
    >
      <MemoryDetail memoryId={id} />
    </Suspense>
  );
}
