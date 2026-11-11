import { useI18n } from "../i18n/LocaleProvider";
import { handleTabKeyDown } from "../lib/tabs";
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
  Workflow,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { agentChainToneLabel, agentTraceDetails } from "../lib/agentChain";
import { formatEventTime } from "../lib/format";
import { jobElapsedLabel, jobStatusLabel, shortJobId } from "../lib/job";
import { artifactLabel, runOutcome } from "../lib/results";
import { stageStateLabel } from "../lib/stages";
import type {
  AgentChainItem,
  DisplayItem,
  MetricItem,
  StageRow,
} from "../lib/uiTypes";
import type {
  StudioJobResponse,
  StudioProgressEvent,
  StudioRunResponse,
  TaskSummary,
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
  onCopyJson,
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
  const { t } = useI18n();
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
      label: t("流程"),
      title: t("求解流程"),
      icon: <Workflow aria-hidden="true" size={16} />,
      content: <WorkflowSteps stages={stages} />,
    },
    {
      key: "agents",
      label: "Agent",
      title: t("Agent 链路"),
      icon: <Network aria-hidden="true" size={16} />,
      content: <AgentChainPanel items={agentChain} />,
    },
    {
      key: "artifacts",
      label: t("产物"),
      title: t("阶段产物"),
      icon: <Database aria-hidden="true" size={16} />,
      content:
        artifacts.length > 0 ? (
          <ArtifactList artifacts={artifacts} onCopy={onCopyArtifact} />
        ) : (
          <CompactEmpty text={t("运行后显示报告、网格和求解器输出路径。")} />
        ),
    },
    {
      key: "json",
      label: "JSON",
      title: t("摘要 JSON"),
      icon: <FileJson aria-hidden="true" size={16} />,
      actions: (
        <span className="json-actions">
          <button
            className="icon-button"
            title={t("下载 JSON")}
            type="button"
            aria-label={t("下载摘要 JSON")}
            disabled={!result}
            onClick={onDownloadJson}
          >
            <Download aria-hidden="true" size={16} />
          </button>
          <button
            className="icon-button"
            title={t("复制 JSON")}
            type="button"
            aria-label={t("复制摘要 JSON")}
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
      ),
    },
  ];
  const activeTab =
    inspectorTabs.find((tab) => tab.key === activeInspectorTab) ??
    inspectorTabs[0];

  return (
    <aside
      className={`right-rail ${result ? "has-result" : ""}`}
      aria-label={t("仿真检查器")}
    >
      <section
        className={`panel verification-panel ${result ? "has-result" : ""}`}
      >
        <div className="panel-title">
          <div className="panel-title-head">
            <span className="panel-title-icon" aria-hidden="true">
              <ShieldCheck size={18} />
            </span>
            <h2>{t("验收状态")}</h2>
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
            <div
              className={`metric-card tone-${metric.tone ?? "neutral"}`}
              key={metric.label}
            >
              <span>{t(metric.label)}</span>
              <strong>{t(metric.value)}</strong>
            </div>
          ))}
        </div>
        {verification.length > 0 && (
          <dl className="verification-list">
            {verification.map((item) => (
              <div key={item.label}>
                <dt>{t(item.label)}</dt>
                <dd>{t(item.value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section className="panel inspector-detail-panel">
        <div
          className="inspector-tabs"
          role="tablist"
          aria-label={t("检查器视图")}
          onKeyDown={handleTabKeyDown}
        >
          {inspectorTabs.map((tab) => (
            <button
              key={tab.key}
              className={tab.key === activeTab.key ? "active" : ""}
              type="button"
              role="tab"
              id={`inspector-tab-${tab.key}`}
              aria-controls="inspector-tabpanel"
              tabIndex={tab.key === activeTab.key ? 0 : -1}
              aria-selected={tab.key === activeTab.key}
              onClick={() => setActiveInspectorTab(tab.key)}
            >
              {tab.icon}
              <span>{t(tab.label)}</span>
            </button>
          ))}
        </div>
        <div className="inspector-tab-header">
          <div className="panel-title-head">
            <span className="panel-title-icon" aria-hidden="true">
              {activeTab.icon}
            </span>
            <h2>{t(activeTab.title)}</h2>
          </div>
          {activeTab.actions ? (
            <div className="panel-actions">{activeTab.actions}</div>
          ) : null}
        </div>
        <div
          className="inspector-tab-body"
          role="tabpanel"
          id="inspector-tabpanel"
          aria-labelledby={`inspector-tab-${activeTab.key}`}
        >
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
  task,
}: {
  clockTick: number;
  job: StudioJobResponse | null;
  result: StudioRunResponse | null;
  running: boolean;
  task: TaskSummary | null;
}) {
  const { t } = useI18n();
  const jobLine = job
    ? `${t(shortJobId(job.job_id))} · ${t(jobStatusLabel(job.status))}`
    : t("作业准备中");
  const elapsed = jobElapsedLabel(job, running, clockTick);
  if (running) {
    return (
      <div className="verdict-card running">
        <LoaderCircle aria-hidden="true" className="spin" size={18} />
        <div>
          <strong>{t("求解执行中")}</strong>
          <span>{jobLine}</span>
          <span>
            {elapsed ? t("已运行 {0}", elapsed) : t("等待后端作业启动。")}
          </span>
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
          <strong>{t("等待运行")}</strong>
          <span>{t("提交工程请求后开始验收。")}</span>
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
        <strong>{t(outcome.title)}</strong>
        <span>{t(outcome.message)}</span>
        {job && (
          <span>{`${t(shortJobId(job.job_id))} · ${t(jobStatusLabel(job.status))}`}</span>
        )}
      </div>
    </div>
  );
}

function WorkflowSteps({ stages }: { stages: StageRow[] }) {
  const { t } = useI18n();
  return (
    <ol className="workflow-steps" aria-label={t("求解流程阶段")}>
      {stages.map((stage, index) => (
        <li className={`workflow-step is-${stage.state}`} key={stage.key}>
          <span className="step-index">{index + 1}</span>
          <div>
            <strong>{t(stage.label)}</strong>
            <small title={stage.eventMessage || t(stage.caption)}>
              {t(stage.caption)}
              {stage.eventTime ? ` · ${stage.eventTime}` : ""}
            </small>
          </div>
          <span className="step-state">{t(stageStateLabel(stage.state))}</span>
        </li>
      ))}
    </ol>
  );
}

function AgentChainPanel({ items }: { items: AgentChainItem[] }) {
  const { t } = useI18n();
  if (items.length === 0) {
    return (
      <CompactEmpty
        text={t("运行后显示每个 Agent 的结构化产物和 LLM trace 摘要。")}
      />
    );
  }
  return (
    <div className="agent-chain-list" aria-label={t("Agent 链路摘要")}>
      {items.map((item) => (
        <details
          className={`agent-chain-item tone-${item.tone}`}
          key={item.key}
        >
          <summary>
            <span className="agent-dot" aria-hidden="true" />
            <div>
              <strong>{t(item.label)}</strong>
              <small title={item.summary}>{t(item.summary)}</small>
            </div>
            <span>{t(agentChainToneLabel(item.tone))}</span>
          </summary>
          <dl>
            {[...item.details, ...agentTraceDetails(item.trace)].map(
              (detail) => (
                <div key={`${item.key}-${detail.label}`}>
                  <dt>{t(detail.label)}</dt>
                  <dd title={detail.value}>{t(detail.value)}</dd>
                </div>
              ),
            )}
          </dl>
        </details>
      ))}
    </div>
  );
}

function ArtifactList({
  artifacts,
  onCopy,
}: {
  artifacts: string[];
  onCopy: (artifact: string, label: string) => void;
}) {
  const { t } = useI18n();
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
              title={t("复制路径")}
              type="button"
              aria-label={t("复制阶段产物路径：{0}", label)}
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
  const { t } = useI18n();
  return (
    <details className="event-log">
      <summary className="event-log-head" aria-label={t("最近运行事件")}>
        <span>{t("运行事件")}</span>
        <strong>
          {events.length > 0 ? t("{0} 条", events.length) : t("待记录")}
        </strong>
      </summary>
      {events.length > 0 ? (
        <ol>
          {events.map((event, index) => (
            <li
              className={`event-item is-${event.status}`}
              key={`${event.timestamp}-${index}`}
            >
              <span>{formatEventTime(event.timestamp)}</span>
              <strong title={event.message}>{t(event.message)}</strong>
            </li>
          ))}
        </ol>
      ) : (
        <p>{t("提交作业后显示后端阶段事件。")}</p>
      )}
    </details>
  );
}
