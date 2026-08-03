import { useEffect, useRef, useState } from 'react';
import Plot from 'react-plotly.js';
import { api } from '../services/api';
import ErrorNotice from '../components/ErrorNotice';
import ProvenancePanel from '../components/ProvenancePanel';
import ResearchStatus from '../components/ResearchStatus';
import type { AnalysisResult, Pocket } from '../types/api';
import { errorCorrelationId, errorMessage } from '../types/api';

const cc: Record<string, string> = { high: '#00ff88', medium: '#ffaa22', low: '#ff4455' };
const PLOT_THEME = {
  paper_bgcolor: '#0a0a0f',
  plot_bgcolor: '#0a0a0f',
  font: { color: '#6a6a8a', size: 11, family: 'monospace' },
  xaxis: { color: '#6a6a8a', gridcolor: '#1a1a24' },
  yaxis: { color: '#6a6a8a', gridcolor: '#1a1a24' },
  title: { font: { size: 12, color: '#00ff88' } },
};

export default function Analyze() {
  const [pdbId, setPdbId] = useState('');
  const [profile, setProfile] = useState('default');
  const [status, setStatus] = useState('');
  const [log, setLog] = useState('');
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorCorrelationIdValue, setErrorCorrelationIdValue] = useState<string | null>(null);
  const pollController = useRef<AbortController | null>(null);

  useEffect(() => () => pollController.current?.abort(), []);

  async function submit() {
    const normalizedPdbId = pdbId.trim().toUpperCase();
    if (!/^[A-Z0-9]{4}$/.test(normalizedPdbId)) {
      setError('Enter a valid 4-character RCSB PDB identifier');
      return;
    }
    setError(null);
    setErrorCorrelationIdValue(null);
    setStatus('Submitting...');
    setLog('[START] Analyzing ' + normalizedPdbId + '...\n');
    setResult(null);
    setJobId(null);
    setLoading(true);
    pollController.current?.abort();
    const controller = new AbortController();
    pollController.current = controller;
    try {
      const idempotencyKey = `frontend-${crypto.randomUUID()}`;
      const job = await api.submitJob(
        normalizedPdbId,
        profile,
        idempotencyKey,
        controller.signal,
      );
      setJobId(job.job_id);
      setStatus('Job ' + job.job_id + ' submitted');
      await poll(job.job_id, controller.signal);
    } catch (error: unknown) {
      if (controller.signal.aborted) return;
      setLoading(false);
      setError(errorMessage(error, 'Failed to submit job'));
      setErrorCorrelationIdValue(errorCorrelationId(error));
      setStatus('');
    }
  }

  async function cancel() {
    const activeJobId = jobId;
    pollController.current?.abort();
    setLoading(false);
    setStatus('Cancelling...');
    if (!activeJobId) {
      setStatus('Cancelled');
      return;
    }
    try {
      await api.cancelJob(activeJobId);
      setStatus('Cancelled');
      setLog((prev) => prev + '[CANCELLED] Job cancellation requested\n');
    } catch (cancelError: unknown) {
      setError(errorMessage(cancelError, 'Could not cancel the job'));
      setErrorCorrelationIdValue(errorCorrelationId(cancelError));
      setStatus('');
    }
  }

  async function poll(activeJobId: string, signal: AbortSignal) {
    let transientErrors = 0;
    for (let attempt = 0; attempt < 300 && !signal.aborted; attempt += 1) {
      try {
        const r = await api.jobStatus(activeJobId, signal);
        transientErrors = 0;
        if (r.status === 'succeeded') {
          setLoading(false);
          setStatus('Complete');
          setLog(
            (prev) =>
              prev + '[DONE] ' + (r.result?.total_cavities ?? 0) + ' pockets found\n'
          );
          setResult(r.result ?? null);
          return;
        }
        if (r.status === 'failed' || r.status === 'cancelled') {
          setLoading(false);
          const detail =
            typeof r.error === 'string' ? r.error : r.error?.message ?? r.status;
          setError('Stopped: ' + detail);
          setErrorCorrelationIdValue(null);
          setStatus('');
          return;
        }
        setStatus(r.status === 'running' ? 'Running analysis' : 'Queued');
      } catch (pollError: unknown) {
        if (signal.aborted) return;
        transientErrors += 1;
        if (transientErrors >= 5) {
          setLoading(false);
          setError(errorMessage(pollError, 'Job status could not be reached'));
          setErrorCorrelationIdValue(errorCorrelationId(pollError));
          setStatus('');
          return;
        }
      }
      await new Promise<void>((resolve) => {
        const timer = window.setTimeout(resolve, 2000);
        signal.addEventListener(
          'abort',
          () => {
            window.clearTimeout(timer);
            resolve();
          },
          { once: true }
        );
      });
    }
    if (!signal.aborted) {
      setLoading(false);
      setError('Polling stopped after 10 minutes');
      setErrorCorrelationIdValue(null);
      setStatus('');
    }
  }

  const cavities = result?.cavities ?? [];

  return (
    <div>
      <h2 id="analyze-heading" style={{ fontSize: 20, fontWeight: 700, marginBottom: 8, color: 'var(--accent)' }}>
        ▶ New Analysis
      </h2>
      <p style={{ color: 'var(--text2)', fontSize: 12, marginBottom: 16, maxWidth: 760 }}>
        Static full analysis is the canonical local path. Motion-aware output remains experimental and is not enabled by this form.
      </p>
      <section
        aria-label="Preparation contract"
        style={{
          maxWidth: 760,
          marginBottom: 16,
          padding: 12,
          border: '1px solid var(--border)',
          background: 'var(--surface2)',
        }}
      >
        <div style={{ color: 'var(--accent)', fontWeight: 700, fontSize: 12, marginBottom: 8 }}>
          Preparation contract for this run
        </div>
        <dl className="provenance-grid">
          <div><dt>Source</dt><dd>RCSB PDB</dd></div>
          <div><dt>Representation</dt><dd>Biological assembly 1</dd></div>
          <div><dt>Chains</dt><dd>Automatic; recorded after preparation</dd></div>
          <div><dt>Input policy</dt><dd>Full-atom static detector input</dd></div>
        </dl>
      </section>
      <form
        aria-labelledby="analyze-heading"
        onSubmit={(event) => {
          event.preventDefault();
          if (!loading) void submit();
        }}
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: 16,
          maxWidth: 500,
          marginBottom: 16,
        }}
      >
        <div style={{ marginBottom: 10 }}>
          <label htmlFor="pdb-id"
            style={{
              display: 'block',
              fontSize: 11,
              color: 'var(--text2)',
              marginBottom: 3,
            }}
          >
            PDB ID
          </label>
          <input
            id="pdb-id"
            name="pdb-id"
            aria-describedby="pdb-help"
            value={pdbId}
            onChange={(e) => setPdbId(e.target.value)}
            placeholder="e.g. 1CBS"
            disabled={loading}
            style={{
              width: '100%',
              background: 'var(--surface2)',
              border: '1px solid var(--border)',
              color: 'var(--text)',
              padding: '8px 12px',
              borderRadius: 6,
              fontSize: 13,
              fontFamily: 'monospace',
            }}
          />
          <div id="pdb-help" style={{ marginTop: 4, color: 'var(--text2)', fontSize: 10 }}>
            RCSB PDB identifier, exactly 4 alphanumeric characters.
          </div>
        </div>
        <div style={{ marginBottom: 10 }}>
            <label htmlFor="profile"
              style={{
                display: 'block',
                fontSize: 11,
                color: 'var(--text2)',
                marginBottom: 3,
              }}
            >
              Profile
            </label>
            <select
              id="profile"
              name="profile"
              aria-label="Analysis profile"
              value={profile}
              onChange={(e) => setProfile(e.target.value)}
              disabled={loading}
              style={{
                width: '100%',
                background: 'var(--surface2)',
                border: '1px solid var(--border)',
                color: 'var(--text)',
                padding: '8px 12px',
                borderRadius: 6,
                fontSize: 13,
                fontFamily: 'monospace',
              }}
            >
              <option>default</option>
              <option>enzyme</option>
              <option>ppi</option>
              <option>gpcr</option>
            </select>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button
          type="submit"
          disabled={loading}
          style={{
            padding: '8px 20px',
            background: loading ? 'var(--surface2)' : 'var(--accent)',
            color: loading ? 'var(--text2)' : '#000',
            border: 'none',
            borderRadius: 6,
            fontSize: 13,
            fontWeight: 700,
            cursor: loading ? 'not-allowed' : 'pointer',
            fontFamily: 'monospace',
          }}
        >
          {loading ? 'Running...' : 'Run Analysis'}
        </button>
        {loading && (
          <button
            type="button"
            onClick={() => void cancel()}
            style={{
              padding: '8px 16px',
              background: 'transparent',
              color: 'var(--warn)',
              border: '1px solid var(--warn)',
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 700,
              cursor: 'pointer',
              fontFamily: 'monospace',
            }}
          >
            Cancel
          </button>
        )}
        </div>
        {error && (
          <div style={{ marginTop: 8 }}>
            <ErrorNotice message={error} correlationId={errorCorrelationIdValue} compact />
          </div>
        )}
        {status && !error && (
          <div
            style={{
              marginTop: 8,
              fontSize: 12,
              color:
                status.includes('Error') || status.includes('Failed')
                  ? 'var(--danger)'
                  : 'var(--accent)',
            }}
          >
            {status}
          </div>
        )}
        {log && (
          <pre
            style={{
              marginTop: 8,
              background: 'var(--bg)',
              border: '1px solid var(--border)',
              borderRadius: 6,
              padding: 10,
              fontSize: 11,
              color: 'var(--accent)',
              maxHeight: 120,
              overflowY: 'auto',
            }}
          >
            {log}
          </pre>
        )}
      </form>

      {result && (
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 16,
            animation: 'fadeUp 0.3s ease both',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 12,
              flexWrap: 'wrap',
              gap: 8,
            }}
          >
            <span style={{ fontWeight: 700, fontSize: 16 }}>
              {result.pdb_id} Results
            </span>
            {jobId && (
              <a
                href={`/jobs/${jobId}/result`}
                download
                style={{
                  padding: '6px 14px',
                  background: 'var(--accent)',
                  color: '#000',
                  border: 'none',
                  borderRadius: 6,
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                  fontFamily: 'monospace',
                  textDecoration: 'none',
                }}
              >
                Download Report
              </a>
            )}
          </div>
          <ResearchStatus
            validationStatus={result.validation_status}
            canonicalEligible={result.canonical_eligible}
            motionStatus={result.motion?.status}
            motion={result.motion ?? result.motion_aware}
            compact
          />
          <div style={{ margin: '12px 0' }}>
            <ProvenancePanel
              runId={result.run_id}
              preparedSha256={result.preparation?.prepared_sha256}
              analysisContract={result.analysis_contract}
              preparation={result.preparation}
              provenance={result.provenance}
            />
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4,1fr)',
              gap: 10,
              marginBottom: 12,
            }}
          >
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--accent)' }}>
                {result.total_cavities ?? 0}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text2)' }}>CAVITIES</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--accent)' }}>
                {result.heuristic_shortlist_cavities ?? 0}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text2)' }}>HIGH-TIER</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--accent)' }}>
                {cavities.filter((p) => p.heuristic_quality_tier === 'medium').length}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text2)' }}>MEDIUM-TIER</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--accent)' }}>
                {(result.runtime_seconds ?? 0).toFixed(1)}s
              </div>
              <div style={{ fontSize: 10, color: 'var(--text2)' }}>RUNTIME</div>
            </div>
          </div>
          {cavities.length > 0 && (
            <>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: 12,
                marginBottom: 16,
              }}
            >
              <div
                style={{
                  background: 'var(--surface2)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: 12,
                }}
              >
                <Plot
                  data={[
                    {
                      x: cavities.map((c: Pocket) => `P${c.id ?? c.pocket_id ?? c.rank}`),
                      y: cavities.map((c: Pocket) => c.volume ?? 0),
                      type: 'bar',
                      marker: {
                        color: cavities.map((c: Pocket) => cc[c.heuristic_quality_tier ?? 'low'] ?? '#6a6a8a'),
                        opacity: 0.9,
                      },
                    },
                  ]}
                  layout={{
                    ...PLOT_THEME,
                    xaxis: { ...PLOT_THEME.xaxis, title: 'Pocket' },
                    yaxis: { ...PLOT_THEME.yaxis, title: 'Volume (Å³)' },
                    title: { ...PLOT_THEME.title, text: 'Pocket Volume' },
                    height: 240,
                  }}
                  config={{ responsive: true, displayModeBar: false }}
                  style={{ width: '100%' }}
                />
              </div>
              <div
                style={{
                  background: 'var(--surface2)',
                  border: '1px solid var(--border)',
                  borderRadius: 8,
                  padding: 12,
                }}
              >
                <Plot
                  data={[
                    {
                      type: 'bar',
                      name: 'Volume',
                      x: cavities.slice(0, 3).map((c, i) => `P${c.id ?? c.pocket_id ?? i + 1}`),
                      y: cavities.slice(0, 3).map((c) => (c.score_components?.volume_score ?? 0)),
                      marker: { color: '#00ff88', opacity: 0.9 },
                    },
                    {
                      type: 'bar',
                      name: 'Hydrophobicity',
                      x: cavities.slice(0, 3).map((c, i) => `P${c.id ?? c.pocket_id ?? i + 1}`),
                      y: cavities.slice(0, 3).map((c) => (c.score_components?.hydrophobicity_score ?? 0)),
                      marker: { color: '#ffaa22', opacity: 0.9 },
                    },
                    {
                      type: 'bar',
                      name: 'Enclosure',
                      x: cavities.slice(0, 3).map((c, i) => `P${c.id ?? c.pocket_id ?? i + 1}`),
                      y: cavities.slice(0, 3).map((c) => (c.score_components?.enclosure_score ?? 0)),
                      marker: { color: '#22d3ee', opacity: 0.9 },
                    },
                    {
                      type: 'bar',
                      name: 'Depth',
                      x: cavities.slice(0, 3).map((c, i) => `P${c.id ?? c.pocket_id ?? i + 1}`),
                      y: cavities.slice(0, 3).map((c) => (c.score_components?.depth_score ?? 0)),
                      marker: { color: '#a78bfa', opacity: 0.9 },
                    },
                  ]}
                  layout={{
                    ...PLOT_THEME,
                    barmode: 'stack',
                    xaxis: { ...PLOT_THEME.xaxis, title: 'Pocket' },
                    yaxis: { ...PLOT_THEME.yaxis, title: 'Score' },
                    title: { ...PLOT_THEME.title, text: 'Score Components (Top 3)' },
                    showlegend: true,
                    legend: { font: { size: 10, color: '#6a6a8a', family: 'monospace' } },
                    height: 240,
                  }}
                  config={{ responsive: true, displayModeBar: false }}
                  style={{ width: '100%' }}
                />
              </div>
            </div>
            <div
              style={{
                background: 'var(--surface2)',
                border: '1px solid var(--border)',
                borderRadius: 8,
                padding: 12,
                marginBottom: 16,
              }}
            >
              <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>Detailed Metrics</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>
                    {['Pocket', 'Score', 'Volume', 'Hydro%', 'Enclosure', 'Depth', 'Sphericity'].map((h) => (
                      <th
                        key={h}
                        style={{
                          textAlign: 'left',
                          padding: '6px 8px',
                          color: 'var(--text2)',
                          fontSize: 10,
                          textTransform: 'uppercase',
                          borderBottom: '1px solid var(--border)',
                        }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {cavities.map((c: Pocket, i: number) => (
                    <tr key={i} style={{ borderBottom: '1px solid rgba(42,42,58,.4)' }}>
                      <td style={{ padding: '6px 8px', color: 'var(--accent)' }}>
                        P{c.id ?? c.pocket_id ?? c.rank ?? i + 1}
                      </td>
                      <td style={{ padding: '6px 8px', fontWeight: 700 }}>
                        {(c.bio_score ?? 0).toFixed(4)}
                      </td>
                      <td style={{ padding: '6px 8px' }}>{(c.volume ?? 0).toFixed(0)}</td>
                      <td style={{ padding: '6px 8px' }}>
                        {((c.hydrophobic_ratio ?? 0) * 100).toFixed(0)}%
                      </td>
                      <td style={{ padding: '6px 8px' }}>
                        {(c.score_components?.enclosure_score ?? c.enclosure_score ?? 0).toFixed(2)}
                      </td>
                      <td style={{ padding: '6px 8px' }}>
                        {(c.score_components?.depth_score ?? c.depth_score ?? 0).toFixed(2)}
                      </td>
                      <td style={{ padding: '6px 8px' }}>
                        {(c.score_components?.sphericity ?? 0).toFixed(2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Plot
              data={[
                {
                  x: cavities.map((c: Pocket) => c.center?.[0] ?? 0),
                  y: cavities.map((c: Pocket) => c.center?.[1] ?? 0),
                  z: cavities.map((c: Pocket) => c.center?.[2] ?? 0),
                  mode: 'markers+text',
                  type: 'scatter3d',
                  marker: {
                    color: cavities.map(
                      (c: Pocket) => cc[c.heuristic_quality_tier ?? 'low'] ?? '#ff4455'
                    ),
                    size: cavities.map((c: Pocket) =>
                      Math.max(
                        4,
                        Math.min(10, Math.sqrt(c.volume ?? 100) * 0.35)
                      )
                    ),
                    opacity: 0.85,
                    line: { color: '#fff', width: 0.5 },
                  },
                  text: cavities.map((c: Pocket) => 'P' + (c.id ?? c.pocket_id)),
                  textposition: 'top center',
                  textfont: { size: 8, color: '#aaa', family: 'monospace' },
                  hovertext: cavities.map(
                    (c: Pocket) =>
                      `P${c.id ?? c.pocket_id}\nScore: ${(c.bio_score ?? 0).toFixed(4)}\nVol: ${(c.volume ?? 0).toFixed(0)} A³\n${c.heuristic_quality_tier ?? 'low'}`
                  ),
                  hoverinfo: 'text',
                  name: 'Pockets',
                },
              ]}
              layout={{
                paper_bgcolor: '#0a0a0f',
                plot_bgcolor: '#0a0a0f',
                scene: {
                  xaxis: {
                    title: 'X',
                    color: '#6a6a8a',
                    gridcolor: '#1a1a24',
                    showbackground: false,
                  },
                  yaxis: {
                    title: 'Y',
                    color: '#6a6a8a',
                    gridcolor: '#1a1a24',
                    showbackground: false,
                  },
                  zaxis: {
                    title: 'Z',
                    color: '#6a6a8a',
                    gridcolor: '#1a1a24',
                    showbackground: false,
                  },
                  bgcolor: '#0a0a0f',
                  aspectmode: 'data',
                },
                font: { color: '#6a6a8a', family: 'monospace' },
                margin: { l: 0, r: 0, t: 30, b: 0 },
                title: {
                  text: (result.pdb_id ?? '') + ' Pocket Map',
                  font: { size: 13, color: '#00ff88' },
                },
                height: 400,
              }}
              config={{ responsive: true }}
              style={{ width: '100%' }}
            />
            </>
          )}
        </div>
      )}
    </div>
  );
}
