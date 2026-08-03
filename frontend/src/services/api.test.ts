import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from './api';
import { ApiClientError } from '../types/api';

describe('analysis API contract', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('submits a real full-analysis job with typed static defaults', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ job_id: 'job-1', status: 'queued' }), {
        status: 202,
        headers: { 'Content-Type': 'application/json' },
      })
    );
    vi.stubGlobal('fetch', fetchMock);

    const response = await api.submitJob('1CBS', 'default', 'stable-request-key');

    expect(response.job_id).toBe('job-1');
    const [path, options] = fetchMock.mock.calls[0];
    expect(path).toBe('/jobs');
    const body = JSON.parse(String(options.body));
    expect(body).toEqual({
      job_type: 'full_analysis',
      input: { pdb_id: '1CBS' },
      options: {
        profile: 'default',
        mode: 'static',
        structure_source: 'rcsb',
        representation: 'biological_assembly',
        assembly_id: '1',
      },
    });
    expect(options.headers['Idempotency-Key']).toBe('stable-request-key');
  });

  it('preserves structured API errors and correlation IDs', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'ATLAS_UNAVAILABLE',
              message: 'Atlas is not available in this environment.',
              details: { storage: 'missing' },
            },
          }),
          {
            status: 503,
            headers: {
              'Content-Type': 'application/json',
              'X-Correlation-ID': 'corr-phase7-1',
            },
          },
        ),
      ),
    );

    await expect(api.overview()).rejects.toMatchObject({
      name: 'ApiClientError',
      status: 503,
      code: 'ATLAS_UNAVAILABLE',
      correlationId: 'corr-phase7-1',
      message: 'Atlas is not available in this environment.',
    });
    await expect(api.overview()).rejects.toBeInstanceOf(ApiClientError);
  });
});
