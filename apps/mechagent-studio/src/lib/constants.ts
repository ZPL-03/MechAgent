import { Boxes, Gauge, Layers3 } from "lucide-react";
import type { StageKey } from "../types";
import type { Example, ExampleFilter } from "./uiTypes";

export const HISTORY_STORAGE_KEY = "mechagent.studio.runHistory";
export const MAX_HISTORY_ITEMS = 8;
export const HISTORY_STORAGE_FALLBACK_ITEMS = 3;
export const HISTORY_REPORT_CHAR_LIMIT = 24_000;
export const HISTORY_UNDO_TIMEOUT_MS = 20_000;
export const JOB_POLL_INTERVAL_MS = 700;
export const INSPECTION_DEBOUNCE_MS = 420;
export const URL_SYNC_DEBOUNCE_MS = 260;
export const NOTICE_TIMEOUT_MS = 2800;
export const REQUEST_QUERY_KEY = "request";
export const LLM_QUERY_KEY = "llm";
export const VIEW_QUERY_KEY = "view";
export const AUTO_RUN_QUERY_KEY = "run";

export const DEFAULT_REQUEST =
  "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，沿梁竖向向下1kN/m均布线载荷的静力响应";

export const DEFAULT_EXAMPLES: Example[] = [
  {
    tag: "梁",
    title: "悬臂梁 · 均布线载荷",
    request: DEFAULT_REQUEST
  },
  {
    tag: "梁",
    title: "悬臂梁 · 端部集中力",
    request: "求解长1000mm、截面20mmx40mm、材料钢的悬臂梁，一端固支，端部向下1000N集中力的静力响应"
  },
  {
    tag: "板",
    title: "矩形板 · 均布压力",
    request: "求解长300mm、宽200mm、厚5mm、材料铝的矩形板，四边简支，承受0.01MPa均布压力的静力响应"
  },
  {
    tag: "实体",
    title: "长方体 · 轴向拉伸",
    request: "长方体实体200mmx20mmx20mm，材料钢，左端固定，右端承受10MPa轴向拉伸静力分析"
  }
];

export const STAGES: Array<{ key: StageKey; label: string; caption: string }> = [
  { key: "planner", label: "任务识别", caption: "需求拆分" },
  { key: "designer", label: "参数建模", caption: "结构化输入" },
  { key: "mesh", label: "网格生成", caption: "质量检查" },
  { key: "solver", label: "求解执行", caption: "CalculiX" },
  { key: "postproc", label: "结果提取", caption: "场量提取" },
  { key: "analyst", label: "工程校核", caption: "参考解验收" },
  { key: "reporter", label: "报告输出", caption: "Markdown" }
];

export const RENDER_MODES = [
  { key: "geometry", label: "几何", caption: "参数化模型", icon: Boxes },
  { key: "mesh", label: "网格", caption: "单元拓扑", icon: Layers3 },
  { key: "result", label: "结果", caption: "位移云图", icon: Gauge }
] as const;
export type RenderModeKey = (typeof RENDER_MODES)[number]["key"];

export const EXAMPLE_FILTERS: Array<{ key: ExampleFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "beam", label: "梁" },
  { key: "plate", label: "板" },
  { key: "solid", label: "实体" },
  { key: "hole", label: "开孔" }
];

export const NODE_ORDER = STAGES.map((stage) => stage.key);
export const RESULT_RENDER_MODE_INDEX = RENDER_MODES.findIndex((mode) => mode.key === "result");

export const NUMBER_FORMATTER = new Intl.NumberFormat(undefined, {
  maximumSignificantDigits: 6
});
export const PERCENT_FORMATTER = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 4,
  minimumFractionDigits: 0,
  style: "percent"
});
