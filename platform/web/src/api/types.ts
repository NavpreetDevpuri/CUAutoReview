export type Id = string;

export interface SessionUser {
  id: Id;
  name: string;
  email: string;
  role: string;
  workspace_id?: Id;
  [key: string]: unknown;
}

export interface Episode {
  episode_id?: Id;
  problem_number?: number;
  first_observed_step_id?: Id;
  label_id?: Id;
  label_name?: string;
  mechanism?: string;
  onset_step_ids?: Id[];
  recovery?: { status?: string; step_ids?: Id[]; rationale?: string; evidence_refs?: unknown[] };
  uncertainty?: string;
  evidence_refs?: unknown[];
  [key: string]: unknown;
}

export interface ReviewStep {
  step_id?: Id;
  review_status?: string;
  intent?: unknown;
  action?: unknown;
  observed_ui?: unknown;
  effect?: unknown;
  assessment?: unknown;
  episode_refs?: Id[];
  evidence_refs?: unknown[];
  [key: string]: unknown;
}

export interface TrajectoryStep {
  step_id?: Id;
  intent?: unknown;
  action?: unknown;
  observation?: unknown;
  screenshot_url?: string;
  screenshot?: string;
  episode_refs?: Id[];
  evidence_refs?: unknown[];
  [key: string]: unknown;
}

export interface FlaggedLabelSummary {
  id?: string;
  name: string;
  count: number;
}

export interface ReviewEvidenceProvenance {
  evidence_mode?: "images_and_text" | "text_only" | string;
  source_image_step_ids?: string[];
  supplied_image_step_ids?: string[];
  omitted_image_step_ids?: string[];
  cited_image_step_ids?: string[];
  inspected_image_step_ids?: string[];
  source_step_count?: number;
  image_selection?: "all_available" | "sampled" | "none" | string;
  omitted_image_reason?: string;
  [key: string]: unknown;
}

export interface ReviewAttemptRecord {
  attempt_number: number;
  status?: string;
  error?: string | null;
  usage?: Record<string, unknown> | null;
  cost_usd?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface ReviewJobRecord {
  id: string;
  job_id?: string;
  run_id?: string;
  batch_id?: string;
  task_id?: string;
  task_title?: string;
  status?: string;
  attempt_count?: number;
  max_attempts?: number;
  error?: string | null;
  attempts?: ReviewAttemptRecord[];
  usage?: Record<string, unknown> | null;
  cost_usd?: number | null;
  retry_allowed?: boolean;
  [key: string]: unknown;
}

export interface TaskReviewSummary {
  /** Saved ReviewResult rows for this run member, including superseded revisions. */
  review_count?: number;
  review_status?: "saved" | "missing" | string;
  problem_count?: number;
  flagged_step_ids?: string[];
  flagged_step_count?: number;
  recovery_step_count?: number;
  flagged_labels?: FlaggedLabelSummary[];
  source_image_step_ids?: string[];
  supplied_image_step_ids?: string[];
  omitted_image_step_ids?: string[];
  cited_image_step_ids?: string[];
  source_image_count?: number;
  supplied_image_count?: number;
  omitted_image_count?: number;
  cited_image_count?: number;
  evidence_mode?: string;
  [key: string]: unknown;
}

export interface DatasetTaskModelSummary {
  backend?: string;
  model?: string;
  current_review_count?: number;
  historical_review_count?: number;
  current_problem_count?: number;
  historical_problem_count?: number;
  current_flagged_step_count?: number;
  historical_flagged_step_count?: number;
  current_flagged_labels?: FlaggedLabelSummary[];
  historical_flagged_labels?: FlaggedLabelSummary[];
  evidence_mode?: string;
  source_image_count?: number;
  supplied_image_count?: number;
  cited_image_count?: number;
  omitted_image_count?: number;
  source_image_step_ids?: string[];
  supplied_image_step_ids?: string[];
  cited_image_step_ids?: string[];
  omitted_image_step_ids?: string[];
  known_cost_usd?: number;
  unknown_cost_attempts?: number;
  [key: string]: unknown;
}

export interface DatasetTaskSummary {
  run_count?: number;
  saved_review_count?: number;
  missing_review_count?: number;
  review_revision_count?: number;
  historical_review_count?: number;
  problem_count?: number;
  historical_problem_count?: number;
  flagged_step_count?: number;
  historical_flagged_step_count?: number;
  recovery_step_count?: number;
  flagged_labels?: FlaggedLabelSummary[];
  models?: DatasetTaskModelSummary[];
  source_image_step_ids?: string[];
  source_image_count?: number;
  supplied_image_step_ids?: string[];
  supplied_image_count?: number;
  omitted_image_step_ids?: string[];
  omitted_image_count?: number;
  cited_image_step_ids?: string[];
  cited_image_count?: number;
  known_cost_usd?: number;
  unknown_cost_attempts?: number;
  latest_run_evidence?: ReviewEvidenceProvenance;
  [key: string]: unknown;
}

export interface TaskRecord {
  id?: Id;
  task_id: Id;
  title?: string;
  instruction?: string;
  outcome?: string | boolean | null;
  score?: number | null;
  benchmark_result?: string | boolean | null;
  status?: string;
  processing_status?: string;
  review_status?: string;
  review_kind?: string;
  review_summary?: TaskReviewSummary;
  review_provenance?: ReviewEvidenceProvenance | null;
  job_id?: string | null;
  jobs?: ReviewJobRecord[];
  summary?: DatasetTaskSummary;
  source?: Record<string, unknown>;
  steps?: TrajectoryStep[];
  review?: {
    schema_version?: string;
    review_kind?: string;
    summary?: string;
    steps?: ReviewStep[];
    episodes?: Episode[];
    result?: string;
    coverage_notes?: string[];
    [key: string]: unknown;
  } | null;
  raw_url?: string;
  [key: string]: unknown;
}

export interface DatasetRecord {
  id: Id;
  name: string;
  description?: string;
  source_adapter?: string;
  task_count?: number;
  batches?: BatchRecord[];
  tasks?: TaskRecord[];
  [key: string]: unknown;
}

export interface BatchRecord {
  id: Id;
  name: string;
  description?: string;
  dataset_id?: Id;
  preset_id?: Id;
  mode?: "fixed" | "appendable" | string;
  status?: string;
  processing_status?: string;
  outcome_summary?: Record<string, unknown>;
  review_summary?: TaskReviewSummary;
  progress?: Record<string, unknown>;
  waves?: unknown[];
  grants?: unknown[];
  tasks?: TaskRecord[];
  [key: string]: unknown;
}

export interface TaxonomyResponse {
  releases?: Record<string, unknown>[];
  proposals?: Record<string, unknown>[];
  candidates?: Record<string, unknown>[];
  labels?: Record<string, unknown>[];
  [key: string]: unknown;
}

export interface ListResult<T> {
  items: T[];
  total: number;
}

export interface ApiErrorShape {
  detail?: unknown;
  message?: string;
}
