import { ClipboardList, Copy, LoaderCircle, Play, Share2 } from "lucide-react";
import { summaryLabel, uniqueStrings } from "../lib/format";
import type { DisplayItem } from "../lib/uiTypes";
import type { StudioInspectionResponse } from "../types";

export function Composer({
  request,
  onRequestChange,
  useParameterCompletion,
  onParameterCompletionChange,
  inspection,
  inspectionRunning,
  running,
  onRun,
  cliCommand,
  workspaceLink,
  onCopy
}: {
  request: string;
  onRequestChange: (value: string) => void;
  useParameterCompletion: boolean;
  onParameterCompletionChange: (value: boolean) => void;
  inspection: StudioInspectionResponse | null;
  inspectionRunning: boolean;
  running: boolean;
  onRun: () => void;
  cliCommand: string;
  workspaceLink: string;
  onCopy: (text: string, label: string) => void;
}) {
  const trimmed = request.trim();
  return (
    <section className="panel composer-panel">
      <div className="panel-title">
        <div className="panel-title-head">
          <span className="panel-title-icon" aria-hidden="true">
            <ClipboardList size={18} />
          </span>
          <h2>工程请求</h2>
        </div>
      </div>
      <textarea
        value={request}
        onChange={(event) => onRequestChange(event.target.value)}
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
            onChange={(event) => onParameterCompletionChange(event.target.checked)}
          />
          <span className="switch-track" aria-hidden="true">
            <span className="switch-thumb" />
          </span>
          <span>参数补全</span>
        </label>
        <span className="text-counter">{trimmed.length} 字符</span>
      </div>
      <PreflightPanel inspection={inspection} loading={inspectionRunning} />
      <div className="composer-actions">
        <button
          className="primary-action"
          type="button"
          disabled={running}
          onClick={onRun}
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
          disabled={!trimmed}
          onClick={() => onCopy(cliCommand, "CLI 复现命令")}
        >
          <Copy aria-hidden="true" size={16} />
          <span>CLI</span>
        </button>
        <button
          className="secondary-action icon-action"
          title="复制当前工作台链接"
          type="button"
          aria-label="复制当前工作台链接"
          disabled={!trimmed}
          onClick={() => onCopy(workspaceLink, "工作台链接")}
        >
          <Share2 aria-hidden="true" size={16} />
        </button>
      </div>
    </section>
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
