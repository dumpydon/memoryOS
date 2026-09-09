import type { ExecutionMode } from "./types";

export const PUBLIC_DEMO_SCOPE = "00000000-0000-0000-0000-000000000001";
export const PRIVATE_LIVE_SCOPE = "00000000-0000-0000-0000-000000000002";
export const DEMO_EMBEDDING_MODEL = "demo-fixture-v1";
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";
const API_TIMEOUT_MS = 90_000;

export class ApiClientError extends Error {
  code: string;
  retryable: boolean;
  status: number | null;

  constructor(
    message: string,
    options?: { code?: string; retryable?: boolean; status?: number | null },
  ) {
    super(message);
    this.name = "ApiClientError";
    this.code = options?.code || "api_error";
    this.retryable = options?.retryable ?? false;
    this.status = options?.status ?? null;
  }
}

type RequestOptions = RequestInit & { token?: string | null };

export async function apiFetch<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { token, headers, ...init } = options;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      cache: "no-store",
      signal: init.signal ?? controller.signal,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
    });
  } catch {
    if (controller.signal.aborted) {
      throw new ApiClientError(
        "The API did not respond within 90 seconds. It may still be waking up.",
        {
          code: "backend_timeout",
          retryable: true,
        },
      );
    }
    throw new ApiClientError(
      "The API could not be reached. It may still be waking up.",
      {
        code: "backend_unreachable",
        retryable: true,
      },
    );
  } finally {
    clearTimeout(timeout);
  }

  const raw = await response.text();
  const contentType = response.headers.get("content-type") || "";
  if (
    response.ok &&
    (!raw.trim() || !contentType.toLowerCase().includes("json"))
  ) {
    throw new ApiClientError("The API returned an invalid or empty response.", {
      code: "invalid_response",
      retryable: true,
      status: response.status,
    });
  }
  let payload: unknown = null;
  try {
    payload = raw ? JSON.parse(raw) : null;
  } catch {
    payload = null;
  }

  if (!response.ok) {
    const error =
      payload && typeof payload === "object"
        ? (payload as Record<string, unknown>)
        : {};
    throw new ApiClientError(
      typeof error.message === "string"
        ? error.message
        : `The API returned ${response.status}.`,
      {
        code:
          typeof error.code === "string"
            ? error.code
            : response.status === 401
              ? "auth_required"
              : "api_error",
        retryable:
          typeof error.retryable === "boolean"
            ? error.retryable
            : response.status >= 500,
        status: response.status,
      },
    );
  }

  return payload as T;
}

export function buildScopePath(scopeId: string, mode: ExecutionMode) {
  return { scope_id: scopeId, mode };
}
