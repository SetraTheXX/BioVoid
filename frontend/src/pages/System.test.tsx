import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import System from './System';
import { api } from '../services/api';
import { ApiClientError } from '../types/api';

vi.mock('../services/api', () => ({
  api: {
    health: vi.fn(),
  },
}));

describe('System', () => {
  beforeEach(() => {
    vi.mocked(api.health).mockReset();
  });

  it('shows an actionable offline error with the correlation ID', async () => {
    vi.mocked(api.health).mockRejectedValue(
      new ApiClientError('Health endpoint unavailable', {
        status: 503,
        code: 'SERVICE_UNAVAILABLE',
        correlationId: 'corr-system-1',
      }),
    );

    render(<System />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('alert')).toHaveTextContent('Backend not reachable');
    expect(screen.getByRole('alert')).toHaveTextContent('corr-system-1');
  });
});
