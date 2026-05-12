import { useEffect, useState } from 'react';
import Plot from 'react-plotly.js';
import { api } from '../services/api';
import KpiCard from '../components/KpiCard';

const PLOT_THEME = {
  paper_bgcolor: '#0a0a0f',
  plot_bgcolor: '#0a0a0f',
  font: { color: '#6a6a8a', size: 11, family: 'monospace' },
  margin: { l: 45, r: 20, t: 30, b: 45 },
  xaxis: { color: '#6a6a8a', gridcolor: '#1a1a24' },
  yaxis: { color: '#6a6a8a', gridcolor: '#1a1a24' },
  title: { font: { size: 12, color: '#00ff88' } },
};

export default function Dashboard() {
  const [stats, setStats] = useState<Record<string, number | string>>({});
  const [pockets, setPockets] = useState<any[]>([]);
  const [jobs, setJobs] = useState<any[]>([]);
  const [opsMetrics, setOpsMetrics] = useState<Record<string, number> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      api.overview(),
      api.pockets('&druggable_only=true'),
      api.jobs(),
      api.opsMetrics().catch(() => null),
    ])
      .then(([overviewRes, pocketsRes, jobsRes, ops]) => {
        if (cancelled) return;
        const s = overviewRes.summary || overviewRes.statistics || {};
        setStats({
          total_proteins: s.total_proteins ?? 0,
          total_pockets: s.total_pockets ?? 0,
          druggable_pockets: s.druggable_pockets ?? 0,
          avg_bio_score: (s.avg_bio_score ?? 0).toFixed(3),
        });
        setPockets(pocketsRes.pockets ?? pocketsRes.items ?? []);
        setJobs((jobsRes.jobs ?? []).slice(0, 10));
        setOpsMetrics(ops);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? 'Failed to load dashboard data');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  const classCounts: Record<string, number> = { high: 0, medium: 0, low: 0 };
  pockets.forEach((p) => {
    const c = p.druggability_class || 'low';
    classCounts[c] = (classCounts[c] ?? 0) + 1;
  });
  const vols = pockets.map((p) => p.volume || 0).filter((v) => v > 0);
  const scores = pockets.map((p) => p.bio_score || 0).filter((s) => s > 0);
  const top10ByScore = [...pockets]
    .sort((a, b) => (b.bio_score ?? 0) - (a.bio_score ?? 0))
    .slice(0, 10);

  const cc: Record<string, string> = { high: '#00ff88', medium: '#ffaa22', low: '#ff4455' };

  if (loading) {
    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16, color: 'var(--accent)' }}>
          ◉ Dashboard
        </h2>
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 48,
            textAlign: 'center',
            color: 'var(--text2)',
          }}
        >
          <div style={{ marginBottom: 8 }}>Loading...</div>
          <div style={{ fontSize: 11, fontFamily: 'monospace' }}>Fetching overview, pockets, and jobs</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16, color: 'var(--accent)' }}>
          ◉ Dashboard
        </h2>
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--danger)',
            borderRadius: 8,
            padding: 24,
            color: 'var(--danger)',
          }}
        >
          <strong>Error:</strong> {error}
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text2)' }}>
            Ensure the backend is running at http://127.0.0.1:8000
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ animation: 'fadeUp 0.3s ease both' }}>
      <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16, color: 'var(--accent)' }}>
        ◉ Dashboard
      </h2>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: 12,
          marginBottom: 16,
        }}
      >
        <KpiCard label="Proteins" value={stats.total_proteins ?? 0} icon="🧬" />
        <KpiCard label="Pockets" value={stats.total_pockets ?? 0} icon="◈" />
        <KpiCard label="Druggable" value={stats.druggable_pockets ?? 0} icon="💊" />
        <KpiCard label="Avg Score" value={String(stats.avg_bio_score ?? '0.000')} icon="⚡" />
      </div>
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
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 12,
          }}
        >
          <Plot
            data={[
              {
                x: vols,
                y: scores,
                mode: 'markers',
                type: 'scatter',
                marker: {
                  color: pockets.map((p) => cc[p.druggability_class] || '#6a6a8a'),
                  size: 9,
                  opacity: 0.8,
                  line: { color: 'rgba(0,0,0,0.3)', width: 0.5 },
                },
                text: pockets.map((p) => `${p.pdb_id} #${p.pocket_id}`),
                hoverinfo: 'text',
              },
            ]}
            layout={{
              ...PLOT_THEME,
              xaxis: { ...PLOT_THEME.xaxis, title: 'Volume (Å³)' },
              yaxis: { ...PLOT_THEME.yaxis, title: 'Bio-Score' },
              title: { ...PLOT_THEME.title, text: 'Score vs Volume' },
              height: 250,
            }}
            config={{ responsive: true, displayModeBar: false }}
            style={{ width: '100%' }}
          />
        </div>
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 12,
          }}
        >
          <Plot
            data={[
              {
                labels: ['high', 'medium', 'low'],
                values: [
                  classCounts.high ?? 0,
                  classCounts.medium ?? 0,
                  classCounts.low ?? 0,
                ],
                type: 'pie',
                hole: 0.45,
                marker: { colors: ['#00ff88', '#ffaa22', '#ff4455'] },
                textinfo: 'label+percent',
                textfont: { family: 'monospace', color: '#6a6a8a' },
              },
            ]}
            layout={{
              ...PLOT_THEME,
              paper_bgcolor: '#0a0a0f',
              margin: { l: 20, r: 20, t: 30, b: 20 },
              title: { ...PLOT_THEME.title, text: 'Druggability Class' },
              showlegend: false,
              height: 250,
            }}
            config={{ responsive: true, displayModeBar: false }}
            style={{ width: '100%' }}
          />
        </div>
      </div>
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
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 12,
          }}
        >
          <Plot
            data={[
              {
                x: top10ByScore.map((p) => `${p.pdb_id} #${p.pocket_id}`),
                y: top10ByScore.map((p) => p.bio_score ?? 0),
                type: 'bar',
                marker: {
                  color: top10ByScore.map((p) => cc[p.druggability_class] || '#6a6a8a'),
                  opacity: 0.9,
                },
              },
            ]}
            layout={{
              ...PLOT_THEME,
              xaxis: { ...PLOT_THEME.xaxis, tickangle: -35 },
              yaxis: { ...PLOT_THEME.yaxis, title: 'Bio-Score' },
              title: { ...PLOT_THEME.title, text: 'Top 10 Pockets by Score' },
              height: 250,
            }}
            config={{ responsive: true, displayModeBar: false }}
            style={{ width: '100%' }}
          />
        </div>
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 12,
          }}
        >
          <Plot
            data={[
              {
                x: scores.length ? scores : [0],
                type: 'histogram',
                marker: { color: '#00ff88', opacity: 0.7 },
                nbinsx: Math.min(20, Math.max(5, Math.ceil(scores.length / 3))),
              },
            ]}
            layout={{
              ...PLOT_THEME,
              xaxis: { ...PLOT_THEME.xaxis, title: 'Bio-Score' },
              yaxis: { ...PLOT_THEME.yaxis, title: 'Count' },
              title: { ...PLOT_THEME.title, text: 'Score Distribution' },
              height: 250,
            }}
            config={{ responsive: true, displayModeBar: false }}
            style={{ width: '100%' }}
          />
        </div>
      </div>
      {opsMetrics && (
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 12,
            marginBottom: 16,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13, color: 'var(--accent)' }}>
            Pipeline Performance
          </div>
          <div
            style={{
              display: 'flex',
              gap: 24,
              flexWrap: 'wrap',
              fontSize: 12,
              fontFamily: 'monospace',
              color: 'var(--text2)',
            }}
          >
            <span>
              Avg analysis time:{' '}
              <strong style={{ color: 'var(--accent)' }}>
                {(opsMetrics.avg_job_latency_seconds ?? 0).toFixed(2)}s
              </strong>
            </span>
            <span>
              P95 latency:{' '}
              <strong style={{ color: 'var(--accent)' }}>
                {(opsMetrics.p95_job_latency_seconds ?? 0).toFixed(2)}s
              </strong>
            </span>
            <span>
              Succeeded: <strong>{opsMetrics.succeeded_jobs ?? 0}</strong>
            </span>
            <span>
              Failed: <strong>{opsMetrics.failed_jobs ?? 0}</strong>
            </span>
            <span>
              Queue depth: <strong>{opsMetrics.queue_depth ?? 0}</strong>
            </span>
          </div>
        </div>
      )}
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
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 12,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>
            Recent Pockets
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                {['PDB', 'Pocket', 'Score', 'Volume', 'Class'].map((h) => (
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
              {pockets.slice(0, 10).map((p, i) => (
                <tr key={i} style={{ borderBottom: '1px solid rgba(42,42,58,.4)' }}>
                  <td style={{ padding: '6px 8px', color: 'var(--accent)', fontWeight: 700 }}>
                    {p.pdb_id}
                  </td>
                  <td style={{ padding: '6px 8px' }}>#{p.pocket_id}</td>
                  <td style={{ padding: '6px 8px' }}>{(p.bio_score || 0).toFixed(4)}</td>
                  <td style={{ padding: '6px 8px' }}>{(p.volume || 0).toFixed(0)}</td>
                  <td style={{ padding: '6px 8px' }}>
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: 10,
                        fontSize: 10,
                        fontWeight: 600,
                        background:
                          p.druggability_class === 'high'
                            ? 'rgba(0,255,136,.15)'
                            : p.druggability_class === 'medium'
                              ? 'rgba(255,170,34,.15)'
                              : 'rgba(255,68,85,.12)',
                        color:
                          p.druggability_class === 'high'
                            ? 'var(--accent)'
                            : p.druggability_class === 'medium'
                              ? 'var(--warn)'
                              : 'var(--danger)',
                      }}
                    >
                      {p.druggability_class}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {pockets.length === 0 && (
            <div style={{ textAlign: 'center', padding: 16, color: 'var(--text2)', fontSize: 12 }}>
              No pockets yet. Run analyses first.
            </div>
          )}
        </div>
        <div
          style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            padding: 12,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 8, fontSize: 13 }}>
            Recent Jobs
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                {['PDB', 'Status', 'Created'].map((h) => (
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
              {jobs.map((j) => (
                <tr key={j.job_id} style={{ borderBottom: '1px solid rgba(42,42,58,.4)' }}>
                  <td style={{ padding: '6px 8px', color: 'var(--accent)', fontWeight: 700 }}>
                    {j.pdb_id}
                  </td>
                  <td style={{ padding: '6px 8px' }}>
                    <span
                      style={{
                        padding: '2px 6px',
                        borderRadius: 6,
                        fontSize: 10,
                        fontWeight: 600,
                        background:
                          j.status === 'succeeded'
                            ? 'rgba(0,255,136,.15)'
                            : j.status === 'failed'
                              ? 'rgba(255,68,85,.15)'
                              : 'rgba(255,170,34,.15)',
                        color:
                          j.status === 'succeeded'
                            ? 'var(--accent)'
                            : j.status === 'failed'
                              ? 'var(--danger)'
                              : 'var(--warn)',
                      }}
                    >
                      {j.status}
                    </span>
                  </td>
                  <td style={{ padding: '6px 8px', color: 'var(--text2)', fontSize: 11 }}>
                    {j.created_at_utc
                      ? new Date(j.created_at_utc).toLocaleString()
                      : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {jobs.length === 0 && (
            <div style={{ textAlign: 'center', padding: 16, color: 'var(--text2)', fontSize: 12 }}>
              No jobs yet.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
