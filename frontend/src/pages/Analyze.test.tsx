import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import Analyze from './Analyze';
import { api } from '../services/api';

vi.mock('react-plotly.js', () => ({
  default: () => <div data-testid="plot" />,
}));

vi.mock('../services/api', () => ({
  api: {
    submitJob: vi.fn(),
    jobStatus: vi.fn(),
  },
}));

describe('Analyze', () => {
  beforeEach(() => {
    vi.mocked(api.submitJob).mockReset();
    vi.mocked(api.jobStatus).mockReset();
  });

  it('submits, polls, and renders a completed result', async () => {
    vi.mocked(api.submitJob).mockResolvedValue({ job_id: 'job-1', status: 'queued' });
    vi.mocked(api.jobStatus).mockResolvedValue({
      job_id: 'job-1',
      status: 'succeeded',
      result: {
        pdb_id: '1CBS',
        total_cavities: 2,
        heuristic_shortlist_cavities: 1,
        high_druggability: 1,
        runtime_seconds: 0.4,
        validation_status: 'recovery_unvalidated',
        canonical_eligible: false,
        cavities: [],
      },
    });

    render(<Analyze />);
    fireEvent.change(screen.getByPlaceholderText('e.g. 1CBS'), {
      target: { value: '1CBS' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Run Analysis' }));

    await waitFor(() => expect(screen.getByText('Complete')).toBeInTheDocument());
    expect(screen.getByText('1CBS Results')).toBeInTheDocument();
    expect(api.submitJob).toHaveBeenCalledWith(
      '1CBS',
      'default',
      expect.stringMatching(/^frontend-/),
      expect.any(AbortSignal),
    );
    expect(api.jobStatus).toHaveBeenCalledWith('job-1', expect.any(AbortSignal));
  });
});
