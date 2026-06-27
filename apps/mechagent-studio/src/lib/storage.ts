import type { StudioRunResponse, TaskError, TaskSummary } from "../types";
import {
  HISTORY_REPORT_CHAR_LIMIT,
  HISTORY_STORAGE_FALLBACK_ITEMS,
  HISTORY_STORAGE_KEY,
  MAX_HISTORY_ITEMS,
  PERCENT_FORMATTER
} from "./constants";
import { formatHistoryTime, formatNumber, isRecord } from "./format";
import type { RunHistoryItem } from "./uiTypes";

export function createHistoryItem(request: string, result: StudioRunResponse): RunHistoryItem {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    request,
    result: compactHistoryResult(result)
  };
}

export function loadRunHistory(): RunHistoryItem[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(HISTORY_STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    const items = parsed.filter(isRunHistoryItem).map(compactHistoryItem).slice(0, MAX_HISTORY_ITEMS);
    return saveRunHistory(items);
  } catch {
    try {
      window.localStorage.removeItem(HISTORY_STORAGE_KEY);
    } catch {
      return [];
    }
    return [];
  }
}

export function saveRunHistory(items: RunHistoryItem[]) {
  const compactItems = items.map(compactHistoryItem).slice(0, MAX_HISTORY_ITEMS);
  if (typeof window !== "undefined") {
    try {
      window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(compactItems));
      return compactItems;
    } catch {
      const fallbackItems = compactItems.slice(0, HISTORY_STORAGE_FALLBACK_ITEMS);
      try {
        window.localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(fallbackItems));
        return fallbackItems;
      } catch {
        try {
          window.localStorage.removeItem(HISTORY_STORAGE_KEY);
        } catch {
          return [];
        }
        return [];
      }
    }
  }
  return compactItems;
}

function isRunHistoryItem(value: unknown): value is RunHistoryItem {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.id === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.request === "string" &&
    isStudioRunResponse(value.result)
  );
}

function compactHistoryItem(item: RunHistoryItem): RunHistoryItem {
  return {
    id: item.id,
    createdAt: item.createdAt,
    request: trimStorageText(item.request, 1200),
    result: compactHistoryResult(item.result)
  };
}

function isStudioRunResponse(value: unknown): value is StudioRunResponse {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.success === "boolean" &&
    isRecord(value.summary) &&
    Array.isArray(value.visualizations)
  );
}

function compactHistoryResult(result: StudioRunResponse): StudioRunResponse {
  return {
    success: result.success,
    report: trimStorageText(result.report, HISTORY_REPORT_CHAR_LIMIT),
    summary: {
      success: result.summary.success,
      work_dir: result.summary.work_dir ?? null,
      report_path: result.summary.report_path ?? null,
      errors: (result.summary.errors ?? []).slice(0, 6).map(compactTaskError),
      tasks: (result.summary.tasks ?? []).slice(0, 8).map(compactHistoryTask)
    },
    visualizations: [],
    metadata:
      result.metadata?.duration_ms !== undefined
        ? { duration_ms: result.metadata.duration_ms }
        : undefined,
    error: result.error
  };
}

function compactHistoryTask(task: TaskSummary): TaskSummary {
  return {
    task_id: task.task_id,
    case_id: task.case_id,
    capability_id: task.capability_id,
    title: task.title,
    analysis_type: task.analysis_type,
    model_params: compactRecord(task.model_params, 5),
    mesh_result: task.mesh_result
      ? {
          success: task.mesh_result.success,
          mesh_file: task.mesh_result.mesh_file ?? null,
          element_count: task.mesh_result.element_count,
          node_count: task.mesh_result.node_count,
          quality: compactNumberMap(task.mesh_result.quality),
          metadata: compactRecord(task.mesh_result.metadata, 3) ?? undefined,
          error_message: task.mesh_result.error_message ?? null
        }
      : null,
    solver_result: task.solver_result
      ? {
          success: task.solver_result.success,
          model_case_id: task.solver_result.model_case_id,
          quantity: task.solver_result.quantity,
          unit: task.solver_result.unit,
          predicted: task.solver_result.predicted,
          reference: task.solver_result.reference,
          relative_error: task.solver_result.relative_error,
          tolerance: task.solver_result.tolerance,
          passed: task.solver_result.passed,
          verification_status: task.solver_result.verification_status,
          solver: task.solver_result.solver,
          output_files: task.solver_result.output_files?.slice(0, 16),
          mesh_file: task.solver_result.mesh_file ?? null,
          mesh_metadata: compactRecord(task.solver_result.mesh_metadata, 3) ?? undefined,
          values: compactRecord(task.solver_result.values, 3) ?? undefined
        }
      : null,
    post_summary: compactRecord(task.post_summary, 3),
    analysis_text:
      typeof task.analysis_text === "string"
        ? trimStorageText(task.analysis_text, 800)
        : undefined,
    error: task.error ? compactTaskError(task.error) : null
  };
}

function compactTaskError(error: TaskError): TaskError {
  return {
    node: error.node,
    code: error.code,
    message: trimStorageText(error.message, 800),
    missing_fields: error.missing_fields?.slice(0, 16)
  };
}

function compactRecord(
  value: Record<string, unknown> | null | undefined,
  depth: number
): Record<string, unknown> | null {
  if (!isRecord(value)) {
    return null;
  }
  const compacted = compactStorageValue(value, depth);
  return isRecord(compacted) ? compacted : null;
}

function compactNumberMap(value: Record<string, number> | undefined) {
  if (!value) {
    return undefined;
  }
  return Object.fromEntries(
    Object.entries(value)
      .filter(([, item]) => Number.isFinite(item))
      .slice(0, 24)
  );
}

function compactStorageValue(value: unknown, depth: number): unknown {
  if (value === null || value === undefined) {
    return value;
  }
  if (typeof value === "string") {
    return trimStorageText(value, 1000);
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  if (Array.isArray(value)) {
    if (depth <= 0) {
      return [];
    }
    return value.slice(0, 24).map((item) => compactStorageValue(item, depth - 1));
  }
  if (!isRecord(value) || depth <= 0) {
    return null;
  }
  const skippedKeys = new Set([
    "visualizations",
    "scene",
    "svg",
    "nodes",
    "elements",
    "report",
    "planner_llm_trace",
    "designer_llm_trace",
    "mesh_llm_trace",
    "reporter_llm_trace",
    "prompt",
    "response"
  ]);
  const entries = Object.entries(value)
    .filter(([key]) => !skippedKeys.has(key))
    .slice(0, 48)
    .map(([key, item]) => [key, compactStorageValue(item, depth - 1)] as const)
    .filter(([, item]) => item !== null && item !== undefined);
  return Object.fromEntries(entries);
}

function trimStorageText(value: string, limit: number) {
  return value.length > limit ? `${value.slice(0, limit)}...` : value;
}

export function historyTitle(result: StudioRunResponse) {
  const task = result.summary.tasks?.[0];
  const solver = task?.solver_result;
  return solver?.model_case_id || task?.case_id || task?.title || "运行结果";
}

export function historyMeta(item: RunHistoryItem) {
  const task = item.result.summary.tasks?.[0];
  const solver = task?.solver_result;
  const parts = [formatHistoryTime(item.createdAt)];
  if (solver?.predicted !== undefined && solver.predicted !== null) {
    parts.push(`${formatNumber(solver.predicted)} ${solver.unit ?? ""}`.trim());
  }
  if (solver?.relative_error !== undefined && solver.relative_error !== null) {
    parts.push(PERCENT_FORMATTER.format(solver.relative_error));
  }
  return parts.join(" · ");
}
