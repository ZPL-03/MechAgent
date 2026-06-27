import type { StudioRunResponse, TaskSummary, Visualization } from "../types";
import { RESULT_RENDER_MODE_INDEX } from "./constants";

export function visualizationsForTask(visuals: Visualization[], task: TaskSummary | null) {
  if (!task) {
    return visuals;
  }
  const matched = visuals.filter((visual) => visual.task_id === task.task_id);
  return matched.length > 0 ? matched : visuals;
}

export function defaultRenderModeIndex(
  runResult: StudioRunResponse | null,
  task: TaskSummary | null = null
) {
  if (!runResult?.success || RESULT_RENDER_MODE_INDEX < 0) {
    return 0;
  }
  const selectedTask = task ?? runResult.summary.tasks?.[0] ?? null;
  const visuals = visualizationsForTask(runResult.visualizations, selectedTask);
  return visuals.some((visual) => visual.scene?.has_real_results) ? RESULT_RENDER_MODE_INDEX : 0;
}
