import type {
  StageKey,
  StageState,
  StudioJobResponse,
  StudioProgressEvent,
  StudioRunResponse,
  TaskError,
  WorkflowSummary
} from "../types";
import { NODE_ORDER, STAGES } from "./constants";
import { formatEventTime } from "./format";
import type { StageRow } from "./uiTypes";

export function buildStageRows(
  result: StudioRunResponse | null,
  running: boolean,
  job: StudioJobResponse | null
): StageRow[] {
  return STAGES.map((stage) => {
    const event = latestStageEvent(stage.key, job);
    return {
      ...stage,
      state: stageState(stage.key, result, running, job, event),
      eventMessage: event?.message ?? "",
      eventTime: event ? formatEventTime(event.timestamp) : ""
    };
  });
}

export function stageCaption(stage: StageRow) {
  if (!stage.eventMessage) {
    return stage.caption;
  }
  return stage.eventTime ? `${stage.caption} · ${stage.eventTime}` : stage.caption;
}

export function stageState(
  key: StageKey,
  result: StudioRunResponse | null,
  running: boolean,
  job: StudioJobResponse | null,
  event: StudioProgressEvent | null = latestStageEvent(key, job)
): StageState {
  const eventState = stageEventState(event);
  if (eventState) {
    return eventState;
  }
  if (running) {
    return "pending";
  }
  if (!result) {
    return "idle";
  }
  const errorNode = firstErrorNode(result.summary);
  if (!errorNode) {
    return result.summary.tasks?.length ? "complete" : "idle";
  }
  if (key === "reporter" && result.report) {
    return "complete";
  }
  const errorIndex = NODE_ORDER.indexOf(errorNode);
  const currentIndex = NODE_ORDER.indexOf(key);
  if (errorNode === key) {
    return "failed";
  }
  if (errorIndex >= 0 && currentIndex > errorIndex) {
    return "idle";
  }
  return result.summary.tasks?.length ? "complete" : "idle";
}

export function stageStateLabel(state: StageState) {
  if (state === "complete") {
    return "完成";
  }
  if (state === "pending") {
    return "等待";
  }
  if (state === "running") {
    return "运行";
  }
  if (state === "failed") {
    return "失败";
  }
  return "等待";
}

export function firstErrorNode(summary: WorkflowSummary): StageKey | null {
  const error = summary.errors?.[0] ?? summary.tasks?.find((task) => task.error)?.error;
  return normalizeErrorNode(error);
}

export function normalizeErrorNode(error?: TaskError | null): StageKey | null {
  const node = error?.node;
  if (!node) {
    return null;
  }
  if (node === "postproc") {
    return "postproc";
  }
  if (NODE_ORDER.includes(node as StageKey)) {
    return node as StageKey;
  }
  return null;
}

export function latestStageEvent(
  key: StageKey,
  job: StudioJobResponse | null
): StudioProgressEvent | null {
  if (!job?.events?.length) {
    return null;
  }
  const event = [...job.events].reverse().find((item) => item.stage === key);
  if (!event) {
    return null;
  }
  return event;
}

export function stageEventState(event: StudioProgressEvent | null): StageState | null {
  if (!event) {
    return null;
  }
  if (event.status === "running") {
    return "running";
  }
  if (event.status === "complete") {
    return "complete";
  }
  return "failed";
}
