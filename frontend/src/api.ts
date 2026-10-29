import type { AnalyzeResponse, RunPayload, RunSummary } from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const text = await response.text();
  let payload: unknown = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(`Expected JSON from ${url} (HTTP ${response.status})`);
  }
  if (!response.ok) {
    const message =
      payload && typeof payload === "object" && "error" in payload
        ? String((payload as { error: unknown }).error)
        : `Request failed (HTTP ${response.status})`;
    throw new Error(message);
  }
  return payload as T;
}

export async function listRuns(): Promise<RunSummary[]> {
  const payload = await request<{ runs: RunSummary[] }>("/api/runs");
  return payload.runs;
}

export async function loadRun(id: string): Promise<RunPayload> {
  const params = new URLSearchParams({ id });
  return request<RunPayload>(`/api/run?${params.toString()}`);
}

export async function analyzeRepository(
  path: string,
  thinking: "low" | "medium" | "high",
): Promise<AnalyzeResponse> {
  return request<AnalyzeResponse>("/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path, thinking }),
  });
}
