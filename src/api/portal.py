"""Portal page renderer for Phase 6 Step 3."""

from __future__ import annotations


def render_portal_html() -> str:
    """Return portal HTML."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>BioVoid Phase 6 Portal</title>
  <style>
    :root {
      --bg: #f3f5f7;
      --panel: #ffffff;
      --ink: #0f1720;
      --muted: #5f6c78;
      --line: #d8dee4;
      --brand: #0f766e;
      --brand-2: #0b4f4a;
      --accent: #e57a44;
      --ok: #0f9d58;
      --warn: #b45309;
      --fail: #b91c1c;
      --shadow: 0 10px 30px rgba(18, 32, 48, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(1100px 550px at 85% -10%, #d9f2ef 0%, var(--bg) 50%);
      color: var(--ink);
      font-family: "Space Grotesk", "Segoe UI", system-ui, sans-serif;
    }
    .shell {
      max-width: 1100px;
      margin: 0 auto;
      padding: 28px 16px 40px;
      display: grid;
      gap: 18px;
    }
    .hero {
      background: linear-gradient(135deg, #effaf8, #fef6ef);
      border: 1px solid #d7ebe8;
      border-radius: 18px;
      padding: 22px;
      box-shadow: var(--shadow);
    }
    .hero h1 {
      margin: 0;
      font-size: 26px;
      letter-spacing: -0.02em;
    }
    .hero p {
      margin: 8px 0 0;
      color: var(--muted);
    }
    .grid {
      display: grid;
      grid-template-columns: 1.15fr 0.85fr;
      gap: 18px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 16px;
      box-shadow: var(--shadow);
    }
    .card h2 {
      margin: 0 0 10px;
      font-size: 18px;
    }
    .field {
      display: grid;
      gap: 6px;
      margin-bottom: 12px;
    }
    .field label {
      font-size: 13px;
      font-weight: 600;
      color: #2b3a47;
    }
    .field input, .field select {
      border: 1px solid #ccd5dd;
      border-radius: 10px;
      padding: 11px 12px;
      font: inherit;
      width: 100%;
      background: #fff;
    }
    .inline {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 4px;
    }
    button {
      appearance: none;
      border: 1px solid transparent;
      border-radius: 10px;
      padding: 10px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform .08s ease, opacity .18s ease;
    }
    button:active { transform: translateY(1px); }
    .btn-primary { background: var(--brand); color: #fff; }
    .btn-secondary { background: #edf2f5; color: #13212e; border-color: #ced8e0; }
    .btn-accent { background: var(--accent); color: #fff; }
    .btn-danger { background: #fff; border-color: #f0caca; color: var(--fail); }
    .status-pill {
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid #c9d6df;
      color: #1f3342;
      background: #f5f8fb;
    }
    .status-queued { border-color: #d6c4a2; color: #7a4b08; background: #fff8ea; }
    .status-running { border-color: #9dc9c4; color: #08504a; background: #e7f8f6; }
    .status-succeeded { border-color: #a6d8b8; color: #0e5c36; background: #e9fbf0; }
    .status-failed { border-color: #efb5b5; color: #7a1111; background: #ffecec; }
    .mono {
      font-family: "JetBrains Mono", Consolas, monospace;
      font-size: 12px;
      color: #3b4a57;
      background: #f7fafc;
      border: 1px solid #dfe8ef;
      border-radius: 10px;
      padding: 10px;
      overflow-wrap: anywhere;
      margin-top: 10px;
    }
    .timeline {
      list-style: none;
      margin: 8px 0 0;
      padding: 0;
      display: grid;
      gap: 8px;
      max-height: 280px;
      overflow: auto;
    }
    .timeline li {
      border-left: 3px solid #c6d5df;
      padding: 6px 10px;
      background: #f8fbfd;
      border-radius: 8px;
      font-size: 13px;
      color: #334454;
    }
    .muted { color: var(--muted); font-size: 13px; }
    .result-block {
      border-top: 1px dashed #cdd7e0;
      margin-top: 12px;
      padding-top: 12px;
    }
    @media (max-width: 900px) {
      .grid { grid-template-columns: 1fr; }
      .inline { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <h1>BioVoid Phase 6 Web Portal</h1>
      <p>Submit jobs, monitor progress, and download result artifacts from a single interface.</p>
    </section>

    <section class="grid">
      <article class="card">
        <h2>Submit Job</h2>
        <form id="job-form">
          <div class="field">
            <label for="pdb-id">PDB ID</label>
            <input id="pdb-id" name="pdb-id" placeholder="e.g. 1CBS" minlength="4" maxlength="12" required />
          </div>
          <div class="field">
            <label for="idempotency-key">Idempotency Key</label>
            <input id="idempotency-key" name="idempotency-key" placeholder="auto generated if empty" />
          </div>
          <div class="inline">
            <div class="field">
              <label for="priority">Priority</label>
              <select id="priority">
                <option value="normal">normal</option>
                <option value="high">high</option>
              </select>
            </div>
            <div class="field">
              <label for="timeout-seconds">Timeout (sec)</label>
              <input id="timeout-seconds" type="number" min="1" max="600" value="30" />
            </div>
            <div class="field">
              <label for="max-retries">Max Retries</label>
              <input id="max-retries" type="number" min="0" max="5" value="2" />
            </div>
          </div>
          <div class="actions">
            <button class="btn-primary" type="submit">Submit</button>
            <button class="btn-secondary" type="button" id="reset-form-btn">Reset</button>
          </div>
        </form>
        <div class="mono" id="submit-feedback">Ready.</div>
      </article>

      <article class="card">
        <h2>Job Monitor</h2>
        <p class="muted">Live polling every 1.5s while tracking is enabled.</p>
        <div class="actions">
          <span class="status-pill" id="job-status-pill">idle</span>
          <button class="btn-danger" type="button" id="stop-tracking-btn">Stop Tracking</button>
        </div>
        <div class="mono" id="job-meta">No active job.</div>
        <ul class="timeline" id="timeline"></ul>

        <div class="result-block">
          <div class="actions">
            <button class="btn-accent" type="button" id="download-result-btn" disabled>Download Result JSON</button>
          </div>
          <p class="muted" id="cancel-feedback">Tracking can be stopped from UI; server job continues safely.</p>
        </div>
      </article>
    </section>
  </main>

  <script>
    const pollIntervalMs = 1500;
    let activeJobId = null;
    let pollingEnabled = false;
    let pollHandle = null;

    const statusPill = document.getElementById("job-status-pill");
    const submitFeedback = document.getElementById("submit-feedback");
    const jobMeta = document.getElementById("job-meta");
    const timeline = document.getElementById("timeline");
    const downloadBtn = document.getElementById("download-result-btn");
    const cancelFeedback = document.getElementById("cancel-feedback");

    function nowStamp() {
      return new Date().toISOString();
    }

    function pushTimeline(message) {
      const li = document.createElement("li");
      li.textContent = "[" + nowStamp() + "] " + message;
      timeline.prepend(li);
    }

    function setStatus(status) {
      statusPill.textContent = status;
      statusPill.className = "status-pill status-" + status;
    }

    function makeIdempotencyKey() {
      const seed = Math.random().toString(36).slice(2);
      return "portal-" + Date.now().toString(36) + "-" + seed;
    }

    function stopPolling(feedback) {
      pollingEnabled = false;
      if (pollHandle) {
        clearTimeout(pollHandle);
        pollHandle = null;
      }
      cancelFeedback.textContent = feedback || "Tracking stopped.";
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

    document.getElementById("job-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      downloadBtn.disabled = true;

      const pdbId = document.getElementById("pdb-id").value.trim().toUpperCase();
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
          return;
        }

        activeJobId = data.job_id;
        setStatus(data.status);
        submitFeedback.textContent = "Accepted. job_id=" + activeJobId + " reused=" + data.idempotent_reused;
        jobMeta.textContent = "job_id=" + activeJobId + " created_at=" + data.created_at_utc;
        pushTimeline("Job submitted.");
        cancelFeedback.textContent = "Polling active.";
        pollingEnabled = true;
        pollStatus();
      } catch (err) {
        submitFeedback.textContent = "Submit failed: " + err;
        setStatus("failed");
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
      document.getElementById("job-form").reset();
      document.getElementById("idempotency-key").value = "";
      submitFeedback.textContent = "Form reset.";
    });

    setStatus("queued");
  </script>
</body>
</html>
"""
