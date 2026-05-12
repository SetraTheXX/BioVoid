import { useEffect, useState, useCallback } from 'react';
import Plot from 'react-plotly.js';
import { api } from '../services/api';

const PAGE_SIZE = 10;
const cc: Record<string, string> = { high: '#00ff88', medium: '#ffaa22', low: '#ff4455' };
const evidenceColors: Record<string, { bg: string; color: string }> = {
  strong: { bg: 'rgba(0,255,136,.2)', color: '#00ff88' },
  moderate: { bg: 'rgba(34,211,238,.2)', color: '#22d3ee' },
  weak: { bg: 'rgba(255,170,34,.2)', color: '#ffaa22' },
  insufficient: { bg: 'rgba(106,106,138,.2)', color: '#6a6a8a' },
};

function evidenceLevel(p: any): string {
  const score = p.bio_score ?? 0;
  const verts = p.merged_vertices ?? 0;
  const encl = p.enclosure_score ?? 0;
  if (score >= 0.55 && verts >= 8 && encl >= 0.6) return 'strong';
  if (score >= 0.55 || (score >= 0.3 && verts >= 4)) return 'moderate';
  if (score >= 0.2) return 'weak';
  return 'insufficient';
}

const PLOT_THEME = {
  paper_bgcolor: '#0a0a0f',
  plot_bgcolor: '#0a0a0f',
  font: { color: '#6a6a8a', size: 11, family: 'monospace' },
  xaxis: { color: '#6a6a8a', gridcolor: '#1a1a24' },
  yaxis: { color: '#6a6a8a', gridcolor: '#1a1a24' },
};

export default function Atlas() {
  const [pockets, setPockets] = useState<any[]>([]);
  const [detail, setDetail] = useState<any>(null);
  const [backbone, setBackbone] = useState<{ x: number[]; y: number[]; z: number[] }>({
    x: [],
    y: [],
    z: [],
  });
  const [filter, setFilter] = useState('');
  const [pdbSearch, setPdbSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [totalCount, setTotalCount] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = filter ? `&druggability_class=${filter}` : '';
      const r = await api.pockets(params);
      const items = r.pockets ?? r.items ?? [];
      setPockets(items);
      setTotalCount(items.length);
    } catch (e: any) {
      setError(e?.message ?? 'Failed to load pockets');
      setPockets([]);
      setTotalCount(0);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  const searchByPdb = useCallback(async () => {
    const q = pdbSearch.trim().toUpperCase();
    if (!q || q.length < 4) return;
    setLoading(true);
    setError(null);
    try {
      const r = await api.proteinDetail(q);
      const dp = r.pockets ?? [];
      setPockets(
        dp.map((p: any) => ({
          ...p,
          pdb_id: r.pdb_id ?? q,
          center_x: p.center?.[0] ?? p.center_x,
          center_y: p.center?.[1] ?? p.center_y,
          center_z: p.center?.[2] ?? p.center_z,
        }))
      );
      setTotalCount(dp.length);
    } catch (e: any) {
      setError(e?.message ?? `No data for PDB ${q}`);
      setPockets([]);
      setTotalCount(0);
    } finally {
      setLoading(false);
    }
  }, [pdbSearch]);

  const filteredPockets = pdbSearch.trim()
    ? pockets.filter((p) =>
        (p.pdb_id ?? '').toUpperCase().includes(pdbSearch.trim().toUpperCase())
      )
    : pockets;

  const totalPages = Math.max(1, Math.ceil(filteredPockets.length / PAGE_SIZE));
  const paginatedPockets = filteredPockets.slice(
    page * PAGE_SIZE,
    page * PAGE_SIZE + PAGE_SIZE
  );

  async function showDetail(pdbId: string) {
    setDetail(null);
    setBackbone({ x: [], y: [], z: [] });
    try {
      const r = await api.proteinDetail(pdbId);
      setDetail(r);
      try {
        const txt = await api.proteinStructure(pdbId);
        const bx: number[] = [],
          by: number[] = [],
          bz: number[] = [];
        txt.split('\n').forEach((l) => {
          if (l.startsWith('ATOM') && l.substring(12, 16).trim() === 'CA') {
            bx.push(parseFloat(l.substring(30, 38)));
            by.push(parseFloat(l.substring(38, 46)));
            bz.push(parseFloat(l.substring(46, 54)));
          }
        });
        setBackbone({ x: bx, y: by, z: bz });
      } catch {
        setBackbone({ x: [], y: [], z: [] });
      }
    } catch {
      setDetail(null);
    }
  }

  const dp = detail?.pockets ?? [];
  const dpWithCoords = dp.map((p: any) => ({
    ...p,
    center_x: p.center?.[0] ?? p.center_x ?? 0,
    center_y: p.center?.[1] ?? p.center_y ?? 0,
    center_z: p.center?.[2] ?? p.center_z ?? 0,
  }));
  const topPocket = dp[0];
  const radarMetrics = topPocket
    ? [
        topPocket.volume_score ?? Math.min(1, Math.max(0, ((topPocket.volume ?? 0) - 80) / 2420)),
        topPocket.hydrophobic_ratio ?? 0,
        topPocket.enclosure_score ?? 0,
        topPocket.depth_score ?? 0,
        topPocket.sphericity ?? 0,
      ]
    : [];
  const dpSortedByRank = [...dp].sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0));

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16, color: 'var(--accent)' }}>
        ◈ Pocket Atlas
      </h2>
      <div
        style={{
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 8,
          padding: 12,
          marginBottom: 12,
        }}
      >
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: 8,
            marginBottom: 10,
            alignItems: 'center',
          }}
        >
          <input
            type="text"
            placeholder="Search by PDB ID (e.g. 1CBS)"
            value={pdbSearch}
            onChange={(e) => setPdbSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && searchByPdb()}
            style={{
              background: 'var(--surface2)',
              border: '1px solid var(--border)',
              color: 'var(--text)',
              padding: '6px 10px',
              borderRadius: 6,
              fontSize: 12,
              fontFamily: 'monospace',
              minWidth: 180,
            }}
          />
          <button
            onClick={searchByPdb}
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
            }}
          >
            Search
          </button>
          <select
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setPage(0);
            }}
            style={{
              background: 'var(--surface2)',
              border: '1px solid var(--border)',
              color: 'var(--text)',
              padding: '6px 10px',
              borderRadius: 6,
              fontSize: 12,
              fontFamily: 'monospace',
            }}
          >
            <option value="">All classes</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <button
            onClick={() => {
              setPdbSearch('');
              setPage(0);
              load();
            }}
            style={{
              padding: '6px 14px',
              background: 'transparent',
              border: '1px solid var(--border)',
              color: 'var(--text2)',
              borderRadius: 6,
              fontSize: 12,
              cursor: 'pointer',
              fontFamily: 'monospace',
            }}
          >
            Refresh
          </button>
          <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text2)' }}>
            {totalCount} result{totalCount !== 1 ? 's' : ''}
          </span>
        </div>

        {error && (
          <div
            style={{
              padding: 8,
              marginBottom: 8,
              background: 'rgba(255,68,85,.1)',
              border: '1px solid var(--danger)',
              borderRadius: 6,
              color: 'var(--danger)',
              fontSize: 12,
            }}
          >
            {error}
          </div>
        )}

        {loading ? (
          <div
            style={{
              textAlign: 'center',
              padding: 32,
              color: 'var(--text2)',
              fontSize: 12,
            }}
          >
            Loading pockets...
          </div>
        ) : (
          <>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  {['PDB', 'Pocket', 'Score', 'Volume', 'Class', 'Sphericity', 'Merged V', 'Evidence'].map((h) => (
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
                {paginatedPockets.map((p, i) => (
                  <tr
                    key={`${p.pdb_id}-${p.pocket_id}-${i}`}
                    onClick={() => showDetail(p.pdb_id)}
                    style={{
                      cursor: 'pointer',
                      borderBottom: '1px solid rgba(42,42,58,.4)',
                    }}
                  >
                    <td
                      style={{
                        padding: '6px 8px',
                        color: 'var(--accent)',
                        fontWeight: 700,
                      }}
                    >
                      {p.pdb_id}
                    </td>
                    <td style={{ padding: '6px 8px' }}>#{p.pocket_id}</td>
                    <td style={{ padding: '6px 8px' }}>
                      {(p.bio_score ?? 0).toFixed(4)}
                    </td>
                    <td style={{ padding: '6px 8px' }}>
                      {(p.volume ?? 0).toFixed(0)}
                    </td>
                    <td style={{ padding: '6px 8px' }}>
                      <span
                        style={{
                          padding: '2px 8px',
                          borderRadius: 10,
                          fontSize: 10,
                          fontWeight: 600,
                          background:
                            (cc[p.druggability_class] ?? '#ff4455') + '22',
                          color: cc[p.druggability_class] ?? '#ff4455',
                        }}
                      >
                        {p.druggability_class ?? 'low'}
                      </span>
                    </td>
                    <td style={{ padding: '6px 8px' }}>
                      {(p.sphericity ?? 0).toFixed(2)}
                    </td>
                    <td style={{ padding: '6px 8px' }}>{p.merged_vertices ?? '-'}</td>
                    <td style={{ padding: '6px 8px' }}>
                      <span
                        style={{
                          padding: '2px 6px',
                          borderRadius: 6,
                          fontSize: 9,
                          fontWeight: 600,
                          textTransform: 'capitalize',
                          ...evidenceColors[evidenceLevel(p)],
                        }}
                      >
                        {evidenceLevel(p)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {paginatedPockets.length === 0 && (
              <div
                style={{
                  textAlign: 'center',
                  padding: 16,
                  color: 'var(--text2)',
                  fontSize: 12,
                }}
              >
                No data. Run analyses first or search by PDB ID.
              </div>
            )}

            {totalPages > 1 && (
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'center',
                  gap: 8,
                  marginTop: 12,
                  alignItems: 'center',
                }}
              >
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  style={{
                    padding: '4px 12px',
                    background: page === 0 ? 'var(--surface2)' : 'transparent',
                    border: '1px solid var(--border)',
                    color: page === 0 ? 'var(--text2)' : 'var(--text)',
                    borderRadius: 6,
                    fontSize: 11,
                    cursor: page === 0 ? 'not-allowed' : 'pointer',
                    fontFamily: 'monospace',
                  }}
                >
                  Prev
                </button>
                <span style={{ fontSize: 12, color: 'var(--text2)' }}>
                  Page {page + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  style={{
                    padding: '4px 12px',
                    background:
                      page >= totalPages - 1 ? 'var(--surface2)' : 'transparent',
                    border: '1px solid var(--border)',
                    color:
                      page >= totalPages - 1 ? 'var(--text2)' : 'var(--text)',
                    borderRadius: 6,
                    fontSize: 11,
                    cursor:
                      page >= totalPages - 1 ? 'not-allowed' : 'pointer',
                    fontFamily: 'monospace',
                  }}
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>

      {detail && (
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
            }}
          >
            <span style={{ fontWeight: 700, fontSize: 16 }}>
              {(detail.pdb_id ?? '').toUpperCase()} Analysis
            </span>
            <button
              onClick={() => setDetail(null)}
              style={{
                padding: '4px 12px',
                background: 'transparent',
                border: '1px solid var(--border)',
                color: 'var(--text2)',
                borderRadius: 6,
                fontSize: 11,
                cursor: 'pointer',
                fontFamily: 'monospace',
              }}
            >
              Close
            </button>
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
              <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent)' }}>
                {detail.total_pockets ?? 0}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text2)' }}>POCKETS</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent)' }}>
                {detail.druggable_pockets ?? 0}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text2)' }}>DRUGGABLE</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent)' }}>
                {(detail.max_bio_score ?? 0).toFixed(3)}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text2)' }}>TOP SCORE</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent)' }}>
                {(detail.avg_volume ?? 0).toFixed(0)}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text2)' }}>AVG VOL</div>
            </div>
          </div>

          <Plot
            data={[
              ...(backbone.x.length > 3
                ? [
                    {
                      x: backbone.x,
                      y: backbone.y,
                      z: backbone.z,
                      mode: 'lines' as const,
                      type: 'scatter3d' as const,
                      line: { color: '#3388ff', width: 3 },
                      opacity: 0.4,
                      name: 'Backbone',
                      hoverinfo: 'skip' as const,
                    },
                  ]
                : []),
              ...(dpWithCoords.length > 0
                ? [
                    {
                      x: dpWithCoords.map((p: any) => p.center_x ?? 0),
                      y: dpWithCoords.map((p: any) => p.center_y ?? 0),
                      z: dpWithCoords.map((p: any) => p.center_z ?? 0),
                      mode: 'markers+text' as const,
                      type: 'scatter3d' as const,
                      marker: {
                        color: dpWithCoords.map(
                          (p: any) => cc[p.druggability_class] ?? '#ff4455'
                        ),
                        size: dpWithCoords.map((p: any) =>
                          Math.max(
                            4,
                            Math.min(10, Math.sqrt(p.volume ?? 100) * 0.35)
                          )
                        ),
                        opacity: 0.85,
                        line: { color: '#fff', width: 0.5 },
                      },
                      text: dpWithCoords.map((p: any) => 'P' + p.pocket_id),
                      textposition: 'top center' as const,
                      textfont: { size: 8, color: '#aaa', family: 'monospace' },
                      hovertext: dpWithCoords.map(
                        (p: any) =>
                          `P${p.pocket_id}\nScore: ${(p.bio_score ?? 0).toFixed(4)}\nVol: ${(p.volume ?? 0).toFixed(0)}`
                      ),
                      hoverinfo: 'text' as const,
                      name: 'Pockets',
                    },
                  ]
                : []),
            ]}
            layout={{
              paper_bgcolor: '#0a0a0f',
              plot_bgcolor: '#0a0a0f',
              scene: {
                xaxis: {
                  title: 'X (Å)',
                  color: '#6a6a8a',
                  gridcolor: '#1a1a24',
                  showbackground: false,
                },
                yaxis: {
                  title: 'Y (Å)',
                  color: '#6a6a8a',
                  gridcolor: '#1a1a24',
                  showbackground: false,
                },
                zaxis: {
                  title: 'Z (Å)',
                  color: '#6a6a8a',
                  gridcolor: '#1a1a24',
                  showbackground: false,
                },
                bgcolor: '#0a0a0f',
                aspectmode: 'data',
              },
              font: { color: '#6a6a8a', family: 'monospace' },
              margin: { l: 0, r: 0, t: 30, b: 0 },
              height: 420,
              title: {
                text:
                  (detail.pdb_id ?? '').toUpperCase() + ' Pocket Map',
                font: { size: 13, color: '#00ff88' },
              },
            }}
            config={{ responsive: true }}
            style={{ width: '100%' }}
          />

          {dp.length > 0 && (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: 12,
                marginTop: 16,
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
                      r: [...radarMetrics, radarMetrics[0]],
                      theta: ['Volume', 'Hydrophobicity', 'Enclosure', 'Depth', 'Sphericity', 'Volume'],
                      type: 'scatterpolar',
                      fill: 'toself',
                      line: { color: '#00ff88', width: 1.5 },
                      marker: { size: 6, color: '#00ff88' },
                    },
                  ]}
                  layout={{
                    paper_bgcolor: '#0a0a0f',
                    polar: {
                      bgcolor: '#0a0a0f',
                      radialaxis: { range: [0, 1], color: '#6a6a8a', gridcolor: '#1a1a24' },
                      angularaxis: { color: '#6a6a8a', gridcolor: '#1a1a24' },
                    },
                    font: { color: '#6a6a8a', size: 10, family: 'monospace' },
                    margin: { l: 60, r: 60, t: 30, b: 30 },
                    title: { text: "Top Pocket Metrics", font: { size: 11, color: '#00ff88' } },
                    height: 220,
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
                      x: dp.map((p: any) => `P${p.pocket_id}`),
                      y: dp.map((p: any) => p.volume ?? 0),
                      type: 'bar',
                      marker: {
                        color: dp.map((p: any) => cc[p.druggability_class] ?? '#6a6a8a'),
                        opacity: 0.9,
                      },
                    },
                  ]}
                  layout={{
                    ...PLOT_THEME,
                    xaxis: { ...PLOT_THEME.xaxis, title: 'Pocket' },
                    yaxis: { ...PLOT_THEME.yaxis, title: 'Volume (Å³)' },
                    title: { text: 'Volume Comparison', font: { size: 11, color: '#00ff88' } },
                    height: 220,
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
                      x: dpSortedByRank.map((p: any) => `#${p.rank ?? p.pocket_id}`),
                      y: dpSortedByRank.map((p: any) => p.bio_score ?? 0),
                      type: 'scatter',
                      mode: 'lines+markers',
                      line: { color: '#00ff88', width: 2 },
                      marker: {
                        size: 8,
                        color: dpSortedByRank.map((p: any) => cc[p.druggability_class] ?? '#6a6a8a'),
                      },
                    },
                  ]}
                  layout={{
                    ...PLOT_THEME,
                    xaxis: { ...PLOT_THEME.xaxis, title: 'Rank' },
                    yaxis: { ...PLOT_THEME.yaxis, title: 'Bio-Score' },
                    title: { text: 'Score Trend by Rank', font: { size: 11, color: '#00ff88' } },
                    height: 220,
                  }}
                  config={{ responsive: true, displayModeBar: false }}
                  style={{ width: '100%' }}
                />
              </div>
            </div>
          )}

          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontSize: 12,
              marginTop: 12,
            }}
          >
            <thead>
              <tr>
                {[
                  'Pocket',
                  'Score',
                  'Volume',
                  'Class',
                  'Hydro%',
                  'Enclosure',
                  'Depth',
                  'Sphericity',
                  'Merged V',
                  'Evidence',
                ].map((h) => (
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
              {dp.map((p: any, i: number) => (
                <tr key={i} style={{ borderBottom: '1px solid rgba(42,42,58,.4)' }}>
                  <td style={{ padding: '6px 8px', color: 'var(--accent)' }}>
                    #{p.pocket_id}
                  </td>
                  <td style={{ padding: '6px 8px', fontWeight: 700 }}>
                    {(p.bio_score ?? 0).toFixed(4)}
                  </td>
                  <td style={{ padding: '6px 8px' }}>
                    {(p.volume ?? 0).toFixed(0)}
                  </td>
                  <td style={{ padding: '6px 8px' }}>
                    <span
                      style={{
                        padding: '2px 6px',
                        borderRadius: 8,
                        fontSize: 10,
                        fontWeight: 600,
                        background:
                          (cc[p.druggability_class] ?? '#ff4455') + '22',
                        color: cc[p.druggability_class] ?? '#ff4455',
                      }}
                    >
                      {p.druggability_class ?? 'low'}
                    </span>
                  </td>
                  <td style={{ padding: '6px 8px' }}>
                    {((p.hydrophobic_ratio ?? 0) * 100).toFixed(0)}%
                  </td>
                  <td style={{ padding: '6px 8px' }}>
                    {(p.enclosure_score ?? 0).toFixed(2)}
                  </td>
                  <td style={{ padding: '6px 8px' }}>
                    {(p.depth_score ?? 0).toFixed(2)}
                  </td>
                  <td style={{ padding: '6px 8px' }}>
                    {(p.sphericity ?? 0).toFixed(2)}
                  </td>
                  <td style={{ padding: '6px 8px' }}>{p.merged_vertices ?? '-'}</td>
                  <td style={{ padding: '6px 8px' }}>
                    <span
                      style={{
                        padding: '2px 6px',
                        borderRadius: 6,
                        fontSize: 9,
                        fontWeight: 600,
                        textTransform: 'capitalize',
                        ...evidenceColors[evidenceLevel(p)],
                      }}
                    >
                      {evidenceLevel(p)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
