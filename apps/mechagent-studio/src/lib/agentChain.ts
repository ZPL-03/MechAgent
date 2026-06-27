import type { AgentTrace, StageKey, StudioRunResponse, TaskSummary } from "../types";
import { PERCENT_FORMATTER } from "./constants";
import {
  arrayValue,
  finiteNumberValue,
  formatNumber,
  isRecord,
  recordValue,
  textValue,
  uniqueStrings
} from "./format";
import { geometryLabel, materialLabel, boundaryLabel, loadLabel, meshLabel } from "./labels";
import { taskRelativeError, taskStatus } from "./results";
import { normalizeErrorNode } from "./stages";
import type { AgentChainItem, AgentChainTone, DisplayItem } from "./uiTypes";

export function buildAgentChain(
  result: StudioRunResponse | null,
  task: TaskSummary | null
): AgentChainItem[] {
  if (!result || !task) {
    return [];
  }
  const model = recordValue(task.model_params);
  const geometry = recordValue(model?.geometry);
  const dimensions = recordValue(geometry?.dimensions);
  const material = recordValue(model?.material);
  const mesh = recordValue(model?.mesh);
  const loads = arrayValue(model?.loads).map(recordValue).filter(isRecord);
  const bcs = arrayValue(model?.bcs).map(recordValue).filter(isRecord);
  const postSummary = recordValue(task.post_summary);
  const solver = task.solver_result;
  const solverTrace = traceValue(recordValue(solver)?.solver_llm_trace);
  const postTrace = traceValue(postSummary?.postproc_llm_trace);
  const analystTrace = traceValue(postSummary?.analyst_llm_trace);

  return [
    {
      key: "planner",
      label: "Planner",
      summary: plannerSummary(task),
      tone: agentTone(result, task, "planner", Boolean(task.intent || task.capability_id)),
      details: [
        { label: "任务", value: task.task_id || "N/A" },
        { label: "能力", value: task.capability_id || "N/A" },
        { label: "几何", value: intentGeometryLabel(task) },
        { label: "缺参", value: missingFieldLabel(task) }
      ],
      trace: task.planner_llm_trace
    },
    {
      key: "designer",
      label: "Designer",
      summary: model ? geometryLabel(geometry, dimensions) : "参数模型待生成",
      tone: agentTone(result, task, "designer", Boolean(model)),
      details: [
        { label: "模型", value: textValue(model?.case_id, task.case_id || "N/A") },
        { label: "材料", value: materialLabel(material) },
        { label: "载荷", value: loadLabel(loads[0]) },
        { label: "边界", value: boundaryLabel(bcs[0], bcs.length) }
      ],
      trace: task.designer_llm_trace
    },
    {
      key: "mesh",
      label: "MeshAgent",
      summary: meshAgentSummary(task),
      tone: meshAgentTone(result, task),
      details: [
        { label: "策略", value: meshLabel(mesh, task.mesh_result ?? null) },
        { label: "质量", value: meshQualityLabel(task.mesh_result ?? null) },
        { label: "来源", value: meshSourceLabel(task.mesh_result ?? null) },
        { label: "诊断", value: task.mesh_result?.error_message || "通过质量门禁" }
      ],
      trace: task.mesh_llm_trace
    },
    {
      key: "solver",
      label: "SolverAgent",
      summary: solver ? solverResultLabel(solver) : "求解结果待生成",
      tone: solverAgentTone(result, task),
      details: [
        { label: "求解器", value: solver?.solver || "N/A" },
        { label: "模型", value: solver?.model_case_id || task.case_id || "N/A" },
        { label: "结果", value: solver ? solverResultLabel(solver) : "N/A" },
        { label: "文件", value: `${solver?.output_files?.length ?? 0} 个` }
      ],
      trace: solverTrace
    },
    {
      key: "postproc",
      label: "PostProc",
      summary: postSummary ? postSummaryLabel(postSummary) : "后处理摘要待生成",
      tone: agentTone(result, task, "postproc", Boolean(postSummary)),
      details: postSummaryDetails(postSummary),
      trace: postTrace
    },
    {
      key: "analyst",
      label: "Analyst",
      summary: analystSummary(task),
      tone: analystTone(result, task),
      details: [
        { label: "状态", value: taskStatus(task).label },
        { label: "参考", value: referenceLabel(solver) },
        { label: "误差", value: taskRelativeError(task) },
        { label: "阈值", value: toleranceLabel(solver) }
      ],
      trace: analystTrace
    },
    {
      key: "reporter",
      label: "Reporter",
      summary: result.report ? "Markdown 工程报告已生成" : "报告待生成",
      tone: summaryHasStageError(result, "reporter") ? "bad" : result.report ? "ok" : "warn",
      details: [
        { label: "报告", value: result.summary.report_path || "内存报告" },
        { label: "字数", value: `${result.report.length} 字符` },
        { label: "产物", value: result.summary.work_dir || "N/A" }
      ],
      trace: result.summary.reporter_llm_trace
    }
  ];
}

function agentTone(
  result: StudioRunResponse,
  task: TaskSummary,
  stage: StageKey,
  ready: boolean
): AgentChainTone {
  if (taskHasStageError(task, stage) || summaryHasStageError(result, stage)) {
    return "bad";
  }
  if (ready) {
    return "ok";
  }
  return result.success ? "warn" : "neutral";
}

function meshAgentTone(result: StudioRunResponse, task: TaskSummary): AgentChainTone {
  if (taskHasStageError(task, "mesh") || summaryHasStageError(result, "mesh")) {
    return "bad";
  }
  if (task.mesh_result?.success === false) {
    return "bad";
  }
  if (task.mesh_result?.success === true) {
    return "ok";
  }
  return "warn";
}

function solverAgentTone(result: StudioRunResponse, task: TaskSummary): AgentChainTone {
  if (taskHasStageError(task, "solver") || summaryHasStageError(result, "solver")) {
    return "bad";
  }
  if (task.solver_result?.success === false) {
    return "bad";
  }
  if (task.solver_result?.success === true) {
    return "ok";
  }
  return result.success ? "warn" : "neutral";
}

function analystTone(result: StudioRunResponse, task: TaskSummary): AgentChainTone {
  if (taskHasStageError(task, "analyst") || summaryHasStageError(result, "analyst")) {
    return "bad";
  }
  return taskStatus(task).tone;
}

function taskHasStageError(task: TaskSummary, stage: StageKey) {
  return normalizeErrorNode(task.error) === stage;
}

function summaryHasStageError(result: StudioRunResponse, stage: StageKey) {
  return (result.summary.errors ?? []).some((error) => normalizeErrorNode(error) === stage);
}

function plannerSummary(task: TaskSummary) {
  const parts = [
    task.capability_id || task.case_id || "能力待定",
    task.analysis_type || "",
    missingFieldLabel(task) !== "-" ? `缺参 ${missingFieldLabel(task)}` : ""
  ].filter(Boolean);
  return parts.join(" · ");
}

function intentGeometryLabel(task: TaskSummary) {
  const intent = recordValue(task.intent);
  return textValue(intent?.geometry_type, textValue(intent?.geometry, "N/A"));
}

function missingFieldLabel(task: TaskSummary) {
  const intent = recordValue(task.intent);
  const fields = [
    ...arrayValue(intent?.missing_fields).map((value) => textValue(value, "")),
    ...(task.error?.missing_fields ?? [])
  ].filter(Boolean);
  const uniqueFields = uniqueStrings(fields);
  return uniqueFields.length > 0 ? uniqueFields.join("、") : "-";
}

function meshAgentSummary(task: TaskSummary) {
  const mesh = task.mesh_result;
  if (!mesh) {
    return "网格待生成";
  }
  const count = meshCountLabel(mesh);
  const quality = meshQualityLabel(mesh);
  return `${count}${quality !== "N/A" ? ` · ${quality}` : ""}`;
}

function meshCountLabel(mesh: NonNullable<TaskSummary["mesh_result"]>) {
  const metadata = recordValue(mesh.metadata);
  const nodes = finiteNumberValue(mesh.node_count) ?? finiteNumberValue(metadata?.node_count);
  const elements =
    finiteNumberValue(mesh.element_count) ?? finiteNumberValue(metadata?.element_count);
  if (nodes !== null && elements !== null) {
    return `${formatNumber(nodes)} 节点 / ${formatNumber(elements)} 单元`;
  }
  return "网格数量待记录";
}

function meshQualityLabel(mesh: TaskSummary["mesh_result"] | null) {
  if (!mesh) {
    return "N/A";
  }
  const entries = qualityEntries(mesh.quality);
  const minEntry = entries.filter(([key]) => key.startsWith("min_")).sort((a, b) => a[1] - b[1])[0];
  if (!minEntry) {
    return "未记录质量指标";
  }
  const meanSicn = entries.find(([key]) => key === "mean_sicn")?.[1];
  const meanText = meanSicn !== undefined ? `，mean_sicn=${formatNumber(meanSicn)}` : "";
  return `${minEntry[0]}=${formatNumber(minEntry[1])}${meanText}`;
}

function qualityEntries(quality: Record<string, number> | undefined) {
  if (!quality) {
    return [];
  }
  return Object.entries(quality).flatMap(([key, value]) =>
    Number.isFinite(value) ? ([[key, value]] as Array<[string, number]>) : []
  );
}

function meshSourceLabel(mesh: TaskSummary["mesh_result"] | null) {
  const metadata = recordValue(mesh?.metadata);
  return textValue(metadata?.source, "N/A");
}

function solverResultLabel(solver: NonNullable<TaskSummary["solver_result"]>) {
  const value =
    solver.predicted !== undefined && solver.predicted !== null
      ? `${formatNumber(solver.predicted)} ${solver.unit ?? ""}`.trim()
      : "N/A";
  return `${solver.quantity || "result"}=${value}`;
}

function postSummaryLabel(postSummary: Record<string, unknown>) {
  const scalars = recordValue(postSummary.scalars);
  const scalarKeys = scalars ? Object.keys(scalars) : [];
  if (scalarKeys.length > 0) {
    return `标量 ${scalarKeys.slice(0, 3).join("、")}`;
  }
  return `字段 ${Object.keys(postSummary).length} 项`;
}

function postSummaryDetails(postSummary: Record<string, unknown> | null): DisplayItem[] {
  if (!postSummary) {
    return [{ label: "摘要", value: "N/A" }];
  }
  const scalars = recordValue(postSummary.scalars);
  const scalarItems = scalars
    ? Object.entries(scalars)
        .slice(0, 4)
        .map(([key, value]) => ({ label: key, value: formatUnknownScalar(value) }))
    : [];
  if (scalarItems.length > 0) {
    return scalarItems;
  }
  return Object.entries(postSummary)
    .filter(([key]) => !key.endsWith("_llm_trace"))
    .slice(0, 4)
    .map(([key, value]) => ({ label: key, value: compactScalar(value) }));
}

function formatUnknownScalar(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return formatNumber(value);
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? formatNumber(parsed) : value.trim();
  }
  return "N/A";
}

function compactScalar(value: unknown) {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return formatNumber(value);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (Array.isArray(value)) {
    return `${value.length} 项`;
  }
  if (isRecord(value)) {
    return `${Object.keys(value).length} 项`;
  }
  return "N/A";
}

function analystSummary(task: TaskSummary) {
  const status = taskStatus(task);
  const relative = taskRelativeError(task);
  return relative === "N/A" ? status.label : `${status.label} · 误差 ${relative}`;
}

function referenceLabel(solver: TaskSummary["solver_result"] | undefined) {
  if (!solver || solver.reference === undefined || solver.reference === null) {
    return "N/A";
  }
  return `${formatNumber(solver.reference)} ${solver.unit ?? ""}`.trim();
}

function toleranceLabel(solver: TaskSummary["solver_result"] | undefined) {
  if (!solver || solver.tolerance === undefined || solver.tolerance === null) {
    return "N/A";
  }
  return PERCENT_FORMATTER.format(solver.tolerance);
}

function traceValue(value: unknown): AgentTrace | null {
  if (!isRecord(value)) {
    return null;
  }
  if (typeof value.agent !== "string" || typeof value.used !== "boolean") {
    return null;
  }
  return {
    agent: value.agent,
    used: value.used,
    error: typeof value.error === "string" ? value.error : null,
    prompt_chars: finiteNumberValue(value.prompt_chars) ?? 0,
    response_chars: finiteNumberValue(value.response_chars) ?? 0
  };
}

export function agentTraceDetails(trace: AgentTrace | null | undefined): DisplayItem[] {
  if (!trace) {
    return [{ label: "LLM", value: "未记录" }];
  }
  const state = trace.used ? (trace.error ? "调用失败" : "已调用") : "未调用";
  const details = [
    { label: "LLM", value: state },
    { label: "Agent", value: trace.agent },
    { label: "字符", value: `${trace.prompt_chars}/${trace.response_chars}` }
  ];
  if (trace.error) {
    details.push({ label: "错误", value: trace.error });
  }
  return details;
}

export function agentChainToneLabel(tone: AgentChainTone) {
  if (tone === "ok") {
    return "通过";
  }
  if (tone === "warn") {
    return "注意";
  }
  if (tone === "bad") {
    return "失败";
  }
  return "等待";
}
