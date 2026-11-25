import type {
  ForkRequest,
  ForkResponse,
  TraceDetailResponse,
  TraceListResponse,
} from "./types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export async function fetchTraces(): Promise<TraceListResponse> {
  const res = await fetch(`${API_BASE}/api/traces`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`Failed to fetch traces (${res.status})`);
  }
  return (await res.json()) as TraceListResponse;
}

export async function fetchTraceDetail(
  traceId: string
): Promise<TraceDetailResponse> {
  const res = await fetch(
    `${API_BASE}/api/traces/${encodeURIComponent(traceId)}`,
    { cache: "no-store" }
  );
  if (!res.ok) {
    throw new Error(`Failed to fetch trace ${traceId} (${res.status})`);
  }
  return (await res.json()) as TraceDetailResponse;
}

export async function createFork(
  traceId: string,
  payload: ForkRequest
): Promise<ForkResponse> {
  const res = await fetch(
    `${API_BASE}/api/traces/${encodeURIComponent(traceId)}/fork`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `Fork request failed (${res.status})`);
  }
  return (await res.json()) as ForkResponse;
}
