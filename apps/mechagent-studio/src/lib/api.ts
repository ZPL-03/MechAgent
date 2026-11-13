import type {
  StudioCapabilitiesResponse,
  StudioCapability,
  StudioExample,
  StudioExamplesResponse,
  StudioHealth,
  StudioInspectionResponse,
  StudioJobPage,
  StudioJobResponse
} from "../types";

export async function fetchHealth(): Promise<StudioHealth> {
  const response = await fetch("/api/v1/health");
  return (await response.json()) as StudioHealth;
}

export async function fetchDiagnostics() {
  const response = await fetch("/api/v1/diagnostics");
  return await response.json();
}

export async function fetchCapabilities(): Promise<StudioCapability[]> {
  const response = await fetch("/api/v1/capabilities");
  const data = (await response.json()) as StudioCapabilitiesResponse;
  return Array.isArray(data.capabilities) ? data.capabilities : [];
}

export async function fetchExamples(): Promise<StudioExample[]> {
  const response = await fetch("/api/v1/examples");
  const data = (await response.json()) as StudioExamplesResponse;
  return Array.isArray(data.examples) ? data.examples : [];
}

export async function inspectRequest(
  request: string,
  signal: AbortSignal
): Promise<StudioInspectionResponse> {
  const response = await fetch("/api/v1/inspect", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request, use_llm_agents: false }),
    signal
  });
  return (await response.json()) as StudioInspectionResponse;
}

export async function createJob(
  request: string,
  useLlmAgents: boolean,
  idempotencyKey: string = crypto.randomUUID()
): Promise<StudioJobResponse> {
  const response = await fetch("/api/v1/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ request, use_llm_agents: useLlmAgents })
  });
  const payload = await response.json();
  if (!response.ok) {
    throw apiError(payload, response.status, "请求失败。");
  }
  return payload as StudioJobResponse;
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) { super(message); }
}

function apiError(payload: unknown, status: number, fallback: string): ApiError {
  const body = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
  const detail = typeof body.detail === "string" ? body.detail : fallback;
  const code = typeof body.code === "string" ? body.code : undefined;
  return new ApiError(detail, status, code);
}

export async function cancelJob(jobId: string): Promise<StudioJobResponse> {
  return await jobAction(jobId, "cancel");
}

export async function retryJob(jobId: string): Promise<StudioJobResponse> {
  return await jobAction(jobId, "retry");
}

async function jobAction(jobId: string, action: string): Promise<StudioJobResponse> {
  const response = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/${action}`, {
    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }
  });
  const payload = await response.json();
  if (!response.ok) throw apiError(payload, response.status, "请求失败。");
  return payload as StudioJobResponse;
}

export async function fetchJobs(cursor?: string): Promise<StudioJobPage> {
  const query = new URLSearchParams({ limit: "10" });
  if (cursor) query.set("cursor", cursor);
  const response = await fetch(`/api/v1/jobs?${query.toString()}`);
  const payload = await response.json();
  if (!response.ok) throw apiError(payload, response.status, "请求失败。");
  return payload as StudioJobPage;
}

export async function fetchEvidence(jobId: string): Promise<{ valid: boolean; errors: string[] }> {
  const response = await fetch(`/api/v1/jobs/${encodeURIComponent(jobId)}/evidence`);
  const payload = await response.json();
  if (!response.ok) throw apiError(payload, response.status, "请求失败。");
  return payload;
}

export async function fetchJob(jobId: string): Promise<StudioJobResponse> {
  const response = await fetch(`/api/v1/jobs/${jobId}`);
  const payload = await response.json();
  if (!response.ok) {
    throw apiError(payload, response.status, "作业状态读取失败。");
  }
  return payload as StudioJobResponse;
}
