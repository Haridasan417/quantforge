// Thin API client stub. Every backend call goes through here so the base
// URL (and later: auth headers, error handling) lives in one place.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

// Phase 8: the dashboard's WebSocket needs the same origin as every REST
// call above, just ws(s):// instead of http(s):// -- one helper so that
// swap lives here rather than being hand-rolled at each call site.
export function wsUrl(path: string): string {
  return `${API_BASE_URL.replace(/^http/, "ws")}${path}`;
}

export class ApiError extends Error {
  status: number;
  detail?: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!res.ok) {
    // FastAPI error bodies are `{"detail": "..."}` (validation) or
    // `{"detail": [...]}` (pydantic field errors) — surface that instead
    // of a bare status code wherever the caller just shows err.message,
    // e.g. "No action node has any condition wired into it" rather than
    // "POST /api/strategies/custom failed: 422".
    let detail: unknown;
    try {
      detail = await res.json();
    } catch {
      // body wasn't JSON (or was empty) — fall through with detail unset
    }
    const detailMessage =
      detail && typeof detail === "object" && "detail" in detail
        ? String((detail as { detail: unknown }).detail)
        : undefined;

    throw new ApiError(
      res.status,
      detailMessage ?? `${init?.method ?? "GET"} ${path} failed: ${res.status}`,
      detail,
    );
  }

  // A 204 (e.g. DELETE /api/strategies/{id}) has no body — res.json()
  // would throw on the empty string trying to parse it as JSON.
  if (res.status === 204) return undefined as T;

  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  del: <T = void>(path: string) => request<T>(path, { method: "DELETE" }),
};

// Wired up in Phase 1 against GET /api/candles.
export async function health(): Promise<{ status: string }> {
  return api.get("/health");
}
