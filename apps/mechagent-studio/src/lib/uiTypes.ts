import type { ReactNode } from "react";
import type { AgentTrace, StageKey, StageState, StudioRunResponse } from "../types";

export type Example = {
  tag: string;
  title: string;
  request: string;
};

export type DisplayItem = {
  label: string;
  value: string;
};

export type MetricItem = DisplayItem & {
  tone?: "neutral" | "ok" | "warn" | "bad";
};

export type StageRow = {
  key: StageKey;
  label: string;
  caption: string;
  state: StageState;
  eventMessage: string;
  eventTime: string;
};

export type AgentChainTone = "neutral" | "ok" | "warn" | "bad";

export type AgentChainItem = {
  key: StageKey;
  label: string;
  summary: string;
  tone: AgentChainTone;
  details: DisplayItem[];
  trace?: AgentTrace | null;
};

export type SideTab = "examples" | "history" | "facts";
export type ExampleFilter = "all" | "beam" | "plate" | "solid" | "hole";

export type RunHistoryItem = {
  id: string;
  createdAt: string;
  request: string;
  result: StudioRunResponse;
};

export type Notice = {
  id: number;
  message: string;
  tone: "ok" | "bad";
};

export type RuntimeStatus = {
  ariaLabel: string;
  label: string;
  title: string;
  tone: "ok" | "warn" | "bad" | "neutral";
};

export type RenderModeIcon = (props: { size?: number; "aria-hidden"?: boolean }) => ReactNode;
