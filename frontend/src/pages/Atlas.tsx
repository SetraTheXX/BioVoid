import { useEffect, useState, useCallback, useRef } from 'react';
import Plot from 'react-plotly.js';
import { api } from '../services/api';
import type { Pocket, ProteinDetail } from '../types/api';
import { errorCorrelationId, errorMessage } from '../types/api';
import ErrorNotice from '../components/ErrorNotice';
import ProvenancePanel from '../components/ProvenancePanel';
import ResearchStatus from '../components/ResearchStatus';

const PAGE_SIZE = 10;
const cc: Record<string, string> = { high: '#00ff88', medium: '#ffaa22', low: '#ff4455' };
const PLOT_THEME = {
  paper_bgcolor: '#0a0a0f',
  plot_bgcolor: '#0a0a0f',
  font: { color: '#6a6a8a', size: 11, family: 'monospace' },
  xaxis: { color: '#6a6a8a', gridcolor: '#1a1a24' },
  yaxis: { color: '#6a6a8a', gridcolor: '#1a1a24' },
};

export default function Atlas() {
  const [pockets, setPockets] = useState<Pocket[]>([]);
  const [detail, setDetail] = useState<ProteinDetail | null>(null);
  const [backbone, setBackbone] = useState<{ x: number[]; y: number[]; z: number[] }>({
    x: [],
    y: [],
    z: [],
  });
  const [filter, setFilter] = useState('');
  const [pdbSearch, setPdbSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [errorCorrelationIdValue, setErrorCorrelationIdValue] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const listRequestId = useRef(0);
  const detailRequestId = useRef(0);

  const load = useCallback(async () => {
    const requestId = ++listRequestId.current;
    setLoading(true);
    setError(null);
    setErrorCorrelationIdValue(null);
    try {
      const r = await api.pockets({
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
        tier: filter || undefined,
        pdbId:
          /^[A-Z0-9]{4}$/.test(pdbSearch.trim().toUpperCase())
            ? pdbSearch.trim().toUpperCase()
            : undefined,
      });
      if (requestId !== listRequestId.current) return;
      const items = r.items;
      setPockets(items);
      setTotalCount(r.total ?? r.count);
    } catch (error: unknown) {
      if (requestId !== listRequestId.current) return;
      setError(errorMessage(error, 'Failed to load pockets'));
      setErrorCorrelationIdValue(errorCorrelationId(error));
      setPockets([]);
      setTotalCount(0);
    } finally {
      if (requestId === listRequestId.current) setLoading(false);
    }
  }, [filter, page, pdbSearch]);

  useEffect(() => {
    queueMicrotask(() => {
      void load();
    });
    return () => {
      listRequestId.current += 1;
      detailRequestId.current += 1;
    };
  }, [load]);

  const searchByPdb = useCallback(async () => {
    const q = pdbSearch.trim().toUpperCase();
    if (!/^[A-Z0-9]{4}$/.test(q)) return;
    const requestId = ++listRequestId.current;
    setLoading(true);
    setError(null);
    setErrorCorrelationIdValue(null);
    try {
      setPage(0);
      const r = await api.pockets({
        limit: PAGE_SIZE,
        offset: 0,
        tier: filter || undefined,
        pdbId: q,
      });
      if (requestId !== listRequestId.current) return;
      setPockets(r.items);
      setTotalCount(r.total ?? r.count);
    } catch (error: unknown) {
      if (requestId !== listRequestId.current) return;
      setError(errorMessage(error, `No data for PDB ${q}`));
      setErrorCorrelationIdValue(errorCorrelationId(error));
      setPockets([]);
      setTotalCount(0);
    } finally {
      if (requestId === listRequestId.current) setLoading(false);
    }
  }, [filter, pdbSearch]);

  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE));
  const paginatedPockets = pockets;

  async function showDetail(pocket: Pocket) {
    if (!pocket.pdb_id || !pocket.run_id) return;
    const requestId = ++detailRequestId.current;
    setDetail(null);
    setBackbone({ x: [], y: [], z: [] });
    setError(null);
    setErrorCorrelationIdValue(null);
    try {
      const r = await api.proteinDetail(pocket.pdb_id, pocket.run_id);
      if (requestId !== detailRequestId.current) return;
      setDetail(r);
      try {
        const txt = await api.proteinStructure(pocket.pdb_id, pocket.run_id);
        if (requestId !== detailRequestId.current) return;
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
      } catch (structureError: unknown) {
        if (requestId !== detailRequestId.current) return;
        setBackbone({ x: [], y: [], z: [] });
        setError('Prepared structure could not be loaded; metadata remains available.');
        setErrorCorrelationIdValue(errorCorrelationId(structureError));
      }
    } catch (detailError: unknown) {
      if (requestId !== detailRequestId.current) return;
      setDetail(null);
      setError(errorMessage(detailError, 'Failed to load protein details'));
      setErrorCorrelationIdValue(errorCorrelationId(detailError));
    }
  }

  const dp = detail?.pockets ?? [];
  const dpWithCoords = dp.map((p: Pocket) => ({
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
            id="atlas-pdb-search"
            aria-label="Search Atlas by PDB ID"
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
            type="button"
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
            id="atlas-tier-filter"
            aria-label="Filter pockets by heuristic tier"
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
            type="button"
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
          <ErrorNotice
            message={error}
            correlationId={errorCorrelationIdValue}
            className="atlas-error"
          />
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
                  {['PDB', 'Run', 'Pocket', 'Score', 'Volume', 'Tier', 'Sphericity', 'Merged V', 'Validation'].map((h) => (
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
                    onClick={() => void showDetail(p)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        void showDetail(p);
                      }
                    }}
                    tabIndex={0}
                    role="button"
                    aria-label={`Open ${p.pdb_id} ${p.pocket_id} analysis`}
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
                    <td
                      title={p.run_id}
                      style={{ padding: '6px 8px', fontFamily: 'monospace' }}
                    >
                      {p.run_id?.slice(0, 8) ?? 'unknown'}
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
                            (cc[p.heuristic_quality_tier ?? 'low'] ?? '#ff4455') + '22',
                          color: cc[p.heuristic_quality_tier ?? 'low'] ?? '#ff4455',
                        }}
                      >
                        {p.heuristic_quality_tier ?? 'low'}
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
                          color: p.canonical_eligible ? '#00ff88' : '#ffaa22',
                          background: p.canonical_eligible
                            ? 'rgba(0,255,136,.16)'
                            : 'rgba(255,170,34,.16)',
                        }}
                      >
                        {p.validation_status ?? 'unknown'}
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
              type="button"
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
          <ResearchStatus
            validationStatus={detail.validation_status}
            canonicalEligible={detail.canonical_eligible}
            motionStatus={detail.motion_aware?.status}
            motion={detail.motion_aware}
            compact
          />
          <div style={{ margin: '12px 0' }}>
            <ProvenancePanel
              runId={detail.run_id}
              preparedSha256={detail.prepared_sha256}
              analysisContract={{
                detector_version: detail.detector_version,
                scoring_contract_version: detail.scoring_contract_version,
                validation_status: detail.validation_status,
                canonical_eligible: detail.canonical_eligible,
                ranking_contract: 'product-heuristic-ranking-v1',
              }}
              preparation={detail.preparation}
              provenance={detail.provenance}
              rankingContract={detail.scoring?.ranking_contract_version}
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
              <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent)' }}>
                {detail.total_pockets ?? 0}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text2)' }}>POCKETS</div>
            </div>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent)' }}>
                {detail.heuristic_shortlist_pockets ?? 0}
              </div>
              <div style={{ fontSize: 9, color: 'var(--text2)' }}>SHORTLIST</div>
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
                      x: dpWithCoords.map((p: Pocket) => p.center_x ?? 0),
                      y: dpWithCoords.map((p: Pocket) => p.center_y ?? 0),
                      z: dpWithCoords.map((p: Pocket) => p.center_z ?? 0),
                      mode: 'markers+text' as const,
                      type: 'scatter3d' as const,
                      marker: {
                        color: dpWithCoords.map(
                          (p: Pocket) => cc[p.heuristic_quality_tier ?? 'low'] ?? '#ff4455'
                        ),
                        size: dpWithCoords.map((p: Pocket) =>
                          Math.max(
                            4,
                            Math.min(10, Math.sqrt(p.volume ?? 100) * 0.35)
                          )
                        ),
                        opacity: 0.85,
                        line: { color: '#fff', width: 0.5 },
                      },
                      text: dpWithCoords.map((p: Pocket) => 'P' + p.pocket_id),
                      textposition: 'top center' as const,
                      textfont: { size: 8, color: '#aaa', family: 'monospace' },
                      hovertext: dpWithCoords.map(
                        (p: Pocket) =>
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
                      x: dp.map((p: Pocket) => `P${p.pocket_id}`),
                      y: dp.map((p: Pocket) => p.volume ?? 0),
                      type: 'bar',
                      marker: {
                        color: dp.map((p: Pocket) => cc[p.heuristic_quality_tier ?? 'low'] ?? '#6a6a8a'),
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
                      x: dpSortedByRank.map((p: Pocket) => `#${p.rank ?? p.pocket_id}`),
                      y: dpSortedByRank.map((p: Pocket) => p.bio_score ?? 0),
                      type: 'scatter',
                      mode: 'lines+markers',
                      line: { color: '#00ff88', width: 2 },
                      marker: {
                        size: 8,
                        color: dpSortedByRank.map((p: Pocket) => cc[p.heuristic_quality_tier ?? 'low'] ?? '#6a6a8a'),
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
                  'Validation',
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
              {dp.map((p: Pocket, i: number) => (
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
                          (cc[p.heuristic_quality_tier ?? 'low'] ?? '#ff4455') + '22',
                        color: cc[p.heuristic_quality_tier ?? 'low'] ?? '#ff4455',
                      }}
                    >
                      {p.heuristic_quality_tier ?? 'low'}
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
                        color: p.canonical_eligible ? '#00ff88' : '#ffaa22',
                        background: p.canonical_eligible
                          ? 'rgba(0,255,136,.16)'
                          : 'rgba(255,170,34,.16)',
                      }}
                    >
                      {p.validation_status ?? 'unknown'}
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
