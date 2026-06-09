import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node
} from "@xyflow/react";
import {
  AlertTriangle,
  Boxes,
  Brain,
  CheckCircle2,
  Copy,
  Database,
  Download,
  FileJson,
  FileText,
  Gauge,
  LoaderCircle,
  Play,
  Route,
  Settings2,
  Workflow
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  StageKey,
  StageState,
  StudioHealth,
  StudioRunResponse,
  TaskError,
  TaskSummary,
  Visualization,
  WorkflowSummary
} from "./types";

const EXAMPLES = [
  "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应",
  "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力的静力响应",
  "求解长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力的静力响应",
  "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
];

const STAGES: Array<{ key: StageKey; label: string; caption: string }> = [
  { key: "planner", label: "Planner", caption: "意图与任务拆解" },
  { key: "designer", label: "Designer", caption: "结构化建模参数" },
  { key: "mesh", label: "MeshAgent", caption: "网格与质量检查" },
  { key: "solver", label: "SolverAgent", caption: "求解器执行" },
  { key: "postproc", label: "PostProcAgent", caption: "结果提取" },
  { key: "analyst", label: "AnalystAgent", caption: "工程校核" },
  { key: "reporter", label: "ReporterAgent", caption: "报告生成" }
];

const NODE_ORDER = STAGES.map((stage) => stage.key);

export function App() {
  const [request, setRequest] = useState(EXAMPLES[0]);
  const [useLlmAgents, setUseLlmAgents] = useState(false);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<StudioRunResponse | null>(null);
  const [health, setHealth] = useState<StudioHealth | null>(null);
  const [selectedTaskIndex, setSelectedTaskIndex] = useState(0);
  const [selectedVisualIndex, setSelectedVisualIndex] = useState(0);

  useEffect(() => {
    void fetch("/api/health")
      .then((response) => response.json())
      .then((data: StudioHealth) => {
        setHealth(data);
      })
      .catch(() => {
        setHealth(null);
      });
  }, []);

  const tasks = result?.summary.tasks ?? [];
  const selectedTask = tasks[selectedTaskIndex] ?? tasks[0] ?? null;
  const taskVisualizations = visualizationsForTask(
    result?.visualizations ?? [],
    selectedTask
  );
  const activeVisualization = taskVisualizations[selectedVisualIndex] ?? taskVisualizations[0];
  const metrics = metricItems(result, selectedTask);
  const artifacts = artifactPaths(result?.summary, selectedTask);
  const flow = useMemo(() => buildFlow(result, running), [result, running]);

  async function runSimulation() {
    const requestText = request.trim();
    if (!requestText) {
      setResult(runError("请求不能为空。"));
      return;
    }
    setRunning(true);
    setSelectedTaskIndex(0);
    setSelectedVisualIndex(0);
    try {
      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request: requestText,
          use_llm_agents: useLlmAgents
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(String(payload.detail ?? "请求失败。"));
      }
      setResult(payload as StudioRunResponse);
    } catch (error) {
      setResult(runError(error instanceof Error ? error.message : String(error)));
    } finally {
      setRunning(false);
    }
  }

  function selectTask(index: number) {
    setSelectedTaskIndex(index);
    setSelectedVisualIndex(0);
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">M</div>
          <div>
            <h1>MechAgent Studio</h1>
            <p>自然语言驱动的 CAE/FEA 多智能体工程工作台</p>
          </div>
        </div>
        <div className="topbar-actions">
          <StatusPill result={result} running={running} />
          <span className="config-pill" title={health?.config ?? ""}>
            <Settings2 size={16} />
            {health?.ok ? "配置已连接" : "等待服务"}
          </span>
        </div>
      </header>

      <div className="studio-grid">
        <aside className="command-panel">
          <SectionTitle icon={<Brain size={18} />} title="仿真请求" />
          <textarea
            value={request}
            onChange={(event) => setRequest(event.target.value)}
            spellCheck={false}
            aria-label="自然语言仿真请求"
          />
          <div className="run-bar">
            <label className="toggle">
              <input
                type="checkbox"
                checked={useLlmAgents}
                onChange={(event) => setUseLlmAgents(event.target.checked)}
              />
              <span>LLM Agent</span>
            </label>
            <button className="primary-action" disabled={running} onClick={runSimulation}>
              {running ? <LoaderCircle className="spin" size={18} /> : <Play size={18} />}
              <span>{running ? "运行中" : "运行仿真"}</span>
            </button>
          </div>

          <SectionTitle icon={<Route size={18} />} title="工程示例" />
          <div className="example-list">
            {EXAMPLES.map((example) => (
              <button key={example} onClick={() => setRequest(example)}>
                {example}
              </button>
            ))}
          </div>
        </aside>

        <main className="workbench">
          <div className="workbench-head">
            <div>
              <SectionTitle icon={<Boxes size={18} />} title="结果视口" />
              <p>{selectedTask?.title ?? "运行后显示模型、网格、结果和校核信息。"}</p>
            </div>
            <TaskTabs
              tasks={tasks}
              selectedIndex={selectedTaskIndex}
              onSelect={selectTask}
            />
          </div>

          <section className="visual-panel">
            <div className="visual-toolbar">
              <div className="view-tabs">
                {taskVisualizations.map((visual, index) => (
                  <button
                    key={`${visual.task_id}-${visual.kind}-${index}`}
                    className={index === selectedVisualIndex ? "active" : ""}
                    onClick={() => setSelectedVisualIndex(index)}
                  >
                    {visualTitle(visual)}
                  </button>
                ))}
              </div>
              <button
                className="icon-button"
                title="下载 SVG"
                disabled={!activeVisualization}
                onClick={() => downloadSvg(activeVisualization)}
              >
                <Download size={17} />
              </button>
            </div>
            <div className="visual-canvas">
              {activeVisualization ? (
                <>
                  <div
                    className="svg-stage"
                    dangerouslySetInnerHTML={{ __html: activeVisualization.svg }}
                  />
                  <p className="caption">{activeVisualization.caption}</p>
                </>
              ) : (
                <EmptyState
                  icon={<Boxes size={28} />}
                  title="等待仿真结果"
                  text="运行后显示由求解摘要、网格文件和位移场生成的工程可视化。"
                />
              )}
            </div>
          </section>

          <section className="report-panel">
            <div className="panel-head">
              <SectionTitle icon={<FileText size={18} />} title="工程报告" />
              <button
                className="icon-button"
                title="复制报告"
                disabled={!result?.report}
                onClick={() => void navigator.clipboard?.writeText(result?.report ?? "")}
              >
                <Copy size={17} />
              </button>
            </div>
            <div className="markdown-body">
              {result?.report ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.report}</ReactMarkdown>
              ) : (
                <p>运行后显示 Markdown 工程报告。</p>
              )}
            </div>
          </section>
        </main>

        <aside className="inspector">
          <section className="inspector-section flow-section">
            <SectionTitle icon={<Workflow size={18} />} title="Agent DAG" />
            <div className="flow-canvas">
              <ReactFlow
                nodes={flow.nodes}
                edges={flow.edges}
                fitView
                fitViewOptions={{ padding: 0.18 }}
                nodesDraggable={false}
                nodesConnectable={false}
                elementsSelectable={false}
                proOptions={{ hideAttribution: true }}
              >
                <Background gap={18} size={1} />
                <Controls showInteractive={false} />
              </ReactFlow>
            </div>
          </section>

          <section className="inspector-section">
            <SectionTitle icon={<Gauge size={18} />} title="关键指标" />
            <div className="metric-list">
              {metrics.map((metric) => (
                <div className="metric-row" key={metric.label}>
                  <span>{metric.label}</span>
                  <strong>{metric.value}</strong>
                </div>
              ))}
            </div>
          </section>

          <section className="inspector-section">
            <SectionTitle icon={<Database size={18} />} title="阶段产物" />
            <div className="artifact-list">
              {artifacts.length > 0 ? (
                artifacts.map((artifact) => <code key={artifact}>{artifact}</code>)
              ) : (
                <p>运行后显示报告、网格和求解器产物路径。</p>
              )}
            </div>
          </section>

          <section className="inspector-section">
            <SectionTitle icon={<FileJson size={18} />} title="摘要 JSON" />
            <pre className="json-view">
              {result ? JSON.stringify(result.summary, null, 2) : "{}"}
            </pre>
          </section>
        </aside>
      </div>
    </div>
  );
}

function SectionTitle({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="section-title">
      {icon}
      <h2>{title}</h2>
    </div>
  );
}

function StatusPill({
  result,
  running
}: {
  result: StudioRunResponse | null;
  running: boolean;
}) {
  if (running) {
    return (
      <span className="status-pill running">
        <LoaderCircle className="spin" size={16} />
        运行中
      </span>
    );
  }
  if (!result) {
    return <span className="status-pill idle">待运行</span>;
  }
  return (
    <span className={`status-pill ${result.success ? "ok" : "bad"}`}>
      {result.success ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
      {result.success ? "通过" : "未通过"}
    </span>
  );
}

function TaskTabs({
  tasks,
  selectedIndex,
  onSelect
}: {
  tasks: TaskSummary[];
  selectedIndex: number;
  onSelect: (index: number) => void;
}) {
  if (tasks.length === 0) {
    return <div className="task-tabs empty-tabs">无任务</div>;
  }
  return (
    <div className="task-tabs">
      {tasks.map((task, index) => (
        <button
          key={task.task_id}
          className={index === selectedIndex ? "active" : ""}
          onClick={() => onSelect(index)}
        >
          {task.task_id}
        </button>
      ))}
    </div>
  );
}

function EmptyState({
  icon,
  title,
  text
}: {
  icon: React.ReactNode;
  title: string;
  text: string;
}) {
  return (
    <div className="empty-state">
      {icon}
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}

function buildFlow(
  result: StudioRunResponse | null,
  running: boolean
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = STAGES.map((stage, index) => {
    const state = stageState(stage.key, result, running);
    return {
      id: stage.key,
      position: { x: (index % 2) * 215, y: Math.floor(index / 2) * 86 },
      data: {
        label: (
          <div className="flow-node-label">
            <span>{stage.label}</span>
            <small>{stage.caption}</small>
          </div>
        )
      },
      className: `flow-node is-${state}`
    };
  });
  const edges: Edge[] = STAGES.slice(0, -1).map((stage, index) => ({
    id: `${stage.key}-${STAGES[index + 1].key}`,
    source: stage.key,
    target: STAGES[index + 1].key,
    type: "smoothstep",
    markerEnd: { type: MarkerType.ArrowClosed },
    className: "flow-edge"
  }));
  return { nodes, edges };
}

function stageState(
  key: StageKey,
  result: StudioRunResponse | null,
  running: boolean
): StageState {
  if (running) {
    return "running";
  }
  if (!result) {
    return "idle";
  }
  const errorNode = firstErrorNode(result.summary);
  if (!errorNode) {
    return result.summary.tasks?.length ? "complete" : "idle";
  }
  if (key === "reporter" && result.report) {
    return "complete";
  }
  const errorIndex = NODE_ORDER.indexOf(errorNode);
  const currentIndex = NODE_ORDER.indexOf(key);
  if (errorNode === key) {
    return "failed";
  }
  if (errorIndex >= 0 && currentIndex > errorIndex) {
    return "idle";
  }
  return result.summary.tasks?.length ? "complete" : "idle";
}

function firstErrorNode(summary: WorkflowSummary): StageKey | null {
  const error = summary.errors?.[0] ?? summary.tasks?.find((task) => task.error)?.error;
  return normalizeErrorNode(error);
}

function normalizeErrorNode(error?: TaskError | null): StageKey | null {
  const node = error?.node;
  if (!node) {
    return null;
  }
  if (node === "postproc") {
    return "postproc";
  }
  if (NODE_ORDER.includes(node as StageKey)) {
    return node as StageKey;
  }
  return null;
}

function metricItems(result: StudioRunResponse | null, task: TaskSummary | null) {
  const solver = task?.solver_result;
  return [
    {
      label: "工作流状态",
      value: result ? (result.success ? "通过" : "未通过") : "待运行"
    },
    { label: "任务数", value: String(result?.summary.tasks?.length ?? 0) },
    { label: "模型编号", value: solver?.model_case_id || task?.case_id || "N/A" },
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
          ? `${(solver.relative_error * 100).toFixed(4)}%`
          : "N/A"
    },
    {
      label: "耗时",
      value:
        result?.metadata?.duration_ms !== undefined
          ? formatDuration(result.metadata.duration_ms)
          : "N/A"
    }
  ];
}

function artifactPaths(summary: WorkflowSummary | undefined, task: TaskSummary | null) {
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

function visualizationsForTask(visuals: Visualization[], task: TaskSummary | null) {
  if (!task) {
    return visuals;
  }
  const matched = visuals.filter((visual) => visual.task_id === task.task_id);
  return matched.length > 0 ? matched : visuals;
}

function visualTitle(visual: Visualization) {
  if (visual.kind === "beam") {
    return "梁变形";
  }
  if (visual.kind === "plate") {
    return "板云图";
  }
  if (visual.kind === "solid") {
    return "实体变形";
  }
  return visual.title || "可视化";
}

function downloadSvg(visual: Visualization | undefined) {
  if (!visual) {
    return;
  }
  const blob = new Blob([visual.svg], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${visual.task_id || "mechagent"}-${visual.kind}.svg`;
  link.click();
  URL.revokeObjectURL(url);
}

function runError(message: string): StudioRunResponse {
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

function formatNumber(value: number) {
  if (!Number.isFinite(value)) {
    return "N/A";
  }
  return value.toPrecision(6).replace(/\.?0+$/, "");
}

function formatDuration(ms: number) {
  if (!Number.isFinite(ms)) {
    return "N/A";
  }
  if (ms < 1000) {
    return `${ms} ms`;
  }
  return `${(ms / 1000).toFixed(2)} s`;
}
