import {
  AlertCircle,
  CheckCircle2,
  LoaderCircle,
  RefreshCw,
  WifiOff,
} from "lucide-react";

import { ApiClientError } from "@/lib/api/client";

export function LoadingState({
  label = "Loading memory data",
}: {
  label?: string;
}) {
  return (
    <div className="state-card" role="status" aria-live="polite">
      <LoaderCircle className="spin" size={18} aria-hidden="true" />
      <div>
        <strong>{label}</strong>
        <span>Reading the current scope from the API.</span>
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  detail,
}: {
  title: string;
  detail: string;
}) {
  return (
    <div className="empty-state">
      <CheckCircle2 size={20} aria-hidden="true" />
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  const apiError = error instanceof ApiClientError ? error : null;
  const title =
    apiError?.code === "backend_unreachable"
      ? "Backend is waking up"
      : "MemoryOS could not load this view";
  const detail =
    apiError?.message || "Try again after checking the API service.";
  return (
    <div className="state-card error" role="alert">
      {apiError?.code === "backend_unreachable" ? (
        <WifiOff size={18} aria-hidden="true" />
      ) : (
        <AlertCircle size={18} aria-hidden="true" />
      )}
      <div>
        <strong>{title}</strong>
        <span>{detail}</span>
      </div>
      {onRetry ? (
        <button
          className="icon-button"
          type="button"
          onClick={onRetry}
          aria-label="Retry request"
        >
          <RefreshCw size={15} />
        </button>
      ) : null}
    </div>
  );
}

export function InlineNotice({
  children,
  tone = "info",
}: {
  children: React.ReactNode;
  tone?: "info" | "warning" | "success";
}) {
  return (
    <div
      className={`inline-notice ${tone}`}
      role={tone === "warning" ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
