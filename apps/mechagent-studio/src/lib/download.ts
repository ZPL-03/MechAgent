import type { StudioRunResponse, TaskSummary, Visualization } from "../types";

export function downloadVisualization(
  visual: Visualization | undefined,
  renderMode: "geometry" | "mesh" | "result"
) {
  if (!visual) {
    return;
  }
  if (visual.scene) {
    const canvas = document.querySelector<HTMLCanvasElement>(".three-stage canvas");
    if (canvas) {
      const url = canvas.toDataURL("image/png");
      const link = document.createElement("a");
      link.href = url;
      link.download = `${visual.task_id || "mechagent"}-${visual.kind}-${renderMode}.png`;
      link.click();
      return;
    }
  }
  const blob = new Blob([visual.svg], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${visual.task_id || "mechagent"}-${visual.kind}.svg`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function downloadReport(runResult: StudioRunResponse | null, task: TaskSummary | null) {
  if (!runResult?.report) {
    return;
  }
  const taskName = safeFileSegment(task?.task_id || runResult.summary.tasks?.[0]?.task_id || "report");
  const statusName = runResult.success ? "passed" : "failed";
  const blob = new Blob([runResult.report], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `mechagent-${taskName}-${statusName}.md`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function downloadSummaryJson(
  runResult: StudioRunResponse | null,
  task: TaskSummary | null,
  summaryJson: string
) {
  if (!runResult) {
    return;
  }
  const taskName = safeFileSegment(
    task?.task_id || runResult.summary.tasks?.[0]?.task_id || "summary"
  );
  const statusName = runResult.success ? "passed" : "failed";
  const blob = new Blob([summaryJson], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `mechagent-${taskName}-${statusName}.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function safeFileSegment(value: string) {
  const normalized = value
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || "report";
}
