import { Suspense } from "react";

import { LoadingState } from "@/components/status-state";
import { HowItWorks } from "@/features/onboarding/how-it-works";

export default function HowItWorksPage() {
  return (
    <Suspense
      fallback={
        <div className="page-wrap">
          <LoadingState label="Loading product tour" />
        </div>
      }
    >
      <HowItWorks />
    </Suspense>
  );
}
