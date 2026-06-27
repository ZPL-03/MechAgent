import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  LoaderCircle,
  Monitor,
  Moon,
  Settings2,
  Sun
} from "lucide-react";
import {
  diagnosticCheckDescription,
  runtimeSummaryText
} from "../lib/diagnostics";
import { runOutcome } from "../lib/results";
import type { RuntimeStatus } from "../lib/uiTypes";
import type {
  StudioDiagnosticsResponse,
  StudioHealth,
  StudioRunResponse
} from "../types";
import { useTheme } from "../theme/useTheme";
import { CompactEmpty } from "./common";

export function Topbar({
  result,
  running,
  diagnostics,
  health,
  runtimeStatusInfo,
  statusMessage
}: {
  result: StudioRunResponse | null;
  running: boolean;
  diagnostics: StudioDiagnosticsResponse | null;
  health: StudioHealth | null;
  runtimeStatusInfo: RuntimeStatus;
  statusMessage: string;
}) {
  return (
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
        <RuntimeDiagnosticsMenu diagnostics={diagnostics} health={health} status={runtimeStatusInfo} />
        <ThemeToggle />
      </div>
    </header>
  );
}

export function ThemeToggle() {
  const { preference, cyclePreference } = useTheme();
  const meta =
    preference === "light"
      ? { icon: <Sun aria-hidden="true" size={16} />, label: "浅色" }
      : preference === "dark"
        ? { icon: <Moon aria-hidden="true" size={16} />, label: "深色" }
        : { icon: <Monitor aria-hidden="true" size={16} />, label: "跟随系统" };
  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={cyclePreference}
      aria-label={`主题：${meta.label}，点击切换`}
      title={`主题：${meta.label}（点击在 浅色 / 深色 / 跟随系统 间切换）`}
    >
      {meta.icon}
      <span>{meta.label}</span>
    </button>
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

function RuntimeDiagnosticsMenu({
  diagnostics,
  health,
  status
}: {
  diagnostics: StudioDiagnosticsResponse | null;
  health: StudioHealth | null;
  status: RuntimeStatus;
}) {
  return (
    <details className="runtime-menu">
      <summary
        aria-label={status.ariaLabel}
        className={`utility-pill tone-${status.tone}`}
        title={status.title}
      >
        <Settings2 aria-hidden="true" size={16} />
        <span>{status.label}</span>
      </summary>
      <div className="runtime-popover" role="group" aria-label="运行环境诊断摘要">
        <div className="runtime-popover-head">
          <div>
            <strong>运行环境</strong>
            <span>{runtimeSummaryText(diagnostics, health)}</span>
          </div>
          <span className={`runtime-summary-badge tone-${status.tone}`}>
            {diagnostics ? (diagnostics.ok ? "通过" : "异常") : health?.ok ? "检测中" : "连接中"}
          </span>
        </div>
        <p className="runtime-config">
          配置：{diagnostics?.config_path ?? health?.config ?? "等待后端返回"}
        </p>
        {diagnostics ? (
          <ol className="runtime-checks">
            {diagnostics.checks.map((check) => (
              <li className={`runtime-check tone-${check.ok ? "ok" : "bad"}`} key={check.key}>
                <span className="runtime-check-dot" aria-hidden="true" />
                <div>
                  <strong>{check.label || check.key}</strong>
                  <small>{diagnosticCheckDescription(check)}</small>
                </div>
                <span className="runtime-check-kind">{check.required ? "必需" : "可选"}</span>
              </li>
            ))}
          </ol>
        ) : (
          <CompactEmpty text={health?.ok ? "正在读取本机环境诊断。" : "正在连接本地 Studio 服务。"} />
        )}
      </div>
    </details>
  );
}
