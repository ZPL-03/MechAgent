import type {
  StudioDiagnosticCheck,
  StudioDiagnosticsResponse,
  StudioHealth
} from "../types";
import type { RuntimeStatus } from "./uiTypes";

export function runtimeStatus(
  diagnostics: StudioDiagnosticsResponse | null,
  health: StudioHealth | null
): RuntimeStatus {
  if (diagnostics) {
    const summary = diagnostics.summary;
    const requiredText = `必需 ${summary.required_passed}/${summary.required_total}`;
    const optionalText = `可选 ${summary.optional_passed}/${summary.optional_total}`;
    const requiredFailures = diagnosticFailureLabels(diagnostics, true);
    const optionalFailures = diagnosticFailureLabels(diagnostics, false);
    const failureText =
      requiredFailures.length > 0
        ? `；必需异常：${requiredFailures.join("、")}`
        : optionalFailures.length > 0
          ? `；可选异常：${optionalFailures.join("、")}`
          : "";
    const title = `运行环境：${requiredText}，${optionalText}；配置 ${diagnostics.config_path}${failureText}`;
    if (!diagnostics.ok) {
      return {
        ariaLabel: `运行环境异常，${requiredText}，${optionalText}`,
        label: "环境异常",
        title,
        tone: "bad"
      };
    }
    return {
      ariaLabel: `运行环境通过，${requiredText}，${optionalText}`,
      label: `环境 ${summary.required_passed}/${summary.required_total}`,
      title,
      tone: optionalFailures.length > 0 ? "warn" : "ok"
    };
  }
  if (health?.ok) {
    return {
      ariaLabel: "本地服务已连接，运行环境检测中",
      label: "环境检测中",
      title: health.config,
      tone: "neutral"
    };
  }
  return {
    ariaLabel: "本地服务检测中",
    label: "服务检测中",
    title: "等待后端健康检查返回。",
    tone: "neutral"
  };
}

export function diagnosticFailureLabels(
  diagnostics: StudioDiagnosticsResponse,
  required: boolean
): string[] {
  return diagnostics.checks
    .filter((item) => item.required === required && !item.ok)
    .slice(0, 4)
    .map((item) => item.label || item.key);
}

export function runtimeSummaryText(
  diagnostics: StudioDiagnosticsResponse | null,
  health: StudioHealth | null
): string {
  if (diagnostics) {
    const summary = diagnostics.summary;
    return `必需 ${summary.required_passed}/${summary.required_total} · 可选 ${summary.optional_passed}/${summary.optional_total}`;
  }
  return health?.ok ? "本地服务已连接，环境检测中" : "等待本地服务健康检查";
}

export function diagnosticCheckDescription(check: StudioDiagnosticCheck): string {
  const details = check.details;
  switch (check.key) {
    case "python":
      return joinRuntimeParts([detailText(details, "version"), detailText(details, "executable")]);
    case "config":
      return joinRuntimeParts([
        `solver=${detailText(details, "solver")}`,
        `mesher=${detailText(details, "mesher")}`,
        `orchestrator=${detailText(details, "orchestrator")}`
      ]);
    case "packages":
      return packageSummary(details);
    case "studio_static":
      return `JS ${detailArrayLength(details, "js_assets")} · CSS ${detailArrayLength(
        details,
        "css_assets"
      )}`;
    case "registry":
      return `solver ${detailArrayLength(details, "solvers")} · mesher ${detailArrayLength(
        details,
        "meshers"
      )} · capability ${detailArrayLength(details, "capabilities")}`;
    case "solver":
      return joinRuntimeParts([detailText(details, "name"), detailText(details, "resolved")]);
    case "llm":
      return joinRuntimeParts([
        detailText(details, "model"),
        detailBoolean(details, "api_key_present") ? "密钥已配置" : "密钥未配置",
        detailBoolean(details, "connection_checked") ? "已远端检查" : "未远端检查"
      ]);
    case "frontend_source":
      return joinRuntimeParts([detailText(details, "package_json"), detailText(details, "npm")]);
    case "git":
      return detailText(details, "git") || (check.ok ? "Git 可用" : "Git 不可用");
    default:
      return check.ok ? "通过" : "失败";
  }
}

function packageSummary(details: Record<string, unknown>): string {
  const modules = details.modules;
  if (!modules || typeof modules !== "object" || Array.isArray(modules)) {
    return "依赖状态已返回";
  }
  const entries = Object.entries(modules);
  const passed = entries.filter(([, ok]) => ok === true).length;
  const failed = entries
    .filter(([, ok]) => ok !== true)
    .map(([name]) => name)
    .slice(0, 3);
  return failed.length > 0
    ? `依赖 ${passed}/${entries.length} · 缺少 ${failed.join("、")}`
    : `依赖 ${passed}/${entries.length}`;
}

function detailText(details: Record<string, unknown>, key: string): string {
  const value = details[key];
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function detailBoolean(details: Record<string, unknown>, key: string): boolean {
  return details[key] === true;
}

function detailArrayLength(details: Record<string, unknown>, key: string): number {
  const value = details[key];
  return Array.isArray(value) ? value.length : 0;
}

function joinRuntimeParts(parts: string[]): string {
  return parts.filter((part) => part.trim()).join(" · ");
}
