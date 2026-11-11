import type {
  StudioCapabilitiesResponse,
  StudioCapability,
  StudioExample,
  StudioExamplesResponse,
  StudioHealth,
  StudioInspectionResponse,
  StudioJobResponse
} from "../types";

export async function fetchHealth(): Promise<StudioHealth> {
  const response = await fetch("/api/health");
  return (await response.json()) as StudioHealth;
}

export async function fetchDiagnostics() {
  const response = await fetch("/api/diagnostics");
  return await response.json();
}

export async function fetchCapabilities(): Promise<StudioCapability[]> {
  const response = await fetch("/api/capabilities");
  const data = (await response.json()) as StudioCapabilitiesResponse;
  return Array.isArray(data.capabilities) ? data.capabilities : [];
}

export async function fetchExamples(): Promise<StudioExample[]> {
  const response = await fetch("/api/examples");
  const data = (await response.json()) as StudioExamplesResponse;
  return Array.isArray(data.examples) ? data.examples : [];
}

export async function inspectRequest(
  request: string,
  signal: AbortSignal
): Promise<StudioInspectionResponse> {
  const response = await fetch("/api/inspect", {
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
  const response = await fetch("/api/jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ request, use_llm_agents: useLlmAgents })
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new ApiError(String(payload.detail ?? "请求失败。"), response.status);
  }
  return payload as StudioJobResponse;
}

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

export async function cancelJob(jobId: string): Promise<StudioJobResponse> {
  return await jobAction(jobId, "cancel");
}

export async function retryJob(jobId: string): Promise<StudioJobResponse> {
  return await jobAction(jobId, "retry");
}

async function jobAction(jobId: string, action: string): Promise<StudioJobResponse> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/${action}`, {
    method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }
  });
  const payload = await response.json();
  if (!response.ok) throw new ApiError(String(payload.detail ?? "请求失败。"), response.status);
  return payload as StudioJobResponse;
}

export async function fetchJobs(): Promise<StudioJobResponse[]> {
  const response = await fetch("/api/jobs?limit=10");
  const payload = await response.json();
  if (!response.ok) throw new ApiError(String(payload.detail ?? "请求失败。"), response.status);
  return payload.jobs;
}

export async function fetchEvidence(jobId: string): Promise<{ valid: boolean; errors: string[] }> {
  const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/evidence`);
  const payload = await response.json();
  if (!response.ok) throw new ApiError(String(payload.detail ?? "请求失败。"), response.status);
  return payload;
}

export async function fetchJob(jobId: string): Promise<StudioJobResponse> {
  const response = await fetch(`/api/jobs/${jobId}`);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(String(payload.detail ?? "作业状态读取失败。"));
  }
  return payload as StudioJobResponse;
}
