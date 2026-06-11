import { lazy, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  ClipboardList,
  Copy,
  Database,
  Download,
  FileJson,
  FileText,
  Gauge,
  History,
  Layers3,
  LoaderCircle,
  Play,
  Ruler,
  Search,
  Settings2,
  Share2,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  Workflow
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type {
  StageKey,
  StageState,
  StudioCapabilitiesResponse,
  StudioExample,
  StudioExamplesResponse,
  StudioHealth,
  StudioInspectionResponse,
  StudioJobResponse,
  StudioProgressEvent,
  StudioRunResponse,
  StudioCapability,
  TaskError,
  TaskSummary,
  Visualization,
  WorkflowSummary
} from "./types";

const ThreeViewport = lazy(() =>
  import("./ThreeViewport").then((module) => ({ default: module.ThreeViewport }))
);

type Example = {
  tag: string;
  title: string;
  request: string;
};

type DisplayItem = {
  label: string;
  value: string;
};

type MetricItem = DisplayItem & {
  tone?: "neutral" | "ok" | "warn" | "bad";
};

type StageRow = {
  key: StageKey;
  label: string;
  caption: string;
  state: StageState;
  eventMessage: string;
  eventTime: string;
};

type SideTab = "examples" | "history" | "facts";
type ExampleFilter = "all" | "beam" | "plate" | "solid" | "hole";

type RunHistoryItem = {
  id: string;
  createdAt: string;
  request: string;
  result: StudioRunResponse;
};

type Notice = {
  id: number;
  message: string;
  tone: "ok" | "bad";
};

const HISTORY_STORAGE_KEY = "mechagent.studio.runHistory";
const MAX_HISTORY_ITEMS = 8;
const HISTORY_STORAGE_FALLBACK_ITEMS = 3;
const HISTORY_REPORT_CHAR_LIMIT = 24_000;
const HISTORY_UNDO_TIMEOUT_MS = 20_000;
const JOB_POLL_INTERVAL_MS = 700;
const INSPECTION_DEBOUNCE_MS = 420;
const URL_SYNC_DEBOUNCE_MS = 260;
const NOTICE_TIMEOUT_MS = 2800;
const REQUEST_QUERY_KEY = "request";
const LLM_QUERY_KEY = "llm";
const VIEW_QUERY_KEY = "view";
const AUTO_RUN_QUERY_KEY = "run";

const DEFAULT_REQUEST =
  "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应";

const DEFAULT_EXAMPLES: Example[] = [
  {
    tag: "梁",
    title: "悬臂梁 · 均布线载荷",
    request: DEFAULT_REQUEST
  },
  {
    tag: "梁",
    title: "悬臂梁 · 端部集中力",
    request:
      "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力的静力响应"
  },
  {
    tag: "板",
    title: "矩形板 · 均布压力",
    request:
      "求解长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力的静力响应"
  },
  {
    tag: "实体",
    title: "长方体 · 轴向拉伸",
    request: "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
  }
];

const STAGES: Array<{ key: StageKey; label: string; caption: string }> = [
  { key: "planner", label: "任务识别", caption: "需求拆分" },
  { key: "designer", label: "参数建模", caption: "结构化输入" },
  { key: "mesh", label: "网格生成", caption: "质量检查" },
  { key: "solver", label: "求解执行", caption: "CalculiX" },
  { key: "postproc", label: "结果提取", caption: "场量提取" },
  { key: "analyst", label: "工程校核", caption: "参考解验收" },
  { key: "reporter", label: "报告输出", caption: "Markdown" }
];

const RENDER_MODES = [
  { key: "geometry", label: "几何", caption: "参数化模型", icon: Boxes },
  { key: "mesh", label: "网格", caption: "单元拓扑", icon: Layers3 },
  { key: "result", label: "结果", caption: "位移云图", icon: Gauge }
] as const;
type RenderModeKey = (typeof RENDER_MODES)[number]["key"];
const EXAMPLE_FILTERS: Array<{ key: ExampleFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "beam", label: "梁" },
  { key: "plate", label: "板" },
  { key: "solid", label: "实体" },
  { key: "hole", label: "开孔" }
];

const NODE_ORDER = STAGES.map((stage) => stage.key);
const RESULT_RENDER_MODE_INDEX = RENDER_MODES.findIndex((mode) => mode.key === "result");
const NUMBER_FORMATTER = new Intl.NumberFormat(undefined, {
  maximumSignificantDigits: 6
});
const PERCENT_FORMATTER = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 4,
  minimumFractionDigits: 0,
  style: "percent"
});

export function App() {
  const autoRunRequested = useRef(initialAutoRunFromUrl());
  const autoRunStarted = useRef(false);
  const [request, setRequest] = useState(() => initialRequestFromUrl());
  const [capabilities, setCapabilities] = useState<StudioCapability[]>([]);
  const [catalogExamples, setCatalogExamples] = useState<StudioExample[]>([]);
  const [useParameterCompletion, setUseParameterCompletion] = useState(() =>
    initialParameterCompletionFromUrl()
  );
  const [running, setRunning] = useState(false);
  const [activeJob, setActiveJob] = useState<StudioJobResponse | null>(null);
  const [monitorTick, setMonitorTick] = useState(0);
  const [result, setResult] = useState<StudioRunResponse | null>(null);
  const [inspection, setInspection] = useState<StudioInspectionResponse | null>(null);
  const [inspectionRunning, setInspectionRunning] = useState(false);
  const [health, setHealth] = useState<StudioHealth | null>(null);
  const [selectedTaskIndex, setSelectedTaskIndex] = useState(0);
  const [selectedVisualIndex, setSelectedVisualIndex] = useState(0);
  const [selectedRenderModeIndex, setSelectedRenderModeIndex] = useState(() =>
    initialRenderModeIndexFromUrl()
  );
  const [selectedSideTab, setSelectedSideTab] = useState<SideTab>("examples");
  const [exampleFilter, setExampleFilter] = useState<ExampleFilter>("all");
  const [exampleQuery, setExampleQuery] = useState("");
  const [history, setHistory] = useState<RunHistoryItem[]>(() => loadRunHistory());
  const [activeHistoryId, setActiveHistoryId] = useState<string | null>(null);
  const [recentlyClearedHistory, setRecentlyClearedHistory] = useState<RunHistoryItem[] | null>(
    null
  );
  const [notice, setNotice] = useState<Notice | null>(null);
  const selectedRenderMode = RENDER_MODES[selectedRenderModeIndex] ?? RENDER_MODES[0];

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

  useEffect(() => {
    void fetch("/api/capabilities")
      .then((response) => response.json())
      .then((data: StudioCapabilitiesResponse) => {
        setCapabilities(Array.isArray(data.capabilities) ? data.capabilities : []);
      })
      .catch(() => {
        setCapabilities([]);
      });
  }, []);

  useEffect(() => {
    void fetch("/api/examples")
      .then((response) => response.json())
      .then((data: StudioExamplesResponse) => {
        setCatalogExamples(Array.isArray(data.examples) ? data.examples : []);
      })
      .catch(() => {
        setCatalogExamples([]);
      });
  }, []);

  useEffect(() => {
    if (!recentlyClearedHistory) {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => {
      setRecentlyClearedHistory(null);
    }, HISTORY_UNDO_TIMEOUT_MS);
    return () => window.clearTimeout(timeoutId);
  }, [recentlyClearedHistory]);

  useEffect(() => {
    if (!notice) {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => {
      setNotice((current) => (current?.id === notice.id ? null : current));
    }, NOTICE_TIMEOUT_MS);
    return () => window.clearTimeout(timeoutId);
  }, [notice]);

  useEffect(() => {
    if (!running) {
      return undefined;
    }
    const intervalId = window.setInterval(() => {
      setMonitorTick((current) => current + 1);
    }, 1000);
    return () => window.clearInterval(intervalId);
  }, [running]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      replaceStudioUrl(request, useParameterCompletion, selectedRenderMode.key);
    }, URL_SYNC_DEBOUNCE_MS);
    return () => window.clearTimeout(timeoutId);
  }, [request, selectedRenderMode.key, useParameterCompletion]);

  useEffect(() => {
    const requestText = request.trim();
    if (!requestText) {
      setInspection(null);
      setInspectionRunning(false);
      return undefined;
    }

    const controller = new AbortController();
    let cancelled = false;
    setInspectionRunning(true);
    const timeoutId = window.setTimeout(() => {
      void fetch("/api/inspect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request: requestText,
          use_llm_agents: false
        }),
        signal: controller.signal
      })
        .then((response) => response.json())
        .then((data: StudioInspectionResponse) => {
          if (!cancelled) {
            setInspection(data);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setInspection({
              success: false,
              ready: false,
              request: requestText,
              tasks: [],
              errors: [
                {
                  node: "studio",
                  code: "unknown_error",
                  message: "预检服务不可用。"
                }
              ]
            });
          }
        })
        .finally(() => {
          if (!cancelled) {
            setInspectionRunning(false);
          }
        });
    }, INSPECTION_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [request]);

  useEffect(() => {
    if (
      !autoRunRequested.current ||
      autoRunStarted.current ||
      running ||
      result ||
      !request.trim()
    ) {
      return;
    }
    autoRunStarted.current = true;
    removeAutoRunQuery();
    void runSimulation();
  }, [request, result, running]);

  const tasks = result?.summary.tasks ?? [];
  const examples = useMemo(
    () => displayExamples(catalogExamples, capabilities),
    [catalogExamples, capabilities]
  );
  const filteredExamples = useMemo(
    () => filterExamples(examples, exampleFilter, exampleQuery),
    [exampleFilter, exampleQuery, examples]
  );
  const selectedTask = tasks[selectedTaskIndex] ?? tasks[0] ?? null;
  const taskVisualizations = visualizationsForTask(
    result?.visualizations ?? [],
    selectedTask
  );
  const activeVisualization = taskVisualizations[selectedVisualIndex] ?? taskVisualizations[0];
  const downloadTitle = activeVisualization
    ? activeVisualization.scene
      ? "下载当前 3D PNG"
      : "下载当前 SVG"
    : "下载当前可视化";
  const stages = useMemo(
    () => buildStageRows(result, running, activeJob),
    [activeJob, result, running]
  );
  const eventLog = recentJobEvents(activeJob);
  const summaryJson = useMemo(
    () => (result ? JSON.stringify(result.summary, null, 2) : "{}"),
    [result]
  );
  const metrics = metricItems(result, selectedTask, running, activeJob, monitorTick);
  const verification = verificationItems(selectedTask);
  const facts = studyFacts(selectedTask);
  const artifacts = artifactPaths(result?.summary, selectedTask);
  const outcome = result ? runOutcome(result, selectedTask) : null;
  const cliCommand = useMemo(
    () => reproducibleCliCommand(request, useParameterCompletion, health?.python_executable),
    [health?.python_executable, request, useParameterCompletion]
  );
  const workspaceLink = useMemo(
    () => studioWorkspaceLink(request, useParameterCompletion, selectedRenderMode.key),
    [request, selectedRenderMode.key, useParameterCompletion]
  );
  const statusMessage = running
    ? "仿真运行中…"
    : outcome
      ? `仿真${outcome.label}`
      : "等待仿真";

  async function runSimulation() {
    const requestText = request.trim();
    if (!requestText) {
      setResult(runError("请输入结构、材料、边界和载荷信息。"));
      return;
    }
    setRunning(true);
    setActiveJob(null);
    setMonitorTick(0);
    setSelectedTaskIndex(0);
    setSelectedVisualIndex(0);
    setSelectedRenderModeIndex(0);
    try {
      const response = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request: requestText,
          use_llm_agents: useParameterCompletion
        })
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(String(payload.detail ?? "请求失败。"));
      }
      let job = payload as StudioJobResponse;
      setActiveJob(job);
      while (isActiveJob(job)) {
        await sleep(JOB_POLL_INTERVAL_MS);
        const jobResponse = await fetch(`/api/jobs/${job.job_id}`);
        const jobPayload = await jobResponse.json();
        if (!jobResponse.ok) {
          throw new Error(String(jobPayload.detail ?? "作业状态读取失败。"));
        }
        job = jobPayload as StudioJobResponse;
        setActiveJob(job);
      }
      if (!job.result) {
        throw new Error(job.error ?? "作业结束但没有可用结果。");
      }
      const runResult = job.result;
      setResult(runResult);
      setSelectedRenderModeIndex(defaultRenderModeIndex(runResult));
      recordRun(requestText, runResult);
    } catch (error) {
      const failedResult = runError(error instanceof Error ? error.message : String(error));
      setResult(failedResult);
      setSelectedRenderModeIndex(0);
      recordRun(requestText, failedResult);
    } finally {
      setRunning(false);
    }
  }

  function recordRun(requestText: string, runResult: StudioRunResponse) {
    const item = createHistoryItem(requestText, runResult);
    setActiveHistoryId(item.id);
    setHistory((current) => saveRunHistory([item, ...current].slice(0, MAX_HISTORY_ITEMS)));
  }

  function selectTask(index: number) {
    setSelectedTaskIndex(index);
    setSelectedVisualIndex(0);
    setSelectedRenderModeIndex(defaultRenderModeIndex(result, tasks[index] ?? null));
  }

  function selectHistoryItem(item: RunHistoryItem) {
    setRequest(item.request);
    setResult(item.result);
    setActiveJob(null);
    setActiveHistoryId(item.id);
    setSelectedTaskIndex(0);
    setSelectedVisualIndex(0);
    setSelectedRenderModeIndex(defaultRenderModeIndex(item.result));
  }

  function clearHistory() {
    if (history.length === 0) {
      return;
    }
    setRecentlyClearedHistory(history);
    setHistory(saveRunHistory([]));
    setActiveHistoryId(null);
  }

  function restoreHistory() {
    if (!recentlyClearedHistory) {
      return;
    }
    setHistory(saveRunHistory(recentlyClearedHistory));
    setRecentlyClearedHistory(null);
  }

  function showNotice(message: string, tone: Notice["tone"] = "ok") {
    setNotice({
      id: Date.now(),
      message,
      tone
    });
  }

  async function copyTextToClipboard(text: string, label: string) {
    if (!text) {
      return;
    }
    const copied = await writeClipboardText(text);
    if (copied) {
      showNotice(`已复制：${label}。`);
    } else {
      showNotice(`复制失败：${label}。请检查浏览器剪贴板权限。`, "bad");
    }
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-workbench">
        跳转到工作台
      </a>

      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            MA
          </div>
          <div className="brand-copy">
            <h1 translate="no">MechAgent Studio</h1>
            <p>开源 CAE/FEA 多智能体仿真工作台</p>
          </div>
        </div>
        <div className="topbar-actions" aria-live="polite" aria-label={statusMessage}>
          <StatusPill result={result} running={running} />
          <span className="utility-pill" title={health?.config ?? ""}>
            <Settings2 aria-hidden="true" size={16} />
            {health?.ok ? "本地服务已连接" : "服务检测中"}
          </span>
        </div>
      </header>

      <div className="toast-region" aria-live="polite" aria-atomic="true">
        {notice && (
          <div className={`toast-message tone-${notice.tone}`} role="status">
            {notice.message}
          </div>
        )}
      </div>

      <div className="studio-layout">
        <aside className="left-rail" aria-label="仿真输入">
          <section className="panel composer-panel">
            <PanelTitle icon={<ClipboardList size={18} />} title="工程请求" />
            <textarea
              value={request}
              onChange={(event) => setRequest(event.target.value)}
              name="simulation-request"
              autoComplete="off"
              inputMode="text"
              placeholder="例如：长1000mm悬臂梁，一端固支，端部向下1000N集中力…"
              spellCheck={false}
              aria-label="自然语言仿真请求"
            />
            <div className="composer-controls">
              <label className="switch-control">
                <input
                  type="checkbox"
                  checked={useParameterCompletion}
                  onChange={(event) => setUseParameterCompletion(event.target.checked)}
                />
                <span>参数补全</span>
              </label>
              <span className="text-counter">{request.trim().length} 字符</span>
            </div>
            <PreflightPanel inspection={inspection} loading={inspectionRunning} />
            <div className="composer-actions">
              <button
                className="primary-action"
                type="button"
                disabled={running}
                onClick={runSimulation}
              >
                {running ? (
                  <LoaderCircle aria-hidden="true" className="spin" size={18} />
                ) : (
                  <Play aria-hidden="true" size={18} />
                )}
                <span>{running ? "求解中…" : "运行仿真"}</span>
              </button>
              <button
                className="secondary-action"
                title="复制当前请求的 CLI 复现命令"
                type="button"
                aria-label="复制 CLI 复现命令"
                disabled={!request.trim()}
                onClick={() => void copyTextToClipboard(cliCommand, "CLI 复现命令")}
              >
                <Copy aria-hidden="true" size={16} />
                <span>CLI</span>
              </button>
              <button
                className="secondary-action icon-action"
                title="复制当前工作台链接"
                type="button"
                aria-label="复制当前工作台链接"
                disabled={!request.trim()}
                onClick={() => void copyTextToClipboard(workspaceLink, "工作台链接")}
              >
                <Share2 aria-hidden="true" size={16} />
              </button>
            </div>
          </section>

          <section className="panel side-panel">
            <div className="side-tabs" role="tablist" aria-label="输入辅助面板">
              <button
                className={selectedSideTab === "examples" ? "active" : ""}
                type="button"
                role="tab"
                aria-selected={selectedSideTab === "examples"}
                onClick={() => setSelectedSideTab("examples")}
              >
                <SlidersHorizontal aria-hidden="true" size={15} />
                工况
              </button>
              <button
                className={selectedSideTab === "history" ? "active" : ""}
                type="button"
                role="tab"
                aria-selected={selectedSideTab === "history"}
                onClick={() => setSelectedSideTab("history")}
              >
                <History aria-hidden="true" size={15} />
                历史
              </button>
              <button
                className={selectedSideTab === "facts" ? "active" : ""}
                type="button"
                role="tab"
                aria-selected={selectedSideTab === "facts"}
                onClick={() => setSelectedSideTab("facts")}
              >
                <Ruler aria-hidden="true" size={15} />
                摘要
              </button>
            </div>

            <div className="side-panel-body">
              {selectedSideTab === "examples" && (
                <ExampleList
                  examples={filteredExamples}
                  totalCount={examples.length}
                  filter={exampleFilter}
                  query={exampleQuery}
                  onFilterChange={setExampleFilter}
                  onQueryChange={setExampleQuery}
                  onSelect={setRequest}
                />
              )}
              {selectedSideTab === "history" && (
                <HistoryList
                  activeHistoryId={activeHistoryId}
                  history={history}
                  recentlyClearedCount={recentlyClearedHistory?.length ?? 0}
                  onClear={clearHistory}
                  onUndoClear={restoreHistory}
                  onSelect={selectHistoryItem}
                />
              )}
              {selectedSideTab === "facts" && <FactList facts={facts} />}
            </div>
          </section>
        </aside>

        <main className="workspace" id="main-workbench">
          <section className="panel visual-panel">
            <div className="panel-header">
              <div>
                <PanelTitle icon={<Layers3 size={18} />} title="结果视口" />
                <p>{selectedTask?.title ?? "等待仿真任务"}</p>
              </div>
              <TaskTabs tasks={tasks} selectedIndex={selectedTaskIndex} onSelect={selectTask} />
            </div>

            <div className="viewport-toolbar">
              <div className="view-tabs" role="tablist" aria-label="三维视图模式">
                {RENDER_MODES.map((mode, index) => {
                  const Icon = mode.icon;
                  return (
                    <button
                      key={mode.key}
                      className={index === selectedRenderModeIndex ? "active" : ""}
                      type="button"
                      role="tab"
                      aria-selected={index === selectedRenderModeIndex}
                      title={mode.caption}
                      onClick={() => setSelectedRenderModeIndex(index)}
                    >
                      <Icon aria-hidden="true" size={15} />
                      {mode.label}
                    </button>
                  );
                })}
              </div>
              <button
                className="icon-button"
                title={downloadTitle}
                type="button"
                aria-label={downloadTitle}
                disabled={!activeVisualization}
                onClick={() => downloadVisualization(activeVisualization, selectedRenderMode.key)}
              >
                <Download aria-hidden="true" size={17} />
              </button>
            </div>

            <div className="visual-canvas">
              {activeVisualization ? (
                <>
                  {activeVisualization.scene ? (
                    <Suspense
                      fallback={
                        <div className="three-loading" aria-label="3D 视图加载中">
                          <LoaderCircle aria-hidden="true" className="spin" size={18} />
                        </div>
                      }
                    >
                      <ThreeViewport
                        scene={activeVisualization.scene}
                        mode={selectedRenderMode.key}
                      />
                    </Suspense>
                  ) : (
                    <div
                      className="svg-stage"
                      role="img"
                      aria-label={`${activeVisualization.title}：${activeVisualization.caption}`}
                      dangerouslySetInnerHTML={{ __html: activeVisualization.svg }}
                    />
                  )}
                  <p className="caption">{activeVisualization.caption}</p>
                </>
              ) : (
                <EmptyState
                  icon={<Boxes size={30} />}
                  title="等待结果场"
                  text="运行后展示由求解摘要、网格文件和位移场生成的工程视图。"
                />
              )}
            </div>
          </section>

          <section className="panel report-panel">
            <div className="panel-header">
              <PanelTitle icon={<FileText size={18} />} title="工程报告" />
              <div className="panel-actions">
                <button
                  className="icon-button"
                  title="下载报告"
                  type="button"
                  aria-label="下载 Markdown 工程报告"
                  disabled={!result?.report}
                  onClick={() => downloadReport(result, selectedTask)}
                >
                  <Download aria-hidden="true" size={17} />
                </button>
                <button
                  className="icon-button"
                  title="复制报告"
                  type="button"
                  aria-label="复制 Markdown 工程报告"
                  disabled={!result?.report}
                  onClick={() =>
                    void copyTextToClipboard(result?.report ?? "", "Markdown 工程报告")
                  }
                >
                  <Copy aria-hidden="true" size={17} />
                </button>
              </div>
            </div>
            <ResultMatrix tasks={tasks} selectedIndex={selectedTaskIndex} onSelect={selectTask} />
            <div className="markdown-body">
              {result?.report ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.report}</ReactMarkdown>
              ) : (
                <CompactEmpty text="运行后显示可发布的 Markdown 工程报告。" />
              )}
            </div>
          </section>
        </main>

        <aside className={`right-rail ${result ? "has-result" : ""}`} aria-label="仿真检查器">
          <section className={`panel verification-panel ${result ? "has-result" : ""}`}>
            <PanelTitle icon={<ShieldCheck size={18} />} title="验收状态" />
            <Verdict
              clockTick={monitorTick}
              job={activeJob}
              result={result}
              running={running}
              task={selectedTask}
            />
            <div className="metric-grid">
              {metrics.map((metric) => (
                <div className={`metric-card tone-${metric.tone ?? "neutral"}`} key={metric.label}>
                  <span>{metric.label}</span>
                  <strong>{metric.value}</strong>
                </div>
              ))}
            </div>
            {verification.length > 0 && (
              <dl className="verification-list">
                {verification.map((item) => (
                  <div key={item.label}>
                    <dt>{item.label}</dt>
                    <dd>{item.value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </section>

          <section className="panel flow-panel">
            <PanelTitle icon={<Workflow size={18} />} title="求解流程" />
            <WorkflowSteps stages={stages} />
          </section>

          <section className="panel artifacts-panel">
            <PanelTitle icon={<Database size={18} />} title="阶段产物" />
            {artifacts.length > 0 ? (
              <ArtifactList
                artifacts={artifacts}
                onCopy={(artifact, label) =>
                  void copyTextToClipboard(artifact, `${label}产物路径`)
                }
              />
            ) : (
              <CompactEmpty text="运行后显示报告、网格和求解器输出路径。" />
            )}
          </section>

          <section className="panel json-panel">
            <details>
              <summary>
                <FileJson aria-hidden="true" size={18} />
                摘要 JSON
              </summary>
              <div className="json-actions">
                <button
                  className="icon-button"
                  title="下载 JSON"
                  type="button"
                  aria-label="下载摘要 JSON"
                  disabled={!result}
                  onClick={() => downloadSummaryJson(result, selectedTask, summaryJson)}
                >
                  <Download aria-hidden="true" size={16} />
                </button>
                <button
                  className="icon-button"
                  title="复制 JSON"
                  type="button"
                  aria-label="复制摘要 JSON"
                  disabled={!result}
                  onClick={() => void copyTextToClipboard(summaryJson, "摘要 JSON")}
                >
                  <Copy aria-hidden="true" size={16} />
                </button>
              </div>
              <EventLog events={eventLog} />
              <pre className="json-view">{summaryJson}</pre>
            </details>
          </section>
        </aside>
      </div>
    </div>
  );
}

function PanelTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="panel-title">
      <span aria-hidden="true">{icon}</span>
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
        <LoaderCircle aria-hidden="true" className="spin" size={16} />
        求解中…
      </span>
    );
  }
  if (!result) {
    return <span className="status-pill idle">待运行</span>;
  }
  const outcome = runOutcome(result);
  return (
    <span className={`status-pill ${outcome.tone}`}>
      {outcome.tone === "ok" ? (
        <CheckCircle2 aria-hidden="true" size={16} />
      ) : outcome.tone === "warn" ? (
        <Gauge aria-hidden="true" size={16} />
      ) : (
        <AlertTriangle aria-hidden="true" size={16} />
      )}
      {outcome.label}
    </span>
  );
}

function PreflightPanel({
  inspection,
  loading
}: {
  inspection: StudioInspectionResponse | null;
  loading: boolean;
}) {
  const firstTask = inspection?.tasks[0];
  const missingFields = inspection?.tasks.flatMap((task) => task.missing_fields) ?? [];
  const capabilitySummary = summaryLabel(
    inspection?.tasks.map((task) => task.capability_id).filter(Boolean) ?? []
  );
  const geometrySummary = summaryLabel(
    inspection?.tasks.map((task) => task.geometry_type ?? "").filter(Boolean) ?? []
  );
  const errors = inspection?.errors ?? [];
  const tone = loading ? "running" : inspection?.ready ? "ok" : "warn";
  const statusText = loading
    ? "识别中"
    : inspection?.ready
      ? "可执行"
      : inspection?.success
        ? "需补充"
        : inspection
          ? "待修正"
          : "待输入";

  return (
    <section className={`preflight-card tone-${tone}`} aria-label="任务预检" aria-live="polite">
      <div className="preflight-head">
        <span>任务预检</span>
        <strong>
          {loading && <LoaderCircle aria-hidden="true" className="spin" size={13} />}
          {statusText}
        </strong>
      </div>
      <div className="preflight-grid">
        <PreflightItem label="任务" value={String(inspection?.tasks.length ?? 0)} />
        <PreflightItem label="能力" value={capabilitySummary || firstTask?.capability_id || "-"} />
        <PreflightItem label="几何" value={geometrySummary || firstTask?.geometry_type || "-"} />
        <PreflightItem
          label="缺项"
          value={missingFields.length > 0 ? uniqueStrings(missingFields).join("、") : "-"}
        />
      </div>
      {errors.length > 0 && <p className="preflight-error">{errors[0]?.message}</p>}
    </section>
  );
}

function PreflightItem({ label, value }: DisplayItem) {
  return (
    <span>
      <small>{label}</small>
      <b>{value}</b>
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
    <div className="task-tabs" role="tablist" aria-label="仿真任务">
      {tasks.map((task, index) => (
        <button
          key={task.task_id}
          className={index === selectedIndex ? "active" : ""}
          type="button"
          role="tab"
          aria-selected={index === selectedIndex}
          onClick={() => onSelect(index)}
        >
          {task.task_id}
        </button>
      ))}
    </div>
  );
}

function ResultMatrix({
  tasks,
  selectedIndex,
  onSelect
}: {
  tasks: TaskSummary[];
  selectedIndex: number;
  onSelect: (index: number) => void;
}) {
  if (tasks.length <= 1) {
    return <div className="result-matrix is-empty" aria-hidden="true" />;
  }
  return (
    <section className="result-matrix" aria-label="多任务结果矩阵">
      <div className="result-matrix-head" aria-hidden="true">
        <span>任务</span>
        <span>模型</span>
        <span>主结果</span>
        <span>相对误差</span>
        <span>状态</span>
      </div>
      <div className="result-matrix-rows">
        {tasks.map((task, index) => {
          const status = taskStatus(task);
          return (
            <button
              className={`result-row tone-${status.tone} ${index === selectedIndex ? "active" : ""}`}
              key={task.task_id || `${task.case_id}-${index}`}
              type="button"
              title={task.title}
              aria-current={index === selectedIndex ? "true" : undefined}
              onClick={() => onSelect(index)}
            >
              <span>{task.task_id || `TASK_${index + 1}`}</span>
              <span>{taskModelLabel(task)}</span>
              <span>{taskResultValue(task)}</span>
              <span>{taskRelativeError(task)}</span>
              <strong>{status.label}</strong>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function EmptyState({
  icon,
  title,
  text
}: {
  icon: ReactNode;
  title: string;
  text: string;
}) {
  return (
    <div className="empty-state">
      <span aria-hidden="true">{icon}</span>
      <strong>{title}</strong>
      <span>{text}</span>
    </div>
  );
}

function CompactEmpty({ text }: { text: string }) {
  return <p className="compact-empty">{text}</p>;
}

function ExampleList({
  examples,
  totalCount,
  filter,
  query,
  onFilterChange,
  onQueryChange,
  onSelect
}: {
  examples: Example[];
  totalCount: number;
  filter: ExampleFilter;
  query: string;
  onFilterChange: (filter: ExampleFilter) => void;
  onQueryChange: (query: string) => void;
  onSelect: (request: string) => void;
}) {
  return (
    <div className="example-panel">
      <div className="example-toolbar">
        <label className="example-search">
          <Search aria-hidden="true" size={15} />
          <input
            type="search"
            name="example-search"
            autoComplete="off"
            inputMode="search"
            placeholder="搜索工况、材料、载荷…"
            value={query}
            onChange={(event) => onQueryChange(event.target.value)}
            aria-label="搜索工况示例"
          />
        </label>
        <div className="example-filter" role="group" aria-label="工况筛选">
          {EXAMPLE_FILTERS.map((item) => (
            <button
              key={item.key}
              className={filter === item.key ? "active" : ""}
              type="button"
              aria-pressed={filter === item.key}
              onClick={() => onFilterChange(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <span className="example-count">
          {examples.length}/{totalCount} 个工况
        </span>
      </div>
      {examples.length > 0 ? (
        <div className="example-list">
          {examples.map((example) => (
            <button
              key={`${example.title}:${example.request}`}
              className="example-item"
              title={example.request}
              type="button"
              onClick={() => onSelect(example.request)}
            >
              <span>{example.tag}</span>
              <strong>{example.title}</strong>
              <small>{example.request}</small>
            </button>
          ))}
        </div>
      ) : (
        <CompactEmpty text="没有匹配工况。" />
      )}
    </div>
  );
}

function filterExamples(examples: Example[], filter: ExampleFilter, query: string) {
  const normalizedQuery = normalizeSearchText(query);
  return examples.filter((example) => {
    if (!exampleMatchesFilter(example, filter)) {
      return false;
    }
    if (!normalizedQuery) {
      return true;
    }
    return normalizeSearchText(`${example.tag} ${example.title} ${example.request}`).includes(
      normalizedQuery
    );
  });
}

function exampleMatchesFilter(example: Example, filter: ExampleFilter) {
  if (filter === "all") {
    return true;
  }
  const haystack = normalizeSearchText(`${example.tag} ${example.title} ${example.request}`);
  if (filter === "beam") {
    return haystack.includes("梁") || haystack.includes("beam");
  }
  if (filter === "plate") {
    return haystack.includes("板") || haystack.includes("plate");
  }
  if (filter === "solid") {
    return haystack.includes("实体") || haystack.includes("solid") || haystack.includes("block");
  }
  return (
    haystack.includes("开孔") ||
    haystack.includes("孔") ||
    haystack.includes("hole") ||
    haystack.includes("perforated")
  );
}

function normalizeSearchText(value: string) {
  return value.trim().toLocaleLowerCase("zh-CN");
}

function displayExamples(
  catalogExamples: StudioExample[],
  capabilities: StudioCapability[]
): Example[] {
  if (catalogExamples.length > 0) {
    return catalogExamples.map((example) => ({
      tag: catalogExampleTag(example),
      title: example.title,
      request: example.request
    }));
  }
  const examples = capabilities.flatMap((capability) =>
    capability.example_requests.map((requestText) => ({
      tag: exampleTag(capability, requestText),
      title: exampleTitle(capability, requestText),
      request: requestText
    }))
  );
  return examples.length > 0 ? examples : DEFAULT_EXAMPLES;
}

function catalogExampleTag(example: StudioExample) {
  const knownTag = example.tags.find((tag) =>
    ["梁", "板", "实体", "beam", "plate", "solid"].includes(tag)
  );
  if (knownTag === "beam") {
    return "梁";
  }
  if (knownTag === "plate") {
    return "板";
  }
  if (knownTag === "solid") {
    return "实体";
  }
  if (knownTag) {
    return knownTag;
  }
  if (example.geometry_type === "beam") {
    return "梁";
  }
  if (example.geometry_type === "plate") {
    return "板";
  }
  if (example.geometry_type === "solid") {
    return "实体";
  }
  return example.capability_id;
}

function exampleTag(capability: StudioCapability, requestText: string) {
  const text = requestText.toLowerCase();
  if (text.includes("beam") || requestText.includes("梁")) {
    return "梁";
  }
  if (text.includes("plate") || requestText.includes("板")) {
    return "板";
  }
  if (text.includes("solid") || requestText.includes("实体") || requestText.includes("长方体")) {
    return "实体";
  }
  return capability.physics_domain || capability.analysis_type || "能力";
}

function exampleTitle(capability: StudioCapability, requestText: string) {
  const text = requestText.toLowerCase();
  if (text.includes("beam") || requestText.includes("梁")) {
    return `${capability.title} · 梁`;
  }
  if (text.includes("plate") || requestText.includes("板")) {
    return `${capability.title} · 板`;
  }
  if (text.includes("solid") || requestText.includes("实体") || requestText.includes("长方体")) {
    return `${capability.title} · 实体`;
  }
  return capability.title;
}

function HistoryList({
  activeHistoryId,
  history,
  recentlyClearedCount,
  onClear,
  onUndoClear,
  onSelect
}: {
  activeHistoryId: string | null;
  history: RunHistoryItem[];
  recentlyClearedCount: number;
  onClear: () => void;
  onUndoClear: () => void;
  onSelect: (item: RunHistoryItem) => void;
}) {
  return (
    <>
      <div className="side-panel-actions">
        <span>{history.length > 0 ? `${history.length} 条记录` : "无历史记录"}</span>
        <button
          className="clear-history-button"
          title="清空历史"
          type="button"
          aria-label="清空运行历史"
          disabled={history.length === 0}
          onClick={onClear}
        >
          <Trash2 aria-hidden="true" size={16} />
          <span>清空</span>
        </button>
      </div>
      {recentlyClearedCount > 0 && (
        <div className="undo-clear" role="status" aria-live="polite">
          <span>已清空 {recentlyClearedCount} 条记录</span>
          <button type="button" onClick={onUndoClear}>
            恢复
          </button>
        </div>
      )}
      {history.length > 0 ? (
        <div className="history-list">
          {history.map((item) => (
            <button
              key={item.id}
              className={`history-item ${item.id === activeHistoryId ? "active" : ""}`}
              type="button"
              onClick={() => onSelect(item)}
            >
              <HistoryState result={item.result} />
              <strong>{historyTitle(item.result)}</strong>
              <small>{historyMeta(item)}</small>
              <span>{item.request}</span>
            </button>
          ))}
        </div>
      ) : (
        <CompactEmpty text="运行后显示最近结果，便于回看不同请求。" />
      )}
    </>
  );
}

function HistoryState({ result }: { result: StudioRunResponse }) {
  const outcome = runOutcome(result);
  return <span className={`history-state ${outcome.tone}`}>{outcome.label}</span>;
}

function FactList({ facts }: { facts: DisplayItem[] }) {
  if (facts.length === 0) {
    return <CompactEmpty text="运行后显示几何、材料、载荷和网格摘要。" />;
  }
  return (
    <dl className="fact-list">
      {facts.map((fact) => (
        <div key={fact.label}>
          <dt>{fact.label}</dt>
          <dd>{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function WorkflowSteps({
  stages
}: {
  stages: StageRow[];
}) {
  return (
    <ol className="workflow-steps" aria-label="求解流程阶段">
      {stages.map((stage, index) => (
        <li className={`workflow-step is-${stage.state}`} key={stage.key}>
          <span className="step-index">{index + 1}</span>
          <div>
            <strong>{stage.label}</strong>
            <small title={stage.eventMessage || stage.caption}>
              {stageCaption(stage)}
            </small>
          </div>
          <span className="step-state">{stageStateLabel(stage.state)}</span>
        </li>
      ))}
    </ol>
  );
}

function ArtifactList({
  artifacts,
  onCopy
}: {
  artifacts: string[];
  onCopy: (artifact: string, label: string) => void;
}) {
  return (
    <div className="artifact-list">
      {artifacts.map((artifact) => {
        const label = artifactLabel(artifact);
        return (
          <div className="artifact-item" key={artifact}>
            <span>{label}</span>
            <code title={artifact}>{artifact}</code>
            <button
              className="icon-button"
              title="复制路径"
              type="button"
              aria-label={`复制阶段产物路径：${label}`}
              onClick={() => onCopy(artifact, label)}
            >
              <Copy aria-hidden="true" size={15} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

function EventLog({ events }: { events: StudioProgressEvent[] }) {
  return (
    <details className="event-log">
      <summary className="event-log-head" aria-label="最近运行事件">
        <span>运行事件</span>
        <strong>{events.length > 0 ? `${events.length} 条` : "待记录"}</strong>
      </summary>
      {events.length > 0 ? (
        <ol>
          {events.map((event, index) => (
            <li className={`event-item is-${event.status}`} key={`${event.timestamp}-${index}`}>
              <span>{formatEventTime(event.timestamp)}</span>
              <strong title={event.message}>{event.message}</strong>
            </li>
          ))}
        </ol>
      ) : (
        <p>提交作业后显示后端阶段事件。</p>
      )}
    </details>
  );
}

function Verdict({
  clockTick,
  job,
  result,
  running,
  task
}: {
  clockTick: number;
  job: StudioJobResponse | null;
  result: StudioRunResponse | null;
  running: boolean;
  task: TaskSummary | null;
}) {
  const jobLine = job ? `${shortJobId(job.job_id)} · ${jobStatusLabel(job.status)}` : "作业准备中";
  const elapsed = jobElapsedLabel(job, running, clockTick);
  if (running) {
    return (
      <div className="verdict-card running">
        <LoaderCircle aria-hidden="true" className="spin" size={18} />
        <div>
          <strong>求解执行中</strong>
          <span>{jobLine}</span>
          <span>{elapsed ? `已运行 ${elapsed}` : "等待后端作业启动。"}</span>
          <span className="run-progress" aria-hidden="true" />
        </div>
      </div>
    );
  }
  if (!result) {
    return (
      <div className="verdict-card idle">
        <Gauge aria-hidden="true" size={18} />
        <div>
          <strong>等待运行</strong>
          <span>提交工程请求后开始验收。</span>
        </div>
      </div>
    );
  }
  const outcome = runOutcome(result, task);
  return (
    <div className={`verdict-card ${outcome.tone}`}>
      {outcome.tone === "ok" ? (
        <CheckCircle2 aria-hidden="true" size={18} />
      ) : outcome.tone === "warn" ? (
        <Gauge aria-hidden="true" size={18} />
      ) : (
        <AlertTriangle aria-hidden="true" size={18} />
      )}
      <div>
        <strong>{outcome.title}</strong>
        <span>{outcome.message}</span>
        {job && <span>{`${shortJobId(job.job_id)} · ${jobStatusLabel(job.status)}`}</span>}
      </div>
    </div>
  );
}

function buildStageRows(
  result: StudioRunResponse | null,
  running: boolean,
  job: StudioJobResponse | null
): StageRow[] {
  return STAGES.map((stage) => {
    const event = latestStageEvent(stage.key, job);
    return {
      ...stage,
      state: stageState(stage.key, result, running, job, event),
      eventMessage: event?.message ?? "",
      eventTime: event ? formatEventTime(event.timestamp) : ""
    };
  });
}

function stageCaption(stage: StageRow) {
  if (!stage.eventMessage) {
    return stage.caption;
  }
  return stage.eventTime ? `${stage.caption} · ${stage.eventTime}` : stage.caption;
}

function stageState(
  key: StageKey,
  result: StudioRunResponse | null,
  running: boolean,
  job: StudioJobResponse | null,
  event: StudioProgressEvent | null = latestStageEvent(key, job)
): StageState {
  const eventState = stageEventState(event);
  if (eventState) {
    return eventState;
  }
  if (running) {
    return "pending";
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

function stageStateLabel(state: StageState) {
  if (state === "complete") {
    return "完成";
  }
  if (state === "pending") {
    return "等待";
  }
  if (state === "running") {
    return "运行";
  }
  if (state === "failed") {
    return "失败";
  }
  return "等待";
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

function latestStageEvent(
  key: StageKey,
  job: StudioJobResponse | null
): StudioProgressEvent | null {
  if (!job?.events?.length) {
    return null;
  }
  const event = [...job.events].reverse().find((item) => item.stage === key);
  if (!event) {
    return null;
  }
  return event;
}

function stageEventState(event: StudioProgressEvent | null): StageState | null {
  if (!event) {
    return null;
  }
  if (event.status === "running") {
    return "running";
  }
  if (event.status === "complete") {
    return "complete";
  }
  return "failed";
}

function recentJobEvents(job: StudioJobResponse | null) {
  return [...(job?.events ?? [])].slice(-5).reverse();
}

function metricItems(
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

function verificationItems(task: TaskSummary | null): DisplayItem[] {
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

function taskStatus(task: TaskSummary): { label: string; tone: "neutral" | "ok" | "warn" | "bad" } {
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

function runOutcome(result: StudioRunResponse, task: TaskSummary | null = null) {
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

function taskModelLabel(task: TaskSummary) {
  const model = recordValue(task.model_params);
  const caseId = task.solver_result?.model_case_id || task.case_id || textValue(model?.case_id, "");
  const geometry = recordValue(model?.geometry);
  const geometryType = textValue(geometry?.type, "");
  if (caseId && geometryType) {
    return `${caseId} · ${geometryType}`;
  }
  return caseId || geometryType || task.title || "N/A";
}

function taskResultValue(task: TaskSummary) {
  const solver = task.solver_result;
  if (solver?.predicted === undefined || solver.predicted === null) {
    return "N/A";
  }
  return `${formatNumber(solver.predicted)} ${solver.unit ?? ""}`.trim();
}

function taskRelativeError(task: TaskSummary) {
  const solver = task.solver_result;
  if (solver?.relative_error === undefined || solver.relative_error === null) {
    return "N/A";
  }
  return PERCENT_FORMATTER.format(solver.relative_error);
}

function studyFacts(task: TaskSummary | null): DisplayItem[] {
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

function artifactLabel(path: string) {
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

function visualizationsForTask(visuals: Visualization[], task: TaskSummary | null) {
  if (!task) {
    return visuals;
  }
  const matched = visuals.filter((visual) => visual.task_id === task.task_id);
  return matched.length > 0 ? matched : visuals;
}

function defaultRenderModeIndex(
  runResult: StudioRunResponse | null,
  task: TaskSummary | null = null
) {
  if (!runResult?.success || RESULT_RENDER_MODE_INDEX < 0) {
    return 0;
  }
  const selectedTask = task ?? runResult.summary.tasks?.[0] ?? null;
  const visuals = visualizationsForTask(runResult.visualizations, selectedTask);
  return visuals.some((visual) => visual.scene?.has_real_results) ? RESULT_RENDER_MODE_INDEX : 0;
}

function downloadVisualization(
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

function downloadReport(runResult: StudioRunResponse | null, task: TaskSummary | null) {
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

function downloadSummaryJson(
  runResult: StudioRunResponse | null,
  task: TaskSummary | null,
  summaryJson: string
) {
  if (!runResult) {
    return;
  }
  const taskName = safeFileSegment(task?.task_id || runResult.summary.tasks?.[0]?.task_id || "summary");
  const statusName = runResult.success ? "passed" : "failed";
  const blob = new Blob([summaryJson], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `mechagent-${taskName}-${statusName}.json`;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

async function writeClipboardText(text: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // 浏览器原生命令作为复制回退路径。
    }
  }
  return legacyCopyText(text);
}

function legacyCopyText(text: string) {
  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "");
  textArea.style.position = "fixed";
  textArea.style.top = "-1000px";
  textArea.style.left = "-1000px";
  textArea.style.opacity = "0";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  try {
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(textArea);
  }
}

function safeFileSegment(value: string) {
  const normalized = value.trim().replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  return normalized || "report";
}

function initialRequestFromUrl() {
  if (typeof window === "undefined") {
    return DEFAULT_REQUEST;
  }
  const requestValue = new URLSearchParams(window.location.search).get(REQUEST_QUERY_KEY);
  return requestValue?.trim() || DEFAULT_REQUEST;
}

function initialParameterCompletionFromUrl() {
  if (typeof window === "undefined") {
    return false;
  }
  const value = new URLSearchParams(window.location.search).get(LLM_QUERY_KEY);
  return value === "1" || value?.toLowerCase() === "true";
}

function initialRenderModeIndexFromUrl() {
  if (typeof window === "undefined") {
    return 0;
  }
  const value = new URLSearchParams(window.location.search).get(VIEW_QUERY_KEY);
  const index = RENDER_MODES.findIndex((mode) => mode.key === value);
  return index >= 0 ? index : 0;
}

function initialAutoRunFromUrl() {
  if (typeof window === "undefined") {
    return false;
  }
  const value = new URLSearchParams(window.location.search).get(AUTO_RUN_QUERY_KEY);
  return value === "1" || value?.toLowerCase() === "true";
}

function studioWorkspaceLink(
  requestText: string,
  useLlmAgents: boolean,
  renderMode: RenderModeKey
) {
  if (typeof window === "undefined") {
    return "";
  }
  const url = new URL(window.location.href);
  applyWorkspaceQuery(url, requestText, useLlmAgents, renderMode);
  return url.toString();
}

function replaceStudioUrl(
  requestText: string,
  useLlmAgents: boolean,
  renderMode: RenderModeKey
) {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  applyWorkspaceQuery(url, requestText, useLlmAgents, renderMode);
  const nextPath = `${url.pathname}${url.search}${url.hash}`;
  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (nextPath !== currentPath) {
    window.history.replaceState(null, "", nextPath);
  }
}

function applyWorkspaceQuery(
  url: URL,
  requestText: string,
  useLlmAgents: boolean,
  renderMode: RenderModeKey
) {
  url.searchParams.delete(AUTO_RUN_QUERY_KEY);
  const requestValue = requestText.trim();
  if (requestValue && requestValue !== DEFAULT_REQUEST) {
    url.searchParams.set(REQUEST_QUERY_KEY, requestValue);
  } else {
    url.searchParams.delete(REQUEST_QUERY_KEY);
  }
  if (useLlmAgents) {
    url.searchParams.set(LLM_QUERY_KEY, "1");
  } else {
    url.searchParams.delete(LLM_QUERY_KEY);
  }
  if (RENDER_MODES.some((mode) => mode.key === renderMode)) {
    url.searchParams.set(VIEW_QUERY_KEY, renderMode);
  } else {
    url.searchParams.delete(VIEW_QUERY_KEY);
  }
}

function removeAutoRunQuery() {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  if (!url.searchParams.has(AUTO_RUN_QUERY_KEY)) {
    return;
  }
  url.searchParams.delete(AUTO_RUN_QUERY_KEY);
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function reproducibleCliCommand(
  requestText: string,
  useLlmAgents: boolean,
  pythonExecutable: string | undefined
) {
  const requestValue = requestText.trim();
  const parts = [
    pythonLauncher(pythonExecutable),
    "-m",
    "mechagent.cli",
    "run",
    powerShellQuote(requestValue),
    "--config",
    "config/mechagent.yaml"
  ];
  if (useLlmAgents) {
    parts.push("--llm-agents");
  }
  return parts.join(" ");
}

function pythonLauncher(pythonExecutable: string | undefined) {
  const executable = pythonExecutable?.trim() || "python";
  if (executable === "python") {
    return "python";
  }
  return `& ${powerShellQuote(executable)}`;
}

function powerShellQuote(value: string) {
  return `"${value
    .replace(/`/g, "``")
    .replace(/\$/g, "`$")
    .replace(/"/g, '`"')}"`;
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

function geometryLabel(
  geometry: Record<string, unknown> | null,
  dimensions: Record<string, unknown> | null
) {
  if (!geometry) {
    return "N/A";
  }
  const type = textValue(geometry.type, "unknown");
  if (!dimensions) {
    return type;
  }
  const dimensionText = Object.entries(dimensions)
    .map(([key, value]) => `${key}=${formatUnknownNumber(value)}mm`)
    .join(", ");
  return `${type} · ${dimensionText}`;
}

function materialLabel(material: Record<string, unknown> | null) {
  if (!material) {
    return "N/A";
  }
  const type = textValue(material.type, "isotropic");
  const elastic = formatUnknownNumber(material.E);
  const nu = formatUnknownNumber(material.nu);
  return `${type} · E=${elastic}MPa · ν=${nu}`;
}

function loadLabel(load: Record<string, unknown> | undefined) {
  if (!load) {
    return "N/A";
  }
  const type = textValue(load.type, "load");
  const magnitude = formatUnknownNumber(load.magnitude);
  const region = textValue(load.region, "region");
  const direction = arrayValue(load.direction).map((item) => formatUnknownNumber(item)).join(", ");
  return `${type} · ${magnitude} · ${region} · [${direction}]`;
}

function boundaryLabel(boundary: Record<string, unknown> | undefined, count: number) {
  if (!boundary) {
    return "N/A";
  }
  const type = textValue(boundary.type, "bc");
  const region = textValue(boundary.region, "region");
  const dofs = arrayValue(boundary.dofs).map((item) => textValue(item, "")).filter(Boolean);
  return `${type} · ${region} · ${dofs.join("/") || "dofs"}${count > 1 ? ` · ${count} 组` : ""}`;
}

function meshLabel(mesh: Record<string, unknown> | null, meshResult: TaskSummary["mesh_result"]) {
  const element = textValue(mesh?.element_type, "element");
  const seed = mesh?.seed_size !== undefined ? `${formatUnknownNumber(mesh.seed_size)}mm` : "N/A";
  const count =
    meshResult?.element_count !== undefined && meshResult.node_count !== undefined
      ? ` · ${meshResult.node_count} 节点 / ${meshResult.element_count} 单元`
      : "";
  return `${element} · seed=${seed}${count}`;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function arrayValue(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function textValue(value: unknown, fallback: string) {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return formatNumber(value);
  }
  return fallback;
}

function uniqueStrings(values: string[]) {
  return [...new Set(values.filter((value) => value.trim()))];
}

function summaryLabel(values: string[]) {
  return uniqueStrings(values).join(" + ");
}

function formatUnknownNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return formatNumber(value);
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? formatNumber(parsed) : value.trim();
  }
  return "N/A";
}

function formatNumber(value: number) {
  if (!Number.isFinite(value)) {
    return "N/A";
  }
  return NUMBER_FORMATTER.format(value);
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

function isActiveJob(job: StudioJobResponse) {
  return job.status === "queued" || job.status === "running";
}

function sleep(ms: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function shortJobId(jobId: string) {
  return `作业 ${jobId.slice(0, 8)}`;
}

function jobStatusLabel(status: StudioJobResponse["status"]) {
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

function jobElapsedLabel(
  job: StudioJobResponse | null,
  running: boolean,
  clockTick: number
) {
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

function formatEventTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--:--";
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(date);
}

function createHistoryItem(request: string, result: StudioRunResponse): RunHistoryItem {
  return {
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    request,
    result: compactHistoryResult(result)
  };
}

function loadRunHistory(): RunHistoryItem[] {
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
    const items = parsed
      .filter(isRunHistoryItem)
      .map(compactHistoryItem)
      .slice(0, MAX_HISTORY_ITEMS);
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

function saveRunHistory(items: RunHistoryItem[]) {
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

function historyTitle(result: StudioRunResponse) {
  const task = result.summary.tasks?.[0];
  const solver = task?.solver_result;
  return solver?.model_case_id || task?.case_id || task?.title || "运行结果";
}

function historyMeta(item: RunHistoryItem) {
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

function formatHistoryTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "未知时间";
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  }).format(date);
}
