const BASE = '';

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

async function post<T>(path: string, body: unknown, headers?: Record<string, string>): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.json();
}

export async function getText(path: string): Promise<string> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API ${res.status}: ${path}`);
  return res.text();
}

export const api = {
  health: () => get<{ status: string }>('/health'),
  overview: () => get<any>('/atlas/overview'),
  pockets: (params = '') => get<any>(`/atlas/pockets?limit=25${params}`),
  proteinDetail: (id: string) => get<any>(`/protein/${id}/detail`),
  proteinStructure: (id: string) => getText(`/protein/${id}/structure`),
  submitJob: (pdbId: string, frames: number, profile: string) =>
    post<any>(
      '/jobs',
      {
        job_type: 'full_analysis',
        input: { pdb_id: pdbId },
        options: { n_frames: frames, profile },
      },
      { 'Idempotency-Key': `frontend-${pdbId}-${Date.now()}` }
    ),
  jobStatus: (id: string) => get<any>(`/jobs/${id}`),
  jobs: () => get<any>('/jobs?limit=50'),
  opsMetrics: () => get<any>('/ops/metrics'),
};
