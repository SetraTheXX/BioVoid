import type { components } from './openapi';

export type AtlasPocketContract = components['schemas']['AtlasPocketResponse'];
export type JobStatus = components['schemas']['JobStatus'];

export interface JsonObject {
  [key: string]: unknown;
}

export interface ApiErrorPayload {
  code?: string;
  message?: string;
  details?: JsonObject;
  correlation_id?: string;
}

export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId: string | null;
  readonly details: JsonObject;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string;
      correlationId?: string | null;
      details?: JsonObject;
    },
  ) {
    super(message);
    this.name = 'ApiClientError';
    this.status = options.status;
    this.code = options.code ?? 'API_ERROR';
    this.correlationId = options.correlationId ?? null;
    this.details = options.details ?? {};
  }
}

export interface ScoreComponents {
  volume_score?: number;
  hydrophobicity_score?: number;
  enclosure_score?: number;
  depth_score?: number;
  sphericity?: number;
}

export interface Pocket extends Partial<AtlasPocketContract> {
  id?: number;
  pocket_id?: string;
  rank?: number;
  pdb_id?: string;
  run_id?: string;
  prepared_sha256?: string;
  bio_score?: number;
  volume?: number;
  hydrophobic_ratio?: number | null;
  enclosure_score?: number | null;
  depth_score?: number | null;
  sphericity?: number;
  merged_vertices?: number;
  heuristic_quality_tier?: 'high' | 'medium' | 'low';
  heuristic_shortlist?: boolean;
  validation_status?: string;
  canonical_eligible?: boolean;
  detector_version?: string;
  scoring_contract_version?: string;
  center?: [number, number, number] | null;
  center_x?: number;
  center_y?: number;
  center_z?: number;
  volume_score?: number | null;
  score_components?: ScoreComponents;
}

export interface AnalysisResult {
  run_id?: string;
  pdb_id?: string;
  resource_profile?: string;
  structure_source?: {
    provider?: string;
    identifier?: string;
    representation?: string;
    assembly_id?: string | null;
    model_entity_id?: string | null;
  };
  total_cavities?: number;
  total_voids?: number;
  heuristic_shortlist_cavities?: number;
  high_druggability?: number;
  runtime_seconds?: number;
  validation_status?: string;
  canonical_eligible?: boolean;
  analysis_contract?: {
    preparation_policy_version?: string;
    detector_version?: string;
    scoring_contract_version?: string;
    ranking_contract?: string;
    validation_status?: string;
    canonical_eligible?: boolean;
  };
  preparation?: PreparationSummary;
  provenance?: JsonObject;
  scoring?: {
    contract_version?: string;
    ranking_contract_version?: string;
    motion_affects_canonical_score?: boolean;
    raw_measurements_stored_separately?: boolean;
  };
  motion_sampling?: {
    mode_count?: number;
    samples_per_mode?: number;
    requested_sample_count?: number;
  };
  motion_aware?: {
    status?: string;
    canonical_ranking_affected?: boolean;
    quality_counts?: JsonObject;
    accepted_sample_count?: number;
    accepted_mode_count?: number;
  };
  motion?: MotionSummary;
  cavities?: Pocket[];
}

export interface PreparationSummary {
  schema_version?: string;
  status?: string;
  preparation_policy_version?: string;
  policy_version?: string;
  source_provider?: string;
  source_identifier?: string;
  representation?: string;
  assembly_id?: string | null;
  source?: {
    provider?: string;
    identifier?: string;
    representation?: string;
    assembly_id?: string | null;
  };
  selected_chains?: string[];
  removed_components?: string[];
  preserved_components?: string[];
  prepared_sha256?: string;
  context_components?: JsonObject;
  hashes?: {
    input_sha256?: string;
    prepared_sha256?: string;
    preparation_config_sha256?: string;
  };
  warnings?: string[];
}

export interface MotionSummary {
  status?: string;
  canonical_ranking_affected?: boolean;
  frames_total?: number;
  frames_accepted?: number;
  frames_accepted_with_warnings?: number;
  frames_rejected?: number;
  quality_counts?: JsonObject;
  accepted_sample_count?: number;
  accepted_mode_count?: number;
}

export interface JobSubmission {
  job_id: string;
  status: JobStatus;
  idempotent_reused?: boolean;
  created_at_utc?: string;
}

export interface JobDetail {
  job_id: string;
  status: JobStatus;
  created_at_utc?: string;
  result?: AnalysisResult;
  error?: JobError | string | null;
}

export interface JobError {
  code?: string;
  message?: string;
  detail?: string | null;
  attempts?: number;
}

export interface JobListItem {
  job_id: string;
  pdb_id: string;
  status: string;
  created_at_utc?: string;
}

export interface JobListResponse {
  jobs: JobListItem[];
  count: number;
}

export interface AtlasSummary {
  total_proteins?: number;
  total_pockets?: number;
  heuristic_shortlist_pockets?: number;
  avg_bio_score?: number;
}

export interface AtlasOverviewResponse {
  available?: boolean;
  summary?: AtlasSummary;
  statistics?: AtlasSummary;
  message?: string;
  correlation_id?: string | null;
}

export type AtlasPocketsResponse = components['schemas']['AtlasPocketsResponse'];

export type ProteinDetail = components['schemas']['ProteinDetailResponse'] & {
  structure_source?: AnalysisResult['structure_source'];
  preparation?: PreparationSummary;
  provenance?: JsonObject;
  scoring?: AnalysisResult['scoring'];
  motion_sampling?: AnalysisResult['motion_sampling'];
  motion_aware?: AnalysisResult['motion_aware'];
};

export interface OpsMetrics {
  avg_job_latency_seconds?: number;
  p95_job_latency_seconds?: number;
  succeeded_jobs?: number;
  failed_jobs?: number;
  queue_depth?: number;
}

export function errorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiClientError) {
    return error.correlationId
      ? `${error.message} (request ${error.correlationId})`
      : error.message;
  }
  return error instanceof Error ? error.message : fallback;
}

export function errorCorrelationId(error: unknown): string | null {
  return error instanceof ApiClientError ? error.correlationId : null;
}
