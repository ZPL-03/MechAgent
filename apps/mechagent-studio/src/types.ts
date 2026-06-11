export type StageKey =
  | "planner"
  | "designer"
  | "mesh"
  | "solver"
  | "postproc"
  | "analyst"
  | "reporter";

export type StageState = "idle" | "pending" | "running" | "complete" | "failed";

export interface StudioHealth {
  ok: boolean;
  product: string;
  config: string;
  python_executable: string;
  static_ready: boolean;
}

export interface StudioDiagnosticCheck {
  key: string;
  label: string;
  ok: boolean;
  required: boolean;
  details: Record<string, unknown>;
}

export interface StudioDiagnosticsResponse {
  ok: boolean;
  config_path: string;
  checks: StudioDiagnosticCheck[];
  summary: {
    required_passed: number;
    required_total: number;
    optional_passed: number;
    optional_total: number;
  };
}

export interface StudioCapability {
  capability_id: string;
  task_case_id: string;
  title: string;
  analysis_type: string;
  physics_domain: string;
  solver_name: string;
  mesher_name: string;
  model_case_ids: string[];
  example_requests: string[];
  planner_description: string;
}

export interface StudioCapabilitiesResponse {
  capabilities: StudioCapability[];
}

export interface StudioExample {
  example_id: string;
  case_id: string;
  title: string;
  request: string;
  capability_id: string;
  geometry_type: string;
  load_type: string;
  model_case_id: string;
  tags: string[];
}

export interface StudioExamplesResponse {
  examples: StudioExample[];
}

export interface StudioInspectionTask {
  task_id: string;
  case_id: string;
  capability_id: string;
  title: string;
  analysis_type: string;
  complete: boolean;
  missing_fields: string[];
  geometry_type: string | null;
  confidence: number | null;
  source: string;
}

export interface StudioInspectionResponse {
  success: boolean;
  ready: boolean;
  request: string;
  tasks: StudioInspectionTask[];
  errors: TaskError[];
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
  scene?: VisualizationScene | null;
}

export interface VisualizationSceneNode {
  id: number;
  position: [number, number, number];
  displacement: [number, number, number];
  scalar: number;
  fields?: Record<string, number>;
}

export interface VisualizationSceneElement {
  id: number;
  nodes: number[];
}

export interface VisualizationLoad {
  type: string;
  magnitude: number | null;
  region: string;
  direction: [number, number, number];
}

export interface VisualizationBoundaryCondition {
  type: string;
  region: string;
  dofs: string[];
  values: number[];
}

export interface VisualizationScene {
  task_id: string;
  task_title: string;
  mode: "geometry" | "mesh" | "result";
  geometry_type: string;
  dimensions: Record<string, number>;
  mesh: {
    element_type: string;
    seed_size: number | null;
    node_count: number;
    element_count: number;
    source: string;
    quality?: Record<string, unknown>;
  };
  nodes: VisualizationSceneNode[];
  elements: VisualizationSceneElement[];
  scalar: {
    name: string;
    unit: string;
    min: number;
    max: number;
  };
  fields?: Array<{
    key: string;
    name: string;
    unit: string;
    kind: string;
    min: number;
    max: number;
  }>;
  loads?: VisualizationLoad[];
  boundary_conditions?: VisualizationBoundaryCondition[];
  deformation_scale: number;
  bounds: {
    original: {
      min: [number, number, number];
      max: [number, number, number];
    };
    deformed: {
      min: [number, number, number];
      max: [number, number, number];
    };
  };
  camera: {
    position: [number, number, number];
    target: [number, number, number];
    up: [number, number, number];
  };
  result: {
    quantity: string;
    unit: string;
    predicted: number | null;
    reference: number | null;
    relative_error: number | null;
    tolerance: number | null;
    passed: boolean;
    verification_status: string;
  };
  has_real_mesh: boolean;
  has_real_results: boolean;
}

export interface StudioRunResponse {
  success: boolean;
  report: string;
  summary: WorkflowSummary;
  visualizations: Visualization[];
  metadata?: { duration_ms?: number };
  error?: string;
}

export type StudioJobStatus = "queued" | "running" | "succeeded" | "failed";

export interface StudioProgressEvent {
  stage: StageKey;
  status: "running" | "complete" | "failed";
  message: string;
  timestamp: string;
}

export interface StudioJobResponse {
  job_id: string;
  status: StudioJobStatus;
  request: string;
  use_llm_agents: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  result: StudioRunResponse | null;
  error: string | null;
  events: StudioProgressEvent[];
}
