export type StageKey =
  | "planner"
  | "designer"
  | "mesh"
  | "solver"
  | "postproc"
  | "analyst"
  | "reporter";

export type StageState = "idle" | "running" | "complete" | "failed";

export interface StudioHealth {
  ok: boolean;
  product: string;
  config: string;
  static_ready: boolean;
}

export interface AgentTrace {
  agent: string;
  used: boolean;
  error: string | null;
  prompt_chars: number;
  response_chars: number;
}

export interface SolverResult {
  success?: boolean;
  model_case_id?: string;
  quantity?: string;
  unit?: string;
  predicted?: number | null;
  reference?: number | null;
  relative_error?: number | null;
  tolerance?: number | null;
  passed?: boolean;
  verification_status?: string;
  solver?: string;
  output_files?: string[];
  mesh_file?: string | null;
  mesh_metadata?: Record<string, unknown>;
  values?: Record<string, unknown>;
}

export interface MeshResult {
  success?: boolean;
  mesh_file?: string | null;
  element_count?: number;
  node_count?: number;
  quality?: Record<string, number>;
  metadata?: Record<string, unknown>;
  error_message?: string | null;
}

export interface TaskError {
  node: string;
  code?: string;
  message: string;
  missing_fields?: string[];
}

export interface TaskSummary {
  task_id: string;
  case_id: string;
  capability_id?: string;
  title: string;
  analysis_type?: string;
  intent?: Record<string, unknown> | null;
  planner_llm_trace?: AgentTrace | null;
  designer_llm_trace?: AgentTrace | null;
  model_params?: Record<string, unknown> | null;
  mesh_llm_trace?: AgentTrace | null;
  mesh_result?: MeshResult | null;
  solver_result?: SolverResult | null;
  post_summary?: Record<string, unknown> | null;
  analysis_text?: string;
  error?: TaskError | null;
}

export interface WorkflowSummary {
  success?: boolean;
  work_dir?: string | null;
  report_path?: string | null;
  reporter_llm_trace?: AgentTrace | null;
  tasks?: TaskSummary[];
  errors?: TaskError[];
}

export interface Visualization {
  task_id: string;
  title: string;
  kind: string;
  svg: string;
  caption: string;
}

export interface StudioRunResponse {
  success: boolean;
  report: string;
  summary: WorkflowSummary;
  visualizations: Visualization[];
  metadata?: { duration_ms?: number };
  error?: string;
}
