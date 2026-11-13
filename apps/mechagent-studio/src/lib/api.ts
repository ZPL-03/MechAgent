import type {
  StudioCapabilitiesResponse,
  StudioCapability,
  StudioDiagnosticsResponse,
  StudioExample,
  StudioExamplesResponse,
  StudioHealth,
  StudioInspectionResponse,
  StudioJobPage,
  StudioJobResponse
} from "../types";

type JsonObject = Record<string, unknown>;

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
    public detail: unknown = message,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (detail !== undefined && detail !== null) {
    try {
      return JSON.stringify(detail) ?? fallback;
    } catch {
      return fallback;
    }
  }
  return fallback;
}

async function readPayload(response: Response): Promise<unknown> {
  if (typeof response.text === "function") {
    try {
      const text = await response.text();
      if (!text) return {};
      try {
        return JSON.parse(text) as unknown;
      } catch {
        return { detail: text };
      }
    } catch {
      return {};
    }
  }
  try {
    return await response.json();
  } catch {
    return {};
  }
}

async function requestJson<T>(
  input: RequestInfo | URL,
  init: RequestInit | undefined,
  fallback: string,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(input, init);
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") throw error;
    const message = error instanceof Error ? error.message : String(error);
    throw new ApiError(message || "Studio 服务连接失败。", 0, "transport_error", error);
  }
  const payload = await readPayload(response);
  if (!response.ok) throw apiError(payload, response.status, fallback);
  return payload as T;
}

function apiError(payload: unknown, status: number, fallback: string): ApiError {
  const body = isJsonObject(payload) ? payload : {};
  const detail = body.detail ?? (typeof payload === "string" ? payload : fallback);
  const code = typeof body.code === "string" ? body.code : undefined;
  return new ApiError(errorMessage(detail, fallback), status, code, detail);
}

export async function fetchHealth(): Promise<StudioHealth> {
  return await requestJson<StudioHealth>("/api/v1/health", undefined, "环境状态读取失败。");
}

export async function fetchDiagnostics(): Promise<StudioDiagnosticsResponse> {
  return await requestJson<StudioDiagnosticsResponse>(
    "/api/v1/diagnostics",
    undefined,
    "环境诊断读取失败。",
  );
}

export async function fetchCapabilities(): Promise<StudioCapability[]> {
  const data = await requestJson<StudioCapabilitiesResponse>(
    "/api/v1/capabilities",
    undefined,
    "能力目录读取失败。",
  );
  return Array.isArray(data.capabilities) ? data.capabilities : [];
}

export async function fetchExamples(): Promise<StudioExample[]> {
  const data = await requestJson<StudioExamplesResponse>(
    "/api/v1/examples",
    undefined,
    "案例目录读取失败。",
  );
  return Array.isArray(data.examples) ? data.examples : [];
}

export async function inspectRequest(
  request: string,
  signal: AbortSignal
): Promise<StudioInspectionResponse> {
  return await requestJson<StudioInspectionResponse>(
    "/api/v1/inspect",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request, use_llm_agents: false }),
      signal,
    },
    "预检请求失败。",
  );
}

export async function createJob(
  request: string,
  useLlmAgents: boolean,
  idempotencyKey: string = crypto.randomUUID()
): Promise<StudioJobResponse> {
  return await requestJson<StudioJobResponse>(
    "/api/v1/jobs",
    {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ request, use_llm_agents: useLlmAgents }),
    },
    "请求失败。",
  );
}

export async function cancelJob(jobId: string): Promise<StudioJobResponse> {
  return await jobAction(jobId, "cancel");
}

export async function retryJob(jobId: string): Promise<StudioJobResponse> {
  return await jobAction(jobId, "retry");
}

async function jobAction(jobId: string, action: string): Promise<StudioJobResponse> {
  return await requestJson<StudioJobResponse>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/${action}`,
    {
      method: "POST",
      headers: { "Idempotency-Key": crypto.randomUUID() },
    },
    "请求失败。",
  );
}

export async function fetchJobs(cursor?: string): Promise<StudioJobPage> {
  const query = new URLSearchParams({ limit: "10" });
  if (cursor) query.set("cursor", cursor);
  return await requestJson<StudioJobPage>(
    `/api/v1/jobs?${query.toString()}`,
    undefined,
    "请求失败。",
  );
}

export async function fetchEvidence(jobId: string): Promise<{ valid: boolean; errors: string[] }> {
  return await requestJson<{ valid: boolean; errors: string[] }>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}/evidence`,
    undefined,
    "请求失败。",
  );
}

export async function fetchJob(jobId: string): Promise<StudioJobResponse> {
  return await requestJson<StudioJobResponse>(
    `/api/v1/jobs/${encodeURIComponent(jobId)}`,
    undefined,
    "作业状态读取失败。",
  );
}
