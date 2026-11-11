import { useI18n } from "../i18n/LocaleProvider";
import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  LoaderCircle,
  Monitor,
  Moon,
  Settings2,
  Sun,
} from "lucide-react";
import {
  diagnosticCheckDescription,
  runtimeSummaryText,
} from "../lib/diagnostics";
import { runOutcome } from "../lib/results";
import type { RuntimeStatus } from "../lib/uiTypes";
import type {
  StudioDiagnosticsResponse,
  StudioHealth,
  StudioRunResponse,
} from "../types";
import { useTheme } from "../theme/useTheme";
import { CompactEmpty } from "./common";

export function Topbar({
  result,
  running,
  diagnostics,
  health,
  runtimeStatusInfo,
  statusMessage,
}: {
  result: StudioRunResponse | null;
  running: boolean;
  diagnostics: StudioDiagnosticsResponse | null;
  health: StudioHealth | null;
  runtimeStatusInfo: RuntimeStatus;
  statusMessage: string;
}) {
  const { t } = useI18n();
  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">
          <svg
            viewBox="0 0 32 32"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
          >
            <path d="m16 3 12 7v13l-12 7-12-7V10Z M4 10l12 7 12-7 M16 17v13 M10 6.5l12 7V26" />
          </svg>
        </div>
        <div className="brand-copy">
          <h1 translate="no">
            MechAgent <span>Studio</span>
          </h1>
          <p>{t("开源 CAE/FEA 多智能体仿真工作台")}</p>
        </div>
      </div>
      <div
        className="topbar-actions"
        aria-live="polite"
        aria-label={t(statusMessage)}
      >
        <StatusPill result={result} running={running} />
        <RuntimeDiagnosticsMenu
          diagnostics={diagnostics}
          health={health}
          status={runtimeStatusInfo}
        />
        <LanguageToggle />
        <ThemeToggle />
      </div>
    </header>
  );
}

function LanguageToggle() {
  const { locale, setLocale, t } = useI18n();
  return (
    <button
      className="theme-toggle language-toggle"
      type="button"
      lang={locale === "zh" ? "en" : "zh-CN"}
      aria-label={t(locale === "zh" ? "切换为英文" : "切换为中文")}
      title={t("语言")}
      onClick={() => setLocale(locale === "zh" ? "en" : "zh")}
    >
      <span aria-hidden="true">{locale === "zh" ? "EN" : "中"}</span>
      <span>{locale === "zh" ? "English" : "简体中文"}</span>
    </button>
  );
}

export function ThemeToggle() {
  const { t } = useI18n();
  const { preference, cyclePreference } = useTheme();
  const meta =
    preference === "light"
      ? { icon: <Sun aria-hidden="true" size={16} />, label: t("浅色") }
      : preference === "dark"
        ? { icon: <Moon aria-hidden="true" size={16} />, label: t("深色") }
        : {
            icon: <Monitor aria-hidden="true" size={16} />,
            label: t("跟随系统"),
          };
  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={cyclePreference}
      aria-label={t("主题：{0}，点击切换", meta.label)}
      title={t("主题：{0}（点击在 浅色 / 深色 / 跟随系统 间切换）", meta.label)}
    >
      {meta.icon}
      <span>{t(meta.label)}</span>
    </button>
  );
}

function StatusPill({
  result,
  running,
}: {
  result: StudioRunResponse | null;
  running: boolean;
}) {
  const { t } = useI18n();
  if (running) {
    return (
      <span className="status-pill running">
        <LoaderCircle aria-hidden="true" className="spin" size={16} />
        {t("求解中…")}
      </span>
    );
  }
  if (!result) {
    return <span className="status-pill idle">{t("待运行")}</span>;
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
      {t(outcome.label)}
    </span>
  );
}

function RuntimeDiagnosticsMenu({
  diagnostics,
  health,
  status,
}: {
  diagnostics: StudioDiagnosticsResponse | null;
  health: StudioHealth | null;
  status: RuntimeStatus;
}) {
  const { t } = useI18n();
  return (
    <details className="runtime-menu">
      <summary
        aria-label={t(status.ariaLabel)}
        className={`utility-pill tone-${status.tone}`}
        title={t(status.title)}
      >
        <Settings2 aria-hidden="true" size={16} />
        <span>{t(status.label)}</span>
      </summary>
      <div
        className="runtime-popover"
        role="group"
        aria-label={t("运行环境诊断摘要")}
      >
        <div className="runtime-popover-head">
          <div>
            <strong>{t("运行环境")}</strong>
            <span>{t(runtimeSummaryText(diagnostics, health))}</span>
          </div>
          <span className={`runtime-summary-badge tone-${status.tone}`}>
            {diagnostics
              ? diagnostics.ok
                ? t("通过")
                : t("异常")
              : health?.ok
                ? t("检测中")
                : t("连接中")}
          </span>
        </div>
        <p className="runtime-config">
          {t("配置：")}
          {diagnostics?.config_path ?? health?.config ?? t("等待后端返回")}
        </p>
        {diagnostics ? (
          <ol className="runtime-checks">
            {diagnostics.checks.map((check) => (
              <li
                className={`runtime-check tone-${check.ok ? "ok" : "bad"}`}
                key={check.key}
              >
                <span className="runtime-check-dot" aria-hidden="true" />
                <div>
                  <strong>{t(check.label || check.key)}</strong>
                  <small>{t(diagnosticCheckDescription(check))}</small>
                </div>
                <span className="runtime-check-kind">
                  {check.required ? t("必需") : t("可选")}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <CompactEmpty
            text={
              health?.ok
                ? t("正在读取本机环境诊断。")
                : t("正在连接本地 Studio 服务。")
            }
          />
        )}
      </div>
    </details>
  );
}
