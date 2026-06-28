import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Database,
  Download,
  FileJson,
  Gauge,
  LoaderCircle,
  Network,
  ShieldCheck,
  Workflow
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { agentChainToneLabel, agentTraceDetails } from "../lib/agentChain";
import { formatEventTime } from "../lib/format";
import { jobElapsedLabel, jobStatusLabel, shortJobId } from "../lib/job";
import { artifactLabel, runOutcome } from "../lib/results";
import { stageCaption, stageStateLabel } from "../lib/stages";
import type {
  AgentChainItem,
  DisplayItem,
  MetricItem,
  StageRow
} from "../lib/uiTypes";
import type {
  StudioJobResponse,
  StudioProgressEvent,
  StudioRunResponse,
  TaskSummary
} from "../types";
import { CompactEmpty } from "./common";

export function InspectorRail({
  monitorTick,
  activeJob,
  result,
  running,
  selectedTask,
  metrics,
  verification,
  stages,
  agentChain,
  artifacts,
  summaryJson,
  eventLog,
  onCopyArtifact,
  onDownloadJson,
  onCopyJson
}: {
  monitorTick: number;
  activeJob: StudioJobResponse | null;
  result: StudioRunResponse | null;
  running: boolean;
  selectedTask: TaskSummary | null;
  metrics: MetricItem[];
  verification: DisplayItem[];
  stages: StageRow[];
  agentChain: AgentChainItem[];
  artifacts: string[];
  summaryJson: string;
  eventLog: StudioProgressEvent[];
  onCopyArtifact: (artifact: string, label: string) => void;
  onDownloadJson: () => void;
  onCopyJson: () => void;
}) {
  const [activeInspectorTab, setActiveInspectorTab] = useState("workflow");
  const inspectorTabs: Array<{
    key: string;
    label: string;
    title: string;
    icon: ReactNode;
    actions?: ReactNode;
    content: ReactNode;
  }> = [
    {
      key: "workflow",
      label: "流程",
      title: "求解流程",
      icon: <Workflow aria-hidden="true" size={16} />,
      content: <WorkflowSteps stages={stages} />
    },
    {
      key: "agents",
      label: "Agent",
      title: "Agent 链路",
      icon: <Network aria-hidden="true" size={16} />,
      content: <AgentChainPanel items={agentChain} />
    },
    {
      key: "artifacts",
      label: "产物",
      title: "阶段产物",
      icon: <Database aria-hidden="true" size={16} />,
      content:
        artifacts.length > 0 ? (
          <ArtifactList artifacts={artifacts} onCopy={onCopyArtifact} />
        ) : (
          <CompactEmpty text="运行后显示报告、网格和求解器输出路径。" />
        )
    },
    {
      key: "json",
      label: "JSON",
      title: "摘要 JSON",
      icon: <FileJson aria-hidden="true" size={16} />,
      actions: (
        <span className="json-actions">
          <button
            className="icon-button"
            title="下载 JSON"
            type="button"
            aria-label="下载摘要 JSON"
            disabled={!result}
            onClick={onDownloadJson}
          >
            <Download aria-hidden="true" size={16} />
          </button>
          <button
            className="icon-button"
            title="复制 JSON"
            type="button"
            aria-label="复制摘要 JSON"
            disabled={!result}
            onClick={onCopyJson}
          >
            <Copy aria-hidden="true" size={16} />
          </button>
        </span>
      ),
      content: (
        <>
          <EventLog events={eventLog} />
          <pre className="json-view">{summaryJson}</pre>
        </>
      )
    }
  ];
  const activeTab =
    inspectorTabs.find((tab) => tab.key === activeInspectorTab) ?? inspectorTabs[0];

  return (
    <aside className={`right-rail ${result ? "has-result" : ""}`} aria-label="仿真检查器">
      <section className={`panel verification-panel ${result ? "has-result" : ""}`}>
        <div className="panel-title">
          <div className="panel-title-head">
            <span className="panel-title-icon" aria-hidden="true">
              <ShieldCheck size={18} />
            </span>
            <h2>验收状态</h2>
          </div>
        </div>
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

      <section className="panel inspector-detail-panel">
        <div className="inspector-tabs" role="tablist" aria-label="检查器视图">
          {inspectorTabs.map((tab) => (
            <button
              key={tab.key}
              className={tab.key === activeTab.key ? "active" : ""}
              type="button"
              role="tab"
              aria-selected={tab.key === activeTab.key}
              onClick={() => setActiveInspectorTab(tab.key)}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
        </div>
        <div className="inspector-tab-header">
          <div className="panel-title-head">
            <span className="panel-title-icon" aria-hidden="true">
              {activeTab.icon}
            </span>
            <h2>{activeTab.title}</h2>
          </div>
          {activeTab.actions ? <div className="panel-actions">{activeTab.actions}</div> : null}
        </div>
        <div className="inspector-tab-body" role="tabpanel">
          {activeTab.content}
        </div>
      </section>
    </aside>
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

function WorkflowSteps({ stages }: { stages: StageRow[] }) {
  return (
    <ol className="workflow-steps" aria-label="求解流程阶段">
      {stages.map((stage, index) => (
        <li className={`workflow-step is-${stage.state}`} key={stage.key}>
          <span className="step-index">{index + 1}</span>
          <div>
            <strong>{stage.label}</strong>
            <small title={stage.eventMessage || stage.caption}>{stageCaption(stage)}</small>
          </div>
          <span className="step-state">{stageStateLabel(stage.state)}</span>
        </li>
      ))}
    </ol>
  );
}

function AgentChainPanel({ items }: { items: AgentChainItem[] }) {
  if (items.length === 0) {
    return <CompactEmpty text="运行后显示每个 Agent 的结构化产物和 LLM trace 摘要。" />;
  }
  return (
    <div className="agent-chain-list" aria-label="Agent 链路摘要">
      {items.map((item) => (
        <details className={`agent-chain-item tone-${item.tone}`} key={item.key}>
          <summary>
            <span className="agent-dot" aria-hidden="true" />
            <div>
              <strong>{item.label}</strong>
              <small title={item.summary}>{item.summary}</small>
            </div>
            <span>{agentChainToneLabel(item.tone)}</span>
          </summary>
          <dl>
            {[...item.details, ...agentTraceDetails(item.trace)].map((detail) => (
              <div key={`${item.key}-${detail.label}`}>
                <dt>{detail.label}</dt>
                <dd title={detail.value}>{detail.value}</dd>
              </div>
            ))}
          </dl>
        </details>
      ))}
    </div>
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
