import type { ReactNode } from "react";
import { Copy, Download, FileText, Layers3 } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { RENDER_MODES } from "../lib/constants";
import {
  taskModelLabel,
  taskRelativeError,
  taskResultValue,
  taskStatus
} from "../lib/results";
import type { StudioInspectionResponse, StudioRunResponse, TaskSummary } from "../types";
import { CompactEmpty } from "./common";

type StepState = "upcoming" | "current" | "done" | "failed";

export function WorkflowStepper({
  request,
  inspection,
  inspectionRunning,
  running,
  result
}: {
  request: string;
  inspection: StudioInspectionResponse | null;
  inspectionRunning: boolean;
  running: boolean;
  result: StudioRunResponse | null;
}) {
  const hasRequest = request.trim().length > 0;
  const ready = inspection?.ready ?? false;
  const hasResult = Boolean(result);
  const steps: Array<{ key: string; label: string; hint: string; state: StepState }> = [
    {
      key: "input",
      label: "输入需求",
      hint: "自然语言工程请求",
      state: hasRequest ? "done" : "current"
    },
    {
      key: "preflight",
      label: "运行前预检",
      hint: "能力识别与缺参诊断",
      state: inspectionRunning
        ? "current"
        : ready
          ? "done"
          : hasRequest
            ? "current"
            : "upcoming"
    },
    {
      key: "run",
      label: "运行求解",
      hint: "网格、求解与后处理",
      state: running ? "current" : hasResult ? "done" : "upcoming"
    },
    {
      key: "result",
      label: "结果与报告",
      hint: "3D 场量、验收与报告",
      state: hasResult ? (result?.success ? "done" : "failed") : running ? "current" : "upcoming"
    }
  ];
  return (
    <ol className="workflow-stepper" aria-label="仿真工作流进度">
      {steps.map((step, index) => (
        <li className={`stepper-item is-${step.state}`} key={step.key}>
          <span className="stepper-index" aria-hidden="true">
            {index + 1}
          </span>
          <span className="stepper-copy">
            <strong>{step.label}</strong>
            <small>{step.hint}</small>
          </span>
          {index < steps.length - 1 ? <span className="stepper-line" aria-hidden="true" /> : null}
        </li>
      ))}
    </ol>
  );
}

export function ViewportPanel({
  selectedTask,
  tasks,
  selectedTaskIndex,
  onSelectTask,
  renderModeIndex,
  onSelectRenderMode,
  downloadDisabled,
  downloadTitle,
  onDownload,
  children
}: {
  selectedTask: TaskSummary | null;
  tasks: TaskSummary[];
  selectedTaskIndex: number;
  onSelectTask: (index: number) => void;
  renderModeIndex: number;
  onSelectRenderMode: (index: number) => void;
  downloadDisabled: boolean;
  downloadTitle: string;
  onDownload: () => void;
  children: ReactNode;
}) {
  return (
    <section className="panel visual-panel">
      <div className="panel-header">
        <div className="panel-header-copy">
          <div className="panel-title-head">
            <span className="panel-title-icon" aria-hidden="true">
              <Layers3 size={18} />
            </span>
            <h2>结果视口</h2>
          </div>
          <p>{selectedTask?.title ?? "等待仿真任务"}</p>
        </div>
        <TaskTabs tasks={tasks} selectedIndex={selectedTaskIndex} onSelect={onSelectTask} />
      </div>

      <div className="viewport-toolbar">
        <div className="view-tabs" role="tablist" aria-label="三维视图模式">
          {RENDER_MODES.map((mode, index) => {
            const Icon = mode.icon;
            return (
              <button
                key={mode.key}
                className={index === renderModeIndex ? "active" : ""}
                type="button"
                role="tab"
                aria-selected={index === renderModeIndex}
                title={mode.caption}
                onClick={() => onSelectRenderMode(index)}
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
          disabled={downloadDisabled}
          onClick={onDownload}
        >
          <Download aria-hidden="true" size={17} />
        </button>
      </div>

      <div className="visual-canvas">{children}</div>
    </section>
  );
}

export function TaskTabs({
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

export function ReportPanel({
  result,
  tasks,
  selectedTaskIndex,
  onSelectTask,
  onDownloadReport,
  onCopyReport
}: {
  result: StudioRunResponse | null;
  tasks: TaskSummary[];
  selectedTaskIndex: number;
  onSelectTask: (index: number) => void;
  onDownloadReport: () => void;
  onCopyReport: () => void;
}) {
  return (
    <section className="panel report-panel">
      <div className="panel-title">
        <div className="panel-title-head">
          <span className="panel-title-icon" aria-hidden="true">
            <FileText size={18} />
          </span>
          <h2>工程报告</h2>
        </div>
        <div className="panel-actions">
          <button
            className="icon-button"
            title="下载报告"
            type="button"
            aria-label="下载 Markdown 工程报告"
            disabled={!result?.report}
            onClick={onDownloadReport}
          >
            <Download aria-hidden="true" size={17} />
          </button>
          <button
            className="icon-button"
            title="复制报告"
            type="button"
            aria-label="复制 Markdown 工程报告"
            disabled={!result?.report}
            onClick={onCopyReport}
          >
            <Copy aria-hidden="true" size={17} />
          </button>
        </div>
      </div>
      <ResultMatrix tasks={tasks} selectedIndex={selectedTaskIndex} onSelect={onSelectTask} />
      <div className="markdown-body">
        {result?.report ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.report}</ReactMarkdown>
        ) : (
          <CompactEmpty text="运行后显示可发布的 Markdown 工程报告。" />
        )}
      </div>
    </section>
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
