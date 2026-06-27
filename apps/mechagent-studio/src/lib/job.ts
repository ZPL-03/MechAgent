import type { StudioJobResponse, StudioRunResponse } from "../types";
import { formatDuration } from "./format";

export function isActiveJob(job: StudioJobResponse) {
  return job.status === "queued" || job.status === "running";
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
