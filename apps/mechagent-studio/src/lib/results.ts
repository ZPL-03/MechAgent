import type {
  StudioJobResponse,
  StudioRunResponse,
  TaskSummary,
  WorkflowSummary
} from "../types";
import { PERCENT_FORMATTER } from "./constants";
import { arrayValue, formatDuration, formatNumber, isRecord, recordValue, textValue } from "./format";
import { jobElapsedLabel } from "./job";
import { boundaryLabel, geometryLabel, loadLabel, materialLabel, meshLabel } from "./labels";
import type { DisplayItem, MetricItem } from "./uiTypes";

export type StatusTone = "neutral" | "ok" | "warn" | "bad";

export function taskStatus(task: TaskSummary): { label: string; tone: StatusTone } {
  const solver = task.solver_result;
  if (task.error) {
    return { label: task.error.code || "失败", tone: "bad" };
  }
  if (solver?.verification_status === "failed" || solver?.success === false) {
    return { label: "未通过", tone: "bad" };
  }
  if (solver?.passed === true) {
    return { label: "通过", tone: "ok" };
  }
  if (solver?.verification_status === "unverified") {
    return { label: "未验证", tone: "warn" };
  }
  if (solver?.success === true) {
    return { label: "已求解", tone: "warn" };
  }
  return { label: "待求解", tone: "neutral" };
}

export function runOutcome(result: StudioRunResponse, task: TaskSummary | null = null) {
  if (!result.success) {
    return {
      label: "未通过",
      message: result.error ?? "检查错误摘要。",
      title: "结果未通过",
      tone: "bad" as const
    };
  }

  const states = task
    ? [taskStatus(task)]
    : (result.summary.tasks ?? []).map((item) => taskStatus(item));
  if (states.length > 0 && states.every((state) => state.tone === "ok")) {
    return {
      label: "通过",
      message: "工作流、求解和参考校核链路完成。",
      title: "结果满足验收",
      tone: "ok" as const
    };
  }
  if (states.some((state) => state.tone === "bad")) {
    return {
      label: "未通过",
      message: result.error ?? "检查错误摘要。",
      title: "结果未通过",
      tone: "bad" as const
    };
  }
  if (states.some((state) => state.tone === "warn")) {
    return {
      label: "未验证",
      message: "求解已完成；缺少参考解或阈值，未进行参考解验收。",
      title: "求解完成，未参考验收",
      tone: "warn" as const
    };
  }
  return {
    label: "已完成",
    message: "工作流已完成，查看任务摘要确认结果状态。",
    title: "仿真已完成",
    tone: "neutral" as const
  };
}

export function metricItems(
  result: StudioRunResponse | null,
  task: TaskSummary | null,
  running: boolean,
  job: StudioJobResponse | null,
  clockTick: number
): MetricItem[] {
  const solver = task?.solver_result;
  const status = task ? taskStatus(task) : result ? runOutcome(result) : null;
  return [
    {
      label: "状态",
      value: running ? "运行中" : status ? status.label : "待运行",
      tone: running ? "warn" : (status?.tone ?? "neutral")
    },
    {
      label: "主结果",
      value:
        solver?.predicted !== undefined && solver.predicted !== null
          ? `${formatNumber(solver.predicted)} ${solver.unit ?? ""}`.trim()
          : "N/A"
    },
    {
      label: "相对误差",
      value:
        solver?.relative_error !== undefined && solver.relative_error !== null
          ? PERCENT_FORMATTER.format(solver.relative_error)
          : "N/A",
      tone:
        solver?.passed === true ? "ok" : solver?.verification_status === "failed" ? "bad" : "neutral"
    },
    {
      label: "耗时",
      value:
        running && job
          ? jobElapsedLabel(job, running, clockTick)
          : result?.metadata?.duration_ms !== undefined
            ? formatDuration(result.metadata.duration_ms)
            : "N/A"
    }
  ];
}

export function verificationItems(task: TaskSummary | null): DisplayItem[] {
  const solver = task?.solver_result;
  if (!solver) {
    return [];
  }
  return [
    { label: "算例", value: solver.model_case_id || task?.case_id || "N/A" },
    {
      label: "参考值",
      value:
        solver.reference !== undefined && solver.reference !== null
          ? `${formatNumber(solver.reference)} ${solver.unit ?? ""}`.trim()
          : "N/A"
    },
    {
      label: "阈值",
      value:
        solver.tolerance !== undefined && solver.tolerance !== null
          ? PERCENT_FORMATTER.format(solver.tolerance)
          : "N/A"
    },
    { label: "求解器", value: solver.solver || "N/A" }
  ];
}

export function taskModelLabel(task: TaskSummary) {
  const model = recordValue(task.model_params);
  const caseId = task.solver_result?.model_case_id || task.case_id || textValue(model?.case_id, "");
  const geometry = recordValue(model?.geometry);
  const geometryType = textValue(geometry?.type, "");
  if (caseId && geometryType) {
    return `${caseId} · ${geometryType}`;
  }
  return caseId || geometryType || task.title || "N/A";
}

export function taskResultValue(task: TaskSummary) {
  const solver = task.solver_result;
  if (solver?.predicted === undefined || solver.predicted === null) {
    return "N/A";
  }
  return `${formatNumber(solver.predicted)} ${solver.unit ?? ""}`.trim();
}

export function taskRelativeError(task: TaskSummary) {
  const solver = task.solver_result;
  if (solver?.relative_error === undefined || solver.relative_error === null) {
    return "N/A";
  }
  return PERCENT_FORMATTER.format(solver.relative_error);
}

export function studyFacts(task: TaskSummary | null): DisplayItem[] {
  const model = recordValue(task?.model_params);
  if (!model) {
    return [];
  }
  const geometry = recordValue(model.geometry);
  const dimensions = recordValue(geometry?.dimensions);
  const material = recordValue(model.material);
  const mesh = recordValue(model.mesh);
  const loads = arrayValue(model.loads).map(recordValue).filter(isRecord);
  const bcs = arrayValue(model.bcs).map(recordValue).filter(isRecord);
  return [
    { label: "几何", value: geometryLabel(geometry, dimensions) },
    { label: "材料", value: materialLabel(material) },
    { label: "载荷", value: loadLabel(loads[0]) },
    { label: "边界", value: boundaryLabel(bcs[0], bcs.length) },
    { label: "网格", value: meshLabel(mesh, task?.mesh_result ?? null) }
  ];
}

export function artifactPaths(summary: WorkflowSummary | undefined, task: TaskSummary | null) {
  const paths = new Set<string>();
  if (summary?.work_dir) {
    paths.add(summary.work_dir);
  }
  if (summary?.report_path) {
    paths.add(summary.report_path);
  }
  if (task?.mesh_result?.mesh_file) {
    paths.add(task.mesh_result.mesh_file);
  }
  if (task?.solver_result?.mesh_file) {
    paths.add(task.solver_result.mesh_file);
  }
  for (const file of task?.solver_result?.output_files ?? []) {
    paths.add(file);
  }
  return [...paths];
}

export function artifactLabel(path: string) {
  const normalized = path.toLowerCase();
  if (normalized.endsWith("report.md")) {
    return "报告";
  }
  if (normalized.endsWith("_mesh.inp")) {
    return "网格";
  }
  if (normalized.endsWith(".frd")) {
    return "结果场";
  }
  if (normalized.endsWith(".inp")) {
    return "求解输入";
  }
  if (normalized.endsWith(".dat")) {
    return "求解数据";
  }
  if (normalized.endsWith(".sta")) {
    return "状态";
  }
  if (normalized.endsWith(".cvg")) {
    return "收敛";
  }
  if (normalized.endsWith(".12d")) {
    return "求解中间";
  }
  return "目录";
}
