"""Portal page renderer for unified BioVoid operations + discovery UI."""

from __future__ import annotations


def render_portal_html() -> str:
    """Return portal HTML."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BioVoid Phase 6 Portal</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link rel="preload" as="style" href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Manrope:wght@400;600;700;800&display=swap" />
  <link href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Manrope:wght@400;600;700;800&display=swap" rel="stylesheet" />
  <style>
    :root {
      --bg-0: #f3eee6;
      --bg-1: #e6f0ec;
      --ink: #1d2830;
      --ink-soft: #4e5f6d;
      --line: #cfd8de;
      --card: #fffdf9;
      --brand: #146c63;
      --brand-strong: #0f4f49;
      --accent: #d86f39;
      --warn: #b45309;
      --danger: #b42318;
      --ok: #13795b;
      --shadow: 0 24px 44px rgba(22, 34, 45, 0.12);
      --radius: 16px;
    }
    * { box-sizing: border-box; }
    html, body { min-height: 100%; }
    body {
      margin: 0;
      color: var(--ink);
      font-family: "Manrope", "Segoe UI", sans-serif;
      line-height: 1.5;
      -webkit-tap-highlight-color: rgba(20, 108, 99, 0.22);
      background:
        radial-gradient(1000px 520px at 12% -10%, #dbece4 0%, rgba(219, 236, 228, 0) 60%),
        radial-gradient(840px 420px at 92% 2%, #fbe3d6 0%, rgba(251, 227, 214, 0) 62%),
        linear-gradient(160deg, var(--bg-0), var(--bg-1));
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(0deg, rgba(29, 40, 48, 0.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(29, 40, 48, 0.035) 1px, transparent 1px);
      background-size: 20px 20px;
      opacity: 0.28;
      z-index: -1;
    }
    .skip-link {
      position: absolute;
      left: 10px;
      top: -48px;
      padding: 8px 12px;
      border-radius: 8px;
      color: #fff;
      background: var(--brand-strong);
      z-index: 1000;
      text-decoration: none;
    }
    .skip-link:focus-visible { top: 10px; }
    .shell {
      max-width: 1220px;
      margin: 0 auto;
      padding: 22px 16px 38px;
      display: grid;
      gap: 16px;
    }
    .hero {
      border-radius: calc(var(--radius) + 6px);
      padding: 22px;
      border: 1px solid #ced9df;
      background:
        linear-gradient(126deg, rgba(255, 253, 248, 0.96), rgba(237, 248, 244, 0.95)),
        linear-gradient(0deg, #fff, #fff);
      box-shadow: var(--shadow);
      animation: lift .5s ease-out both;
    }
    .hero-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }
    .logo {
      font-family: "Archivo Black", sans-serif;
      letter-spacing: 0.01em;
      font-size: 28px;
      margin: 0;
      text-transform: uppercase;
      text-wrap: balance;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid #b8cbc6;
      border-radius: 999px;
      padding: 7px 12px;
      color: #0f504a;
      background: #e9f8f4;
      font-weight: 700;
      font-size: 12px;
      white-space: nowrap;
    }
    .hero p {
      margin: 8px 0 0;
      color: var(--ink-soft);
      max-width: 68ch;
      line-height: 1.45;
    }
    .board {
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 16px;
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--card);
      box-shadow: var(--shadow);
      padding: 16px;
      animation: lift .55s ease-out both;
    }
    .panel h2 {
      margin: 0 0 10px;
      font-size: 20px;
      letter-spacing: -0.01em;
      text-wrap: balance;
    }
    .subtitle {
      margin: 0 0 14px;
      font-size: 13px;
      color: var(--ink-soft);
    }
    .field {
      display: grid;
      gap: 6px;
      margin-bottom: 11px;
    }
    .field label {
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.02em;
      text-transform: uppercase;
      color: #2f4352;
    }
    input, select {
      width: 100%;
      min-height: 44px;
      border: 1px solid #c5d1da;
      border-radius: 11px;
      padding: 11px 12px;
      font: inherit;
      color: var(--ink);
      background: #fff;
      transition: border-color .16s ease, box-shadow .16s ease;
    }
    input:focus-visible, select:focus-visible, button:focus-visible, a:focus-visible {
      outline: 2px solid transparent;
      border-color: #2d8d83;
      box-shadow: 0 0 0 4px rgba(20, 108, 99, 0.18);
    }
    .inline-3 {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 9px;
      margin-top: 4px;
    }
    button {
      appearance: none;
      min-height: 44px;
      border: 1px solid transparent;
      border-radius: 11px;
      padding: 10px 13px;
      font: inherit;
      font-weight: 800;
      letter-spacing: 0.01em;
      cursor: pointer;
      touch-action: manipulation;
      transition: transform .1s ease, filter .14s ease, box-shadow .14s ease;
    }
    button:hover { filter: brightness(1.04); }
    button:active { transform: translateY(1px); }
    button[disabled] {
      opacity: 0.55;
      cursor: not-allowed;
      filter: grayscale(0.2);
    }
    .btn-primary {
      color: #fff;
      background: linear-gradient(135deg, var(--brand), var(--brand-strong));
      box-shadow: 0 8px 18px rgba(20, 108, 99, 0.3);
    }
    .btn-secondary {
      color: #223542;
      background: #edf3f6;
      border-color: #ccd8e0;
    }
    .btn-accent {
      color: #fff;
      background: linear-gradient(135deg, #d56a32, #b55628);
      box-shadow: 0 8px 18px rgba(213, 106, 50, 0.28);
    }
    .btn-danger {
      color: #7d1f1f;
      background: #fff4f4;
      border-color: #efc6c6;
    }
    .status-pill {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 5px 11px;
      font-size: 12px;
      font-weight: 800;
      border: 1px solid #c7d6df;
      background: #f2f6fa;
      color: #223949;
      text-transform: uppercase;
      letter-spacing: 0.02em;
      min-height: 28px;
    }
    .status-idle { border-color: #c7d6df; color: #2f4352; background: #f2f6fa; }
    .status-queued { border-color: #e7cdb0; color: #865415; background: #fff8ec; }
    .status-running { border-color: #9ec8c3; color: #0d5951; background: #e6f7f4; }
    .status-succeeded { border-color: #9fd6bd; color: #0f5c3b; background: #e8faef; }
    .status-failed { border-color: #efb7b7; color: #841717; background: #ffeeee; }
    .mono {
      margin-top: 10px;
      border-radius: 12px;
      border: 1px solid #d8e1e8;
      background: #f8fbfd;
      color: #2d4251;
      font-family: "Consolas", "SFMono-Regular", monospace;
      font-size: 12px;
      padding: 10px;
      overflow-wrap: anywhere;
      min-height: 42px;
    }
    .timeline {
      margin: 10px 0 0;
      list-style: none;
      padding: 0;
      display: grid;
      gap: 7px;
      max-height: 248px;
      overflow: auto;
    }
    .timeline li {
      border-left: 3px solid #d3dde5;
      border-radius: 8px;
      padding: 6px 9px;
      background: #f7fafc;
      font-size: 12px;
      color: #334a59;
      line-height: 1.4;
      animation: fadeSlide .2s ease both;
    }
    .discovery-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 10px;
    }
    .metric {
      border: 1px solid #d7e0e5;
      border-radius: 12px;
      background: #fff;
      padding: 10px;
      min-height: 92px;
    }
    .metric span {
      display: block;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      color: #4f6472;
      font-weight: 800;
    }
    .metric strong {
      display: block;
      margin-top: 8px;
      font-size: 24px;
      line-height: 1.1;
      font-family: "Archivo Black", sans-serif;
    }
    .bars {
      display: grid;
      gap: 7px;
      margin-top: 10px;
    }
    .bar-row {
      display: grid;
      grid-template-columns: 88px 1fr 62px;
      gap: 8px;
      align-items: center;
      font-size: 12px;
      color: #314451;
    }
    .bar-track {
      height: 10px;
      border-radius: 999px;
      border: 1px solid #d8e3ea;
      background: #f1f6fa;
      overflow: hidden;
    }
    .bar-fill {
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #2f9c8f, #58b6a7);
    }
    .table-wrap {
      margin-top: 12px;
      border: 1px solid #d6e0e8;
      border-radius: 12px;
      overflow: auto;
      background: #fff;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }
    caption {
      text-align: left;
      padding: 10px 12px;
      font-size: 12px;
      font-weight: 700;
      color: #4d6372;
      border-bottom: 1px solid #d6e0e8;
      background: #f8fbfd;
    }
    th, td {
      text-align: left;
      padding: 9px 10px;
      border-bottom: 1px solid #edf2f6;
      font-size: 12px;
      vertical-align: middle;
    }
    th {
      color: #344c5d;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      background: #fbfdff;
    }
    .score {
      font-family: "Consolas", "SFMono-Regular", monospace;
      font-variant-numeric: tabular-nums;
      font-weight: 700;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      border: 1px solid #d6dee5;
      padding: 2px 8px;
      font-size: 11px;
      font-weight: 700;
      text-transform: lowercase;
    }
    .chip-high { color: #0d5c45; background: #e9f8f2; border-color: #b7dfcd; }
    .chip-medium { color: #8c5100; background: #fff5e9; border-color: #efd6b5; }
    .chip-low { color: #475b68; background: #eff4f8; border-color: #d1dde8; }
    .footer-note {
      font-size: 12px;
      color: #506373;
      margin-top: 12px;
      border-top: 1px dashed #d6e0e8;
      padding-top: 10px;
    }
    .legacy-note {
      margin-top: 12px;
      border: 1px dashed #d8c9b8;
      border-radius: 11px;
      background: #fef8f1;
      padding: 9px 10px;
      font-size: 12px;
      color: #684f30;
    }
    @keyframes lift {
      from { opacity: 0; transform: translateY(10px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes fadeSlide {
      from { opacity: 0; transform: translateX(6px); }
      to { opacity: 1; transform: translateX(0); }
    }
    @media (max-width: 1080px) {
      .board { grid-template-columns: 1fr; }
      .discovery-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 720px) {
      .inline-3 { grid-template-columns: 1fr; }
      .discovery-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .logo { font-size: 22px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
      }
    }
  </style>
</head>
<body>
  <a class="skip-link" href="#main-content">Skip to main content</a>
  <main class="shell" id="main-content">
    <section class="hero" aria-labelledby="page-title">
      <div class="hero-head">
        <h1 class="logo" id="page-title">BioVoid Phase 6 Web Portal</h1>
        <span class="badge" id="ops-status-badge">Ops: booting…</span>
      </div>
      <p>
        Unified interface for discovery and operations: submit jobs, monitor pipeline state,
        inspect atlas signals, and download validated artifacts from a single surface.
      </p>
    </section>

    <section class="board" aria-label="Job Operations">
      <article class="panel" aria-labelledby="submit-job-title">
        <h2 id="submit-job-title">Submit Job</h2>
        <p class="subtitle">Use deterministic <code>quick_probe</code> runs to validate orchestration and compare candidate IDs.</p>
        <form id="job-form">
          <div class="field">
            <label for="pdb-id">PDB ID</label>
            <input id="pdb-id" name="pdb-id" placeholder="e.g., 1CBS…" minlength="4" maxlength="12" required autocomplete="off" />
          </div>
          <div class="field">
            <label for="idempotency-key">Idempotency Key</label>
            <input id="idempotency-key" name="idempotency-key" placeholder="e.g., portal-abc123…" autocomplete="off" />
          </div>
          <div class="inline-3">
            <div class="field">
              <label for="priority">Priority</label>
              <select id="priority" name="priority">
                <option value="normal">normal</option>
                <option value="high">high</option>
              </select>
            </div>
            <div class="field">
              <label for="timeout-seconds">Timeout (sec)</label>
              <input id="timeout-seconds" name="timeout-seconds" type="number" min="1" max="600" value="30" inputmode="numeric" />
            </div>
            <div class="field">
              <label for="max-retries">Max Retries</label>
              <input id="max-retries" name="max-retries" type="number" min="0" max="5" value="2" inputmode="numeric" />
            </div>
          </div>
          <div class="actions">
            <button class="btn-primary" type="submit" id="submit-job-btn">Submit</button>
            <button class="btn-secondary" type="button" id="reset-form-btn">Reset</button>
          </div>
        </form>
        <div class="mono" id="submit-feedback" role="status" aria-live="polite">Ready.</div>
      </article>

      <article class="panel" aria-labelledby="job-monitor-title">
        <h2 id="job-monitor-title">Job Monitor</h2>
        <p class="subtitle">Polls every 1.5s while tracking is active. Stop tracking only affects your browser session.</p>
        <div class="actions">
          <span class="status-pill status-idle" id="job-status-pill">idle</span>
          <button class="btn-danger" type="button" id="stop-tracking-btn">Stop Tracking</button>
        </div>
        <div class="mono" id="job-meta" role="status" aria-live="polite">No active job.</div>
        <ul class="timeline" id="timeline" aria-live="polite"></ul>
        <div class="actions">
          <button class="btn-accent" type="button" id="download-result-btn" disabled>Download Result JSON</button>
        </div>
        <p class="subtitle" id="cancel-feedback">Tracking can be stopped from UI; server job continues safely.</p>
      </article>
    </section>

    <section class="panel" aria-labelledby="discovery-title">
      <div class="hero-head">
        <h2 id="discovery-title">Discovery Dashboard</h2>
        <div class="actions">
          <button class="btn-secondary" type="button" id="refresh-discovery-btn">Refresh Discovery</button>
        </div>
      </div>
      <p class="subtitle">Atlas metrics (from <code>data/atlas.db</code>) and high-signal pockets are now embedded directly in this portal.</p>

      <div class="discovery-grid" aria-label="Discovery KPIs">
        <div class="metric"><span>Total Proteins</span><strong id="kpi-total-proteins">-</strong></div>
        <div class="metric"><span>Total Pockets</span><strong id="kpi-total-pockets">-</strong></div>
        <div class="metric"><span>Druggable Pockets</span><strong id="kpi-druggable-pockets">-</strong></div>
        <div class="metric"><span>Elite Pockets</span><strong id="kpi-elite-pockets">-</strong></div>
        <div class="metric"><span>Avg Bio Score</span><strong id="kpi-avg-bio-score">-</strong></div>
        <div class="metric"><span>Avg Volume</span><strong id="kpi-avg-volume">-</strong></div>
      </div>

      <div class="bars" aria-label="Druggability distribution">
        <div class="bar-row">
          <strong>high</strong>
          <div class="bar-track"><div class="bar-fill" id="class-high-bar" style="width: 0%"></div></div>
          <span id="class-high-value">0</span>
        </div>
        <div class="bar-row">
          <strong>medium</strong>
          <div class="bar-track"><div class="bar-fill" id="class-medium-bar" style="width: 0%"></div></div>
          <span id="class-medium-value">0</span>
        </div>
        <div class="bar-row">
          <strong>low</strong>
          <div class="bar-track"><div class="bar-fill" id="class-low-bar" style="width: 0%"></div></div>
          <span id="class-low-value">0</span>
        </div>
      </div>

      <div class="inline-3" style="margin-top:12px;">
        <div class="field">
          <label for="filter-min-score">Min Score</label>
          <input id="filter-min-score" name="filter-min-score" type="number" min="0" max="1" step="0.01" value="0.2" inputmode="decimal" autocomplete="off" />
        </div>
        <div class="field">
          <label for="filter-class">Class</label>
          <select id="filter-class" name="filter-class" autocomplete="off">
            <option value="">all</option>
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
          </select>
        </div>
        <div class="field">
          <label for="filter-limit">Row Limit</label>
          <select id="filter-limit" name="filter-limit" autocomplete="off">
            <option value="8">8</option>
            <option value="12" selected>12</option>
            <option value="20">20</option>
            <option value="25">25</option>
          </select>
        </div>
      </div>

      <div class="table-wrap">
        <table id="pockets-table">
          <caption>Top pocket candidates (druggable-first).</caption>
          <thead>
            <tr>
              <th scope="col">PDB</th>
              <th scope="col">Pocket</th>
              <th scope="col">Score</th>
              <th scope="col">Volume</th>
              <th scope="col">Class</th>
              <th scope="col">Rank</th>
              <th scope="col">Profile</th>
            </tr>
          </thead>
          <tbody id="pockets-tbody"></tbody>
        </table>
      </div>
      <div class="mono" id="discovery-feedback" role="status" aria-live="polite">Loading discovery snapshot…</div>
      <p class="legacy-note">Legacy Streamlit dashboard is deprecated. Daily use should stay on this unified portal.</p>
      <p class="footer-note">Single interface mode: jobs + ops + discovery in one page.</p>
    </section>
  </main>

  <script>
    const pollIntervalMs = 1500;
    const opsPollMs = 4000;
    let activeJobId = null;
    let pollingEnabled = false;
    let pollHandle = null;
    let opsHandle = null;

    const statusPill = document.getElementById("job-status-pill");
    const submitFeedback = document.getElementById("submit-feedback");
    const jobMeta = document.getElementById("job-meta");
    const timeline = document.getElementById("timeline");
    const downloadBtn = document.getElementById("download-result-btn");
    const cancelFeedback = document.getElementById("cancel-feedback");
    const opsBadge = document.getElementById("ops-status-badge");
    const discoveryFeedback = document.getElementById("discovery-feedback");
    const pocketsTbody = document.getElementById("pockets-tbody");
    const submitBtn = document.getElementById("submit-job-btn");
    const formEl = document.getElementById("job-form");
    let hasUnsavedChanges = false;

    function nowStamp() {
      return new Date().toISOString();
    }

    function pushTimeline(message) {
      const li = document.createElement("li");
      li.textContent = "[" + nowStamp() + "] " + message;
      timeline.prepend(li);
    }

    function setStatus(status) {
      const normalized = String(status || "idle").toLowerCase();
      statusPill.textContent = normalized;
      statusPill.className = "status-pill status-" + normalized;
    }

    function setSubmitting(isSubmitting) {
      submitBtn.disabled = isSubmitting;
      submitBtn.textContent = isSubmitting ? "Submitting…" : "Submit";
    }

    function makeIdempotencyKey() {
      const randomPart = Math.random().toString(36).slice(2);
      return "portal-" + Date.now().toString(36) + "-" + randomPart;
    }

    function stopPolling(feedback) {
      pollingEnabled = false;
      if (pollHandle) {
        clearTimeout(pollHandle);
        pollHandle = null;
      }
      cancelFeedback.textContent = feedback || "Tracking stopped.";
    }

    function nf(value, digits) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
      return Number(value).toLocaleString(undefined, {
        minimumFractionDigits: digits || 0,
        maximumFractionDigits: digits || 0
      });
    }

    function setText(id, value) {
      const el = document.getElementById(id);
      if (el) el.textContent = value;
    }

    function updateClassBars(dist) {
      const high = Number(dist.high || 0);
      const medium = Number(dist.medium || 0);
      const low = Number(dist.low || 0);
      const total = high + medium + low;
      const toPct = (v) => total > 0 ? Math.max(0, Math.min(100, (v / total) * 100)) : 0;
      const hiPct = toPct(high);
      const medPct = toPct(medium);
      const lowPct = toPct(low);
      document.getElementById("class-high-bar").style.width = hiPct.toFixed(1) + "%";
      document.getElementById("class-medium-bar").style.width = medPct.toFixed(1) + "%";
      document.getElementById("class-low-bar").style.width = lowPct.toFixed(1) + "%";
      setText("class-high-value", nf(high, 0));
      setText("class-medium-value", nf(medium, 0));
      setText("class-low-value", nf(low, 0));
    }

    function renderPocketRows(items) {
      pocketsTbody.innerHTML = "";
      if (!items || !items.length) {
        const tr = document.createElement("tr");
        const td = document.createElement("td");
        td.colSpan = 7;
        td.textContent = "No pockets found for current filters.";
        tr.appendChild(td);
        pocketsTbody.appendChild(tr);
        return;
      }
      for (const item of items) {
        const tr = document.createElement("tr");
        const clsRaw = String(item.druggability_class || "low").toLowerCase();
        const cls = ["high", "medium", "low"].includes(clsRaw) ? clsRaw : "low";

        const pdbCell = document.createElement("td");
        const pdbStrong = document.createElement("strong");
        pdbStrong.textContent = item.pdb_id || "-";
        pdbCell.appendChild(pdbStrong);

        const pocketCell = document.createElement("td");
        pocketCell.textContent = nf(item.pocket_id, 0);

        const scoreCell = document.createElement("td");
        scoreCell.className = "score";
        scoreCell.textContent = nf(item.bio_score, 4);

        const volumeCell = document.createElement("td");
        volumeCell.className = "score";
        volumeCell.textContent = nf(item.volume, 2);

        const classCell = document.createElement("td");
        const chip = document.createElement("span");
        chip.className = "chip chip-" + cls;
        chip.textContent = cls;
        classCell.appendChild(chip);

        const rankCell = document.createElement("td");
        rankCell.textContent = nf(item.rank, 0);

        const profileCell = document.createElement("td");
        profileCell.textContent = item.profile_used || "-";

        tr.appendChild(pdbCell);
        tr.appendChild(pocketCell);
        tr.appendChild(scoreCell);
        tr.appendChild(volumeCell);
        tr.appendChild(classCell);
        tr.appendChild(rankCell);
        tr.appendChild(profileCell);
        pocketsTbody.appendChild(tr);
      }
    }

    async function pollStatus() {
      if (!pollingEnabled || !activeJobId) return;
      try {
        const res = await fetch("/jobs/" + activeJobId);
        const data = await res.json();
        if (!res.ok) {
          pushTimeline("Polling failed: " + (data.error?.message || "unknown"));
          stopPolling("Tracking stopped due to API error.");
          return;
        }
        setStatus(data.status);
        jobMeta.textContent = "job_id=" + data.job_id + " attempts=" + data.attempts;
        if (data.status === "succeeded") {
          pushTimeline("Job succeeded.");
          downloadBtn.disabled = false;
          stopPolling("Tracking finished. You can download result JSON.");
          return;
        }
        if (data.status === "failed") {
          const err = data.error ? (data.error.code + ": " + data.error.message) : "unknown";
          pushTimeline("Job failed: " + err);
          downloadBtn.disabled = true;
          stopPolling("Tracking finished with failure.");
          return;
        }
      } catch (err) {
        pushTimeline("Network error: " + err);
      }
      pollHandle = setTimeout(pollStatus, pollIntervalMs);
    }

    async function refreshOpsBadge() {
      try {
        const res = await fetch("/ops/metrics");
        const data = await res.json();
        if (!res.ok) {
          opsBadge.textContent = "Ops: degraded";
        } else {
          const status = data.worker_alive ? "healthy" : "degraded";
          opsBadge.textContent =
            "Ops: " + status +
            " | queue " + nf(data.queue_depth, 0) +
            " | p95 " + nf(data.p95_job_latency_seconds, 3) + "s";
        }
      } catch (_) {
        opsBadge.textContent = "Ops: offline";
      }
      if (opsHandle) clearTimeout(opsHandle);
      opsHandle = setTimeout(refreshOpsBadge, opsPollMs);
    }

    function readFiltersFromUrl() {
      const params = new URLSearchParams(window.location.search);
      const minScore = params.get("min_score");
      const cls = params.get("class");
      const limit = params.get("limit");
      if (minScore !== null) document.getElementById("filter-min-score").value = minScore;
      if (cls !== null) document.getElementById("filter-class").value = cls;
      if (limit !== null) document.getElementById("filter-limit").value = limit;
    }

    function writeFiltersToUrl() {
      const params = new URLSearchParams(window.location.search);
      params.set("min_score", document.getElementById("filter-min-score").value);
      params.set("class", document.getElementById("filter-class").value);
      params.set("limit", document.getElementById("filter-limit").value);
      const next = window.location.pathname + "?" + params.toString();
      window.history.replaceState({}, "", next);
    }

    async function loadOverview() {
      try {
        const res = await fetch("/atlas/overview");
        const data = await res.json();
        if (!res.ok || !data.available) {
          discoveryFeedback.textContent = data.message || "Atlas overview unavailable.";
          return;
        }
        setText("kpi-total-proteins", nf(data.summary.total_proteins, 0));
        setText("kpi-total-pockets", nf(data.summary.total_pockets, 0));
        setText("kpi-druggable-pockets", nf(data.summary.druggable_pockets, 0));
        setText("kpi-elite-pockets", nf(data.summary.elite_pockets, 0));
        setText("kpi-avg-bio-score", nf(data.summary.avg_bio_score, 4));
        setText("kpi-avg-volume", nf(data.summary.avg_volume, 2));
        updateClassBars(data.class_distribution || {});
      } catch (err) {
        discoveryFeedback.textContent = "Overview load failed: " + err;
      }
    }

    async function loadPockets() {
      writeFiltersToUrl();
      const minScore = Number(document.getElementById("filter-min-score").value || 0);
      const cls = document.getElementById("filter-class").value;
      const limit = Number(document.getElementById("filter-limit").value || 12);
      const params = new URLSearchParams();
      params.set("min_score", String(minScore));
      params.set("limit", String(limit));
      params.set("druggable_only", "true");
      if (cls) params.set("druggability_class", cls);

      discoveryFeedback.textContent = "Loading pockets…";
      try {
        const res = await fetch("/atlas/pockets?" + params.toString());
        const data = await res.json();
        if (!res.ok || !data.available) {
          discoveryFeedback.textContent = data.message || "Pocket list unavailable.";
          renderPocketRows([]);
          return;
        }
        renderPocketRows(data.items || []);
        discoveryFeedback.textContent = "Loaded " + nf(data.count || 0, 0) + " row(s).";
      } catch (err) {
        discoveryFeedback.textContent = "Pocket load failed: " + err;
        renderPocketRows([]);
      }
    }

    formEl.addEventListener("submit", async (event) => {
      event.preventDefault();
      downloadBtn.disabled = true;
      setSubmitting(true);

      const pdbId = document.getElementById("pdb-id").value.trim().toUpperCase();
      if (!/^[A-Z0-9]{4,12}$/.test(pdbId)) {
        submitFeedback.textContent = "Invalid PDB ID. Use 4-12 alphanumeric chars, e.g., 1CBS.";
        document.getElementById("pdb-id").focus();
        setStatus("failed");
        setSubmitting(false);
        return;
      }

      const idemInput = document.getElementById("idempotency-key");
      const idempotencyKey = (idemInput.value || makeIdempotencyKey()).trim();
      idemInput.value = idempotencyKey;

      const payload = {
        job_type: "quick_probe",
        input: { pdb_id: pdbId },
        options: {
          priority: document.getElementById("priority").value,
          timeout_seconds: Number(document.getElementById("timeout-seconds").value),
          max_retries: Number(document.getElementById("max-retries").value)
        }
      };

      try {
        const res = await fetch("/jobs", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": idempotencyKey
          },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) {
          submitFeedback.textContent = JSON.stringify(data, null, 2);
          setStatus("failed");
          pushTimeline("Submission failed.");
          setSubmitting(false);
          return;
        }
        activeJobId = data.job_id;
        setStatus(data.status);
        submitFeedback.textContent = "Accepted. job_id=" + activeJobId + " reused=" + data.idempotent_reused;
        jobMeta.textContent = "job_id=" + activeJobId + " created_at=" + data.created_at_utc;
        pushTimeline("Job submitted.");
        cancelFeedback.textContent = "Polling active.";
        pollingEnabled = true;
        hasUnsavedChanges = false;
        pollStatus();
        setSubmitting(false);
      } catch (err) {
        submitFeedback.textContent = "Submit failed: " + err;
        setStatus("failed");
        setSubmitting(false);
      }
    });

    document.getElementById("stop-tracking-btn").addEventListener("click", () => {
      stopPolling("Tracking stopped by user. Server-side job continues.");
      pushTimeline("User stopped tracking.");
    });

    document.getElementById("download-result-btn").addEventListener("click", () => {
      if (!activeJobId) return;
      window.location.href = "/jobs/" + activeJobId + "/result";
    });

    document.getElementById("reset-form-btn").addEventListener("click", () => {
      formEl.reset();
      document.getElementById("idempotency-key").value = "";
      submitFeedback.textContent = "Form reset.";
      setStatus("idle");
      hasUnsavedChanges = false;
      setSubmitting(false);
    });

    document.getElementById("refresh-discovery-btn").addEventListener("click", async () => {
      await loadOverview();
      await loadPockets();
    });

    ["filter-min-score", "filter-class", "filter-limit"].forEach((id) => {
      document.getElementById(id).addEventListener("change", () => {
        loadPockets();
      });
    });

    formEl.querySelectorAll("input, select").forEach((el) => {
      el.addEventListener("input", () => {
        hasUnsavedChanges = true;
      });
      el.addEventListener("change", () => {
        hasUnsavedChanges = true;
      });
    });

    window.addEventListener("beforeunload", (event) => {
      if (!hasUnsavedChanges) return;
      event.preventDefault();
      event.returnValue = "";
    });

    readFiltersFromUrl();
    setStatus("idle");
    refreshOpsBadge();
    loadOverview().then(loadPockets);
  </script>
</body>
</html>
"""
