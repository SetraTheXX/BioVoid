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

test('molecular viewer spike renders a structure and exposes pocket focus', async ({ page }, testInfo) => {
  const syntheticPdb = [
    'HEADER    SYNTHETIC UI FIXTURE',
    'ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N',
    'ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00 20.00           C',
    'ATOM      3  C   ALA A   1       2.050   1.400   0.000  1.00 20.00           C',
    'ATOM      4  O   ALA A   1       1.400   2.400   0.000  1.00 20.00           O',
    'ATOM      5  N   GLY A   2       3.300   1.450   0.000  1.00 20.00           N',
    'ATOM      6  CA  GLY A   2       4.000   2.750   0.000  1.00 20.00           C',
    'ATOM      7  C   GLY A   2       5.450   2.450   0.000  1.00 20.00           C',
    'ATOM      8  O   GLY A   2       6.000   1.350   0.000  1.00 20.00           O',
    'END',
  ].join('\n');

  await page.route('**/jobs', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ job_id: 'molstar-job', status: 'queued' }),
    });
  });
  await page.route('**/jobs/molstar-job', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: 'molstar-job',
        status: 'succeeded',
        result: {
          run_id: 'e2e-run',
          pdb_id: '1CBS',
          total_cavities: 2,
          heuristic_shortlist_cavities: 1,
          runtime_seconds: 0.2,
          validation_status: 'recovery_unvalidated',
          canonical_eligible: false,
          cavities: [
            { id: 1, center: [1, 1, 1], volume: 120, bio_score: 0.8, heuristic_quality_tier: 'high' },
            { id: 2, center: [4, 3, 2], volume: 80, bio_score: 0.5, heuristic_quality_tier: 'medium' },
          ],
        },
      }),
    });
  });
  await page.route('**/protein/1CBS/structure**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'chemical/x-pdb', body: syntheticPdb });
  });

  await page.goto('/analyze');
  await page.getByPlaceholder('e.g. 1CBS').fill('1CBS');
  await page.getByRole('button', { name: 'Run Analysis' }).click();
  await expect(page.getByText('1CBS Results')).toBeVisible();
  await expect(page.getByText(/1CBS · ready/)).toBeVisible({ timeout: 30_000 });

  const canvas = page.locator('.molstar-spike-canvas canvas').first();
  await expect(canvas).toBeVisible();
  const desktopCanvas = await canvas.evaluate((element) => {
    const gl = element.getContext('webgl2') ?? element.getContext('webgl');
    if (!gl) return { width: 0, height: 0, renderer: null, pixelEnergy: 0 };
    const pixel = new Uint8Array(4);
    let pixelEnergy = 0;
    for (const [x, y] of [[1, 1], [gl.drawingBufferWidth / 2, gl.drawingBufferHeight / 2], [gl.drawingBufferWidth - 2, gl.drawingBufferHeight - 2]]) {
      gl.readPixels(Math.max(0, Math.floor(x)), Math.max(0, Math.floor(y)), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel);
      pixelEnergy += pixel[0] + pixel[1] + pixel[2] + pixel[3];
    }
    return {
      width: gl.drawingBufferWidth,
      height: gl.drawingBufferHeight,
      renderer: String(gl.getParameter(gl.RENDERER)),
      pixelEnergy,
    };
  });
  expect(desktopCanvas.width).toBeGreaterThan(0);
  expect(desktopCanvas.height).toBeGreaterThan(0);
  expect(desktopCanvas.renderer).toBeTruthy();
  expect(desktopCanvas.pixelEnergy).toBeGreaterThan(0);
  await page.screenshot({ path: testInfo.outputPath('molstar-desktop.png'), fullPage: true });

  await page.getByRole('combobox', { name: 'Focus pocket in molecular viewer' }).selectOption('2');
  await expect(page.getByText(/P2 center/)).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(canvas).toBeVisible();
  const mobileBox = await canvas.boundingBox();
  expect(mobileBox?.width ?? 0).toBeGreaterThan(300);
  expect(mobileBox?.height ?? 0).toBeGreaterThan(300);
  await page.screenshot({ path: testInfo.outputPath('molstar-mobile.png'), fullPage: true });
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
