import { ApiClientError } from '../types/api';
import type {
  ApiErrorPayload,
  AtlasOverviewResponse,
  AtlasPocketsResponse,
  JobDetail,
  JobListResponse,
  JobSubmission,
  JsonObject,
  OpsMetrics,
  ProteinDetail,
} from '../types/api';

const BASE = '';

function isJsonObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function errorPayload(value: unknown): ApiErrorPayload {
  if (!isJsonObject(value)) return {};
  const nested = isJsonObject(value.error) ? value.error : value;
  return {
    code: typeof nested.code === 'string' ? nested.code : undefined,
    message: typeof nested.message === 'string' ? nested.message : undefined,
    details: isJsonObject(nested.details) ? nested.details : undefined,
    correlation_id:
      typeof nested.correlation_id === 'string' ? nested.correlation_id : undefined,
  };
}

async function parseResponse<T>(res: Response, path: string): Promise<T> {
  if (!res.ok) {
    let payload: unknown;
    try {
      payload = await res.json();
    } catch {
      payload = undefined;
    }
    const parsed = errorPayload(payload);
    throw new ApiClientError(
      parsed.message ?? `API request failed (${res.status})`,
      {
        status: res.status,
        code: parsed.code,
        correlationId: res.headers.get('X-Correlation-ID') ?? parsed.correlation_id,
        details: { path, ...(parsed.details ?? {}) },
      },
    );
  }
  return (await res.json()) as T;
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { signal });
  return parseResponse<T>(res, path);
}

async function post<T>(
  path: string,
  body: unknown,
  headers?: Record<string, string>,
  signal?: AbortSignal,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
    signal,
  });
  return parseResponse<T>(res, path);
}

export async function getText(path: string, signal?: AbortSignal): Promise<string> {
  const res = await fetch(`${BASE}${path}`, { signal });
  if (!res.ok) {
    let payload: unknown;
    try {
      payload = await res.json();
    } catch {
      payload = undefined;
    }
    const parsed = errorPayload(payload);
    throw new ApiClientError(
      parsed.message ?? `API request failed (${res.status})`,
      {
        status: res.status,
        code: parsed.code,
        correlationId: res.headers.get('X-Correlation-ID') ?? parsed.correlation_id,
        details: { path, ...(parsed.details ?? {}) },
      },
    );
  }
  return res.text();
}

export const api = {
  health: (signal?: AbortSignal) =>
    get<{ status: string; correlation_id?: string }>('/health', signal),
  overview: (signal?: AbortSignal) => get<AtlasOverviewResponse>('/atlas/overview', signal),
  pockets: (options: {
    limit: number;
    offset: number;
    tier?: string;
    pdbId?: string;
    signal?: AbortSignal;
  }, signal?: AbortSignal) => {
    const params = new URLSearchParams({
      limit: String(options.limit),
      offset: String(options.offset),
    });
    if (options.tier) params.set('druggability_class', options.tier);
    if (options.pdbId) params.set('pdb_id', options.pdbId);
    return get<AtlasPocketsResponse>(`/atlas/pockets?${params}`, signal ?? options.signal);
  },
  proteinDetail: (id: string, runId?: string, signal?: AbortSignal) => {
    const params = runId ? `?run_id=${encodeURIComponent(runId)}` : '';
    return get<ProteinDetail>(`/protein/${id}/detail${params}`, signal);
  },
  proteinStructure: (id: string, runId: string, signal?: AbortSignal) =>
    getText(
      `/protein/${id}/structure?run_id=${encodeURIComponent(runId)}`,
      signal,
    ),
  submitJob: (pdbId: string, profile: string, idempotencyKey: string, signal?: AbortSignal) =>
    post<JobSubmission>(
      '/jobs',
      {
        job_type: 'full_analysis',
        input: { pdb_id: pdbId },
        options: {
          profile,
          mode: 'static',
          structure_source: 'rcsb',
          representation: 'biological_assembly',
          assembly_id: '1',
        },
      },
      { 'Idempotency-Key': idempotencyKey },
      signal,
    ),
  jobStatus: (id: string, signal?: AbortSignal) =>
    get<JobDetail>(`/jobs/${id}`, signal),
  cancelJob: (id: string, signal?: AbortSignal) =>
    post<{ status: string }>(`/jobs/${id}/cancel`, {}, undefined, signal),
  jobs: (signal?: AbortSignal) => get<JobListResponse>('/jobs?limit=50', signal),
  opsMetrics: (signal?: AbortSignal) => get<OpsMetrics>('/ops/metrics', signal),
};
