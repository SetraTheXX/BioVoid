import { expect, test } from '@playwright/test';

test('production FastAPI serves the canonical React application', async ({ page }) => {
  const health = await page.request.get('/health');
  expect(health.ok()).toBeTruthy();

  await page.goto('/');
  await expect(page.getByText('BioVoid')).toBeVisible();
  await expect(page.getByRole('link', { name: /Analyze/ })).toBeVisible();
});

test('submit, poll, and result smoke', async ({ page }) => {
  await page.route('**/jobs', async (route) => {
    if (route.request().method() === 'POST') {
      const body = route.request().postDataJSON();
      expect(body.job_type).toBe('full_analysis');
      expect(body.options.mode).toBe('static');
      await route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'e2e-job', status: 'queued' }),
      });
      return;
    }
    await route.continue();
  });
  await page.route('**/jobs/e2e-job', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'e2e-job',
        status: 'succeeded',
        result: {
          pdb_id: '1CBS',
          total_cavities: 2,
          heuristic_shortlist_cavities: 1,
          high_druggability: 1,
          runtime_seconds: 0.2,
          validation_status: 'recovery_unvalidated',
          canonical_eligible: false,
          cavities: [],
        },
      }),
    });
  });

  await page.goto('/analyze');
  await page.getByPlaceholder('e.g. 1CBS').fill('1CBS');
  await page.getByRole('button', { name: 'Run Analysis' }).click();

  await expect(page.getByText('Complete')).toBeVisible();
  await expect(page.getByText('1CBS Results')).toBeVisible();
});

test('Atlas pagination advances without a backend', async ({ page }) => {
  const items = Array.from({ length: 10 }, (_, index) => ({
    pdb_id: `T${String(index).padStart(3, '0')}`,
    pocket_id: `BV-${index + 1}`,
    run_id: `run-${index + 1}`,
    prepared_sha256: 'a'.repeat(64),
    bio_score: 0.5,
    volume: 100 + index,
    heuristic_quality_tier: 'medium',
    heuristic_shortlist: false,
    validation_status: 'recovery_unvalidated',
    canonical_eligible: false,
    detector_version: 'canonical-static-v1',
    scoring_contract_version: 'heuristic-pocket-ranking-v1',
    profile_used: 'Default',
    rank: index + 1,
    sphericity: 0.4,
    merged_vertices: 5,
  }));
  await page.route('**/atlas/pockets?**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items,
        count: items.length,
        total: 25,
        limit: 10,
        offset: 0,
      }),
    });
  });
  await page.route('**/atlas/overview', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"summary":{}}' })
  );
  await page.route('**/jobs?**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"jobs":[]}' })
  );
  await page.route('**/ops/metrics', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
  );

  await page.goto('/');
  await page.getByRole('link', { name: /Atlas/ }).click();
  await expect(page.getByText('Page 1 / 3')).toBeVisible();
  await page.getByRole('button', { name: 'Next' }).click();
  await expect(page.getByText('Page 2 / 3')).toBeVisible();
});

test('narrow-screen navigation is keyboard accessible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/system');
  await expect(page.getByRole('navigation', { name: 'Primary navigation' })).toBeVisible();

  const analyzeLink = page.getByRole('link', { name: /Analyze/ });
  await analyzeLink.focus();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/analyze$/);
  await expect(page.getByRole('heading', { name: /New Analysis/ })).toBeVisible();
});

test('offline system state exposes a user-visible error', async ({ page }) => {
  await page.route('**/health', (route) => route.abort());
  await page.goto('/system');

  await expect(page.getByRole('heading', { name: /System/ })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('Backend not reachable');
});
