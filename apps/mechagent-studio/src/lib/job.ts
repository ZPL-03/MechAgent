import type { StudioJobResponse, StudioRunResponse } from "../types";
import { formatDuration } from "./format";
import { ApiError } from "./api";

export type JobFailureDisposition = "submission" | "missing" | "disconnected";

export function jobFailureDisposition(error: unknown, hasPersistedJob: boolean): JobFailureDisposition {
  if (hasPersistedJob && error instanceof ApiError && error.status === 404) {
    return "missing";
  }
  if (!hasPersistedJob && error instanceof ApiError && error.status > 0 && error.status < 500) {
    return "submission";
  }
  return "disconnected";
}

export function isActiveJob(job: StudioJobResponse) {
  return ["queued", "starting", "running", "cancelling"].includes(job.status);
}

export function sleep(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

export function shortJobId(jobId: string) {
  return `作业 ${jobId.slice(0, 8)}`;
}

export function jobStatusLabel(status: StudioJobResponse["status"]) {
  if (status === "starting") return "启动中";
  if (status === "cancelling") return "取消中";
  if (status === "cancelled") return "已取消";
  if (status === "interrupted") return "已中断";
  if (status === "queued") {
    return "排队";
  }
  if (status === "running") {
    return "运行";
  }
  if (status === "succeeded") {
    return "完成";
  }
  return "失败";
}

export function jobElapsedLabel(job: StudioJobResponse | null, running: boolean, clockTick: number) {
  void clockTick;
  if (!job) {
    return "";
  }
  if (typeof job.duration_ms === "number" && Number.isFinite(job.duration_ms)) {
    return formatDuration(job.duration_ms);
  }
  const baseTime = Date.parse(job.started_at ?? job.created_at);
  if (!Number.isFinite(baseTime)) {
    return "";
  }
  const endTime = job.finished_at ? Date.parse(job.finished_at) : Date.now();
  if (!running && !Number.isFinite(endTime)) {
    return "";
  }
  return formatDuration(Math.max(endTime - baseTime, 0));
}

export function recentJobEvents(job: StudioJobResponse | null) {
  return [...(job?.events ?? [])].slice(-5).reverse();
}

export function runError(message: string): StudioRunResponse {
  return {
    success: false,
    report: message,
    summary: {
      success: false,
      tasks: [],
      errors: [{ node: "studio", message }]
    },
    visualizations: [],
    error: message
  };
}
