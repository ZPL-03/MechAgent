import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { Boxes, LoaderCircle } from "lucide-react";
import type { ExampleFilter, RunHistoryItem, SideTab } from "./lib/uiTypes";
import type { StudioRunResponse } from "./types";
import {
  HISTORY_UNDO_TIMEOUT_MS,
  JOB_POLL_INTERVAL_MS,
  MAX_HISTORY_ITEMS,
  RENDER_MODES,
  URL_SYNC_DEBOUNCE_MS
} from "./lib/constants";
import { createJob, fetchJob } from "./lib/api";
import { writeClipboardText } from "./lib/clipboard";
import { reproducibleCliCommand } from "./lib/cli";
import { runtimeStatus } from "./lib/diagnostics";
import { downloadReport, downloadSummaryJson, downloadVisualization } from "./lib/download";
import { displayExamples, filterExamples } from "./lib/examples";
import { isActiveJob, recentJobEvents, runError, sleep } from "./lib/job";
import {
  artifactPaths,
  metricItems,
  runOutcome,
  studyFacts,
  verificationItems
} from "./lib/results";
import { buildAgentChain } from "./lib/agentChain";
import { buildStageRows } from "./lib/stages";
import { createHistoryItem, loadRunHistory, saveRunHistory } from "./lib/storage";
import {
  initialAutoRunFromUrl,
  initialParameterCompletionFromUrl,
  initialRenderModeIndexFromUrl,
  initialRequestFromUrl,
  removeAutoRunQuery,
  replaceStudioUrl,
  studioWorkspaceLink
} from "./lib/url";
import { defaultRenderModeIndex, visualizationsForTask } from "./lib/visualization";
import { useInspection } from "./hooks/useInspection";
import { useStudioBootstrap } from "./hooks/useStudioBootstrap";
import { useToast } from "./hooks/useToast";
import { Composer } from "./components/Composer";
import { EmptyState } from "./components/common";
import { InspectorRail } from "./components/Inspector";
import { SidePanel } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { ReportPanel, ViewportPanel, WorkflowStepper } from "./components/Workspace";

const ThreeViewport = lazy(() =>
  import("./ThreeViewport").then((module) => ({ default: module.ThreeViewport }))
);

export function App() {
  const autoRunRequested = useRef(initialAutoRunFromUrl());
  const autoRunStarted = useRef(false);
  const [request, setRequest] = useState(() => initialRequestFromUrl());
  const [useParameterCompletion, setUseParameterCompletion] = useState(() =>
    initialParameterCompletionFromUrl()
  );
  const [running, setRunning] = useState(false);
  const [activeJob, setActiveJob] = useState<Awaited<ReturnType<typeof createJob>> | null>(null);
  const [monitorTick, setMonitorTick] = useState(0);
  const [result, setResult] = useState<StudioRunResponse | null>(null);
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

  const { health, diagnostics, capabilities, catalogExamples } = useStudioBootstrap();
  const { inspection, inspectionRunning } = useInspection(request);
  const { notice, showNotice } = useToast();

  const activeHistoryItem = useMemo(
    () => history.find((item) => item.id === activeHistoryId) ?? null,
    [activeHistoryId, history]
  );
  const selectedRenderMode = RENDER_MODES[selectedRenderModeIndex] ?? RENDER_MODES[0];

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
  const taskVisualizations = visualizationsForTask(result?.visualizations ?? [], selectedTask);
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
  const agentChain = useMemo(() => buildAgentChain(result, selectedTask), [result, selectedTask]);
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
  const runtimeStatusInfo = runtimeStatus(diagnostics, health);

  async function runSimulation(requestOverride?: string) {
    const requestText = (requestOverride ?? request).trim();
    if (!requestText) {
      setResult(runError("请输入结构、材料、边界和载荷信息。"));
      return;
    }
    if (requestOverride !== undefined) {
      setRequest(requestText);
    }
    setRunning(true);
    setActiveJob(null);
    setMonitorTick(0);
    setSelectedTaskIndex(0);
    setSelectedVisualIndex(0);
    setSelectedRenderModeIndex(0);
    try {
      let job = await createJob(requestText, useParameterCompletion);
      setActiveJob(job);
      while (isActiveJob(job)) {
        await sleep(JOB_POLL_INTERVAL_MS);
        job = await fetchJob(job.job_id);
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

  function rerunHistoryItem(item: RunHistoryItem) {
    setActiveHistoryId(item.id);
    void runSimulation(item.request);
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

      <Topbar
        result={result}
        running={running}
        diagnostics={diagnostics}
        health={health}
        runtimeStatusInfo={runtimeStatusInfo}
        statusMessage={statusMessage}
      />

      <div className="toast-region" aria-live="polite" aria-atomic="true">
        {notice && (
          <div className={`toast-message tone-${notice.tone}`} role="status">
            {notice.message}
          </div>
        )}
      </div>

      <WorkflowStepper
        request={request}
        inspection={inspection}
        inspectionRunning={inspectionRunning}
        running={running}
        result={result}
      />

      <div className="studio-layout">
        <aside className="left-rail" aria-label="仿真输入">
          <Composer
            request={request}
            onRequestChange={setRequest}
            useParameterCompletion={useParameterCompletion}
            onParameterCompletionChange={setUseParameterCompletion}
            inspection={inspection}
            inspectionRunning={inspectionRunning}
            running={running}
            onRun={() => void runSimulation()}
            cliCommand={cliCommand}
            workspaceLink={workspaceLink}
            onCopy={(text, label) => void copyTextToClipboard(text, label)}
          />
          <SidePanel
            selectedSideTab={selectedSideTab}
            onSelectSideTab={setSelectedSideTab}
            examples={filteredExamples}
            totalCount={examples.length}
            exampleFilter={exampleFilter}
            exampleQuery={exampleQuery}
            onFilterChange={setExampleFilter}
            onQueryChange={setExampleQuery}
            onSelectExample={setRequest}
            history={history}
            activeHistoryId={activeHistoryId}
            recentlyClearedCount={recentlyClearedHistory?.length ?? 0}
            onClearHistory={clearHistory}
            onUndoClear={restoreHistory}
            onSelectHistory={selectHistoryItem}
            facts={facts}
          />
        </aside>

        <main className="workspace" id="main-workbench">
          <ViewportPanel
            selectedTask={selectedTask}
            tasks={tasks}
            selectedTaskIndex={selectedTaskIndex}
            onSelectTask={selectTask}
            renderModeIndex={selectedRenderModeIndex}
            onSelectRenderMode={setSelectedRenderModeIndex}
            downloadDisabled={!activeVisualization}
            downloadTitle={downloadTitle}
            onDownload={() => downloadVisualization(activeVisualization, selectedRenderMode.key)}
          >
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
                    <ThreeViewport scene={activeVisualization.scene} mode={selectedRenderMode.key} />
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
                title={activeHistoryItem ? "历史结果已回看" : "等待结果场"}
                text={
                  activeHistoryItem
                    ? "当前历史仅保留摘要和报告。重跑此请求可恢复几何、网格和结果视图。"
                    : "运行后展示由求解摘要、网格文件和位移场生成的工程视图。"
                }
                actionLabel={activeHistoryItem ? "重跑此请求" : undefined}
                onAction={
                  activeHistoryItem ? () => rerunHistoryItem(activeHistoryItem) : undefined
                }
              />
            )}
          </ViewportPanel>

          <ReportPanel
            result={result}
            tasks={tasks}
            selectedTaskIndex={selectedTaskIndex}
            onSelectTask={selectTask}
            onDownloadReport={() => downloadReport(result, selectedTask)}
            onCopyReport={() => void copyTextToClipboard(result?.report ?? "", "Markdown 工程报告")}
          />
        </main>

        <InspectorRail
          monitorTick={monitorTick}
          activeJob={activeJob}
          result={result}
          running={running}
          selectedTask={selectedTask}
          metrics={metrics}
          verification={verification}
          stages={stages}
          agentChain={agentChain}
          artifacts={artifacts}
          summaryJson={summaryJson}
          eventLog={eventLog}
          onCopyArtifact={(artifact, label) =>
            void copyTextToClipboard(artifact, `${label}产物路径`)
          }
          onDownloadJson={() => downloadSummaryJson(result, selectedTask, summaryJson)}
          onCopyJson={() => void copyTextToClipboard(summaryJson, "摘要 JSON")}
        />
      </div>
    </div>
  );
}
