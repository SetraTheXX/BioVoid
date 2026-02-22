"""
BioVoid — Unified Web Application
====================================

Single web application that combines:
- Scientific dashboard (charts, KPIs, pocket browser)
- Analysis submission & tracking
- Discovery reports
- System health monitoring

All served from FastAPI at /portal
"""

from __future__ import annotations


def render_portal_html() -> str:
    return _HTML


_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>BioVoid — Cryptic Pocket Discovery</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet"/>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<script>
// Try loading 3Dmol.js from multiple CDNs
(function(){
  var urls=['https://3dmol.csb.pitt.edu/build/3Dmol-min.js','https://unpkg.com/3dmol@2.0.6/build/3Dmol-min.js','https://cdn.jsdelivr.net/npm/3dmol@2.0.6/build/3Dmol-min.js'];
  var loaded=false;
  function tryLoad(i){
    if(i>=urls.length||loaded)return;
    var s=document.createElement('script');
    s.src=urls[i];
    s.onload=function(){loaded=true;window._3dmol_loaded=true;console.log('3Dmol loaded from: '+urls[i])};
    s.onerror=function(){console.warn('3Dmol CDN failed: '+urls[i]);tryLoad(i+1)};
    document.head.appendChild(s);
  }
  tryLoad(0);
})();
</script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0c0e14;--s1:#13161f;--s2:#1a1e2a;--s3:#232836;--border:#2a3040;--text:#e2e6ef;--text2:#7b83a0;--cyan:#22d3ee;--cyan2:#06b6d4;--green:#34d399;--emerald:#10b981;--red:#f87171;--amber:#fbbf24;--purple:#a78bfa;--r:12px}
html{scroll-behavior:smooth}
body{font-family:'Inter',system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.6}

/* SIDEBAR */
.layout{display:flex;min-height:100vh}
.sidebar{width:240px;background:var(--s1);border-right:1px solid var(--border);padding:20px 0;position:fixed;top:0;left:0;height:100vh;overflow-y:auto;z-index:50}
.sidebar-logo{padding:0 20px 24px;font-size:22px;font-weight:800;color:var(--cyan);letter-spacing:-0.5px}
.sidebar-logo small{display:block;font-size:11px;font-weight:400;color:var(--text2);letter-spacing:1px;text-transform:uppercase;margin-top:2px}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 20px;color:var(--text2);cursor:pointer;font-size:14px;font-weight:500;transition:all .15s;border-left:3px solid transparent}
.nav-item:hover{color:var(--text);background:rgba(34,211,238,.04)}
.nav-item.active{color:var(--cyan);background:rgba(34,211,238,.08);border-left-color:var(--cyan)}
.nav-section{padding:16px 20px 6px;font-size:11px;font-weight:600;color:var(--text2);text-transform:uppercase;letter-spacing:1.5px}
.sidebar-footer{position:absolute;bottom:0;left:0;right:0;padding:12px 20px;border-top:1px solid var(--border);font-size:11px;color:var(--text2)}
.status-dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px}
.dot-ok{background:var(--green)}.dot-err{background:var(--red)}.dot-warn{background:var(--amber)}

/* MAIN */
.main{margin-left:240px;padding:24px 32px;flex:1;min-height:100vh}
@media(max-width:900px){.sidebar{display:none}.main{margin-left:0;padding:16px}}

/* CARDS */
.card{background:var(--s2);border:1px solid var(--border);border-radius:var(--r);padding:20px;margin-bottom:16px}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.card-title{font-size:15px;font-weight:600;color:var(--text)}
.grid{display:grid;gap:16px}.g2{grid-template-columns:1fr 1fr}.g3{grid-template-columns:1fr 1fr 1fr}.g4{grid-template-columns:repeat(4,1fr)}
@media(max-width:768px){.g2,.g3,.g4{grid-template-columns:1fr}}

/* KPI */
.kpi{background:var(--s2);border:1px solid var(--border);border-radius:var(--r);padding:20px;text-align:center}
.kpi-icon{font-size:28px;margin-bottom:8px}
.kpi-val{font-size:32px;font-weight:800;background:linear-gradient(135deg,var(--cyan),var(--green));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.kpi-label{font-size:12px;color:var(--text2);text-transform:uppercase;letter-spacing:1px;margin-top:4px}

/* TABLE */
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;padding:10px 12px;color:var(--text2);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid var(--border)}
td{padding:10px 12px;border-bottom:1px solid rgba(42,48,64,.5)}
tr:hover td{background:rgba(34,211,238,.03)}

/* FORM */
input,select,textarea{background:var(--s3);border:1px solid var(--border);color:var(--text);padding:10px 14px;border-radius:8px;font-size:14px;width:100%;font-family:inherit;transition:border .15s}
input:focus,select:focus{outline:none;border-color:var(--cyan)}
label{display:block;font-size:12px;color:var(--text2);margin-bottom:4px;font-weight:500}

/* BUTTONS */
.btn{padding:10px 20px;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:all .15s;font-family:inherit}
.btn-cyan{background:var(--cyan);color:var(--bg)}.btn-cyan:hover{background:var(--cyan2);transform:translateY(-1px)}
.btn-ghost{background:transparent;color:var(--text2);border:1px solid var(--border)}.btn-ghost:hover{border-color:var(--cyan);color:var(--text)}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none}
.btn:active{transform:scale(.97)}

/* BADGES */
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600}
.b-high{background:rgba(16,185,129,.15);color:var(--emerald)}.b-medium{background:rgba(251,191,36,.15);color:var(--amber)}.b-low{background:rgba(248,113,113,.12);color:var(--red)}
.b-queued{background:rgba(167,139,250,.12);color:var(--purple)}.b-running{background:rgba(34,211,238,.12);color:var(--cyan)}.b-succeeded{background:rgba(52,211,153,.12);color:var(--green)}.b-failed{background:rgba(248,113,113,.12);color:var(--red)}

/* MISC */
.progress-bar{height:6px;background:var(--s3);border-radius:3px;overflow:hidden}
.progress-fill{height:100%;background:linear-gradient(90deg,var(--cyan),var(--green));transition:width .3s;border-radius:3px}
.log-area{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:12px;font-family:'Courier New',monospace;font-size:12px;color:var(--green);max-height:180px;overflow-y:auto;white-space:pre-wrap}
.section{display:none}.section.active{display:block}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.card,.kpi{animation:fadeUp .35s ease-out both}
</style>
</head>
<body>
<div class="layout">
  <!-- SIDEBAR -->
  <nav class="sidebar">
    <div class="sidebar-logo">BioVoid<small>Cryptic Pocket Discovery</small></div>
    <div class="nav-section">Analysis</div>
    <div class="nav-item active" data-section="dashboard">Dashboard</div>
    <div class="nav-item" data-section="analyze">New Analysis</div>
    <div class="nav-item" data-section="jobs">Job History</div>
    <div class="nav-section">Discovery</div>
    <div class="nav-item" data-section="atlas">Pocket Atlas</div>
    <div class="nav-item" data-section="report">Reports</div>
    <div class="nav-section">Validation</div>
    <div class="nav-item" data-section="benchmark">Benchmark</div>
    <div class="nav-section">Visuals</div>
    <div class="nav-item" data-section="gallery">Gallery</div>
    <div class="nav-section">System</div>
    <div class="nav-item" data-section="system">System Info</div>
    <div class="sidebar-footer"><span class="status-dot dot-ok" id="health-dot"></span><span id="health-text">Online</span></div>
  </nav>

  <!-- MAIN CONTENT -->
  <main class="main">

    <!-- DASHBOARD -->
    <div class="section active" id="sec-dashboard">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">Dashboard</h2>
      <div class="grid g4" id="dash-kpis">
        <div class="kpi"><div class="kpi-icon">🧬</div><div class="kpi-val" id="kpi-proteins">-</div><div class="kpi-label">Proteins</div></div>
        <div class="kpi"><div class="kpi-icon">🔬</div><div class="kpi-val" id="kpi-pockets">-</div><div class="kpi-label">Pockets</div></div>
        <div class="kpi"><div class="kpi-icon">💊</div><div class="kpi-val" id="kpi-druggable">-</div><div class="kpi-label">Druggable</div></div>
        <div class="kpi"><div class="kpi-icon">⭐</div><div class="kpi-val" id="kpi-elite">-</div><div class="kpi-label">Elite</div></div>
      </div>
      <div class="grid g2">
        <div class="card"><div class="card-title">Score Distribution</div><div id="ch-hist" style="height:280px"></div></div>
        <div class="card"><div class="card-title">Volume vs Score</div><div id="ch-scatter" style="height:280px"></div></div>
      </div>
      <div class="grid g2">
        <div class="card"><div class="card-title">Druggability Classes</div><div id="ch-pie" style="height:280px"></div></div>
        <div class="card"><div class="card-title">Top Discoveries</div><div id="ch-bar" style="height:280px"></div></div>
      </div>
      <div class="grid g2">
        <div class="card">
          <div class="card-header"><div class="card-title">Recent Discoveries</div></div>
          <table><thead><tr><th>PDB</th><th>Pocket</th><th>Bio-Score</th><th>Volume</th><th>Class</th></tr></thead><tbody id="dash-recent"></tbody></table>
        </div>
        <div class="card">
          <div class="card-title">Scientific Validation</div>
          <div style="padding:8px 0">
            <div style="display:flex;justify-content:space-between;margin-bottom:10px"><span style="color:var(--text2)">Recall (known pockets)</span><span style="font-weight:700;color:var(--green)">35.0% (7/20)</span></div>
            <div class="progress-bar" style="margin-bottom:16px"><div class="progress-fill" style="width:35%;background:var(--green)"></div></div>
            <div style="display:flex;justify-content:space-between;margin-bottom:10px"><span style="color:var(--text2)">fpocket Overlap</span><span style="font-weight:700;color:var(--amber)">25.97%</span></div>
            <div class="progress-bar" style="margin-bottom:16px"><div class="progress-fill" style="width:26%;background:var(--amber)"></div></div>
            <div style="display:flex;justify-content:space-between;margin-bottom:10px"><span style="color:var(--text2)">False Positive Rate</span><span style="font-weight:700;color:var(--green)">13.11%</span></div>
            <div class="progress-bar" style="margin-bottom:16px"><div class="progress-fill" style="width:13%;background:var(--green)"></div></div>
            <div style="display:flex;justify-content:space-between;margin-bottom:6px"><span style="color:var(--text2)">MD Validated</span><span style="font-weight:700;color:var(--green)">1 protein</span></div>
          </div>
          <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border);font-size:12px;color:var(--text2)">
            <strong style="color:var(--green)">Phase 5.5 Strict Gate: PASS</strong> | Publication Freeze: PASS
          </div>
        </div>
      </div>
    </div>

    <!-- ANALYZE -->
    <div class="section" id="sec-analyze">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">New Analysis</h2>
      <div class="grid g2">
        <div class="card">
          <div class="card-title">Submit Protein</div>
          <form id="frm-analyze">
            <div style="margin-bottom:12px"><label>PDB ID</label><input id="inp-pdb" placeholder="e.g. 1CBS, 1AKE, 1TUP" required/></div>
            <div class="grid g2" style="margin-bottom:12px">
              <div><label>Type</label><select id="inp-type"><option value="full_analysis">Full Analysis</option><option value="quick_probe">Quick Probe</option></select></div>
              <div><label>NMA Frames</label><input id="inp-frames" type="number" value="20" min="5" max="200"/></div>
            </div>
            <div class="grid g2" style="margin-bottom:16px">
              <div><label>Profile</label><select id="inp-profile"><option value="default">Default</option><option value="enzyme">Enzyme</option><option value="ppi">PPI</option><option value="gpcr">GPCR</option></select></div>
              <div><label>Timeout (s)</label><input id="inp-timeout" type="number" value="120" min="10" max="600"/></div>
            </div>
            <button type="submit" class="btn btn-cyan" id="btn-submit">Start Analysis</button>
            <span id="submit-msg" style="margin-left:12px;font-size:13px;color:var(--text2)"></span>
          </form>
        </div>
        <div class="card">
          <div class="card-title">Progress</div>
          <div style="display:flex;justify-content:space-between;margin-bottom:4px"><span id="prog-label">Idle</span><span id="prog-pct">0%</span></div>
          <div class="progress-bar"><div class="progress-fill" id="prog-fill" style="width:0%"></div></div>
          <div class="log-area" id="log-area">Ready.</div>
        </div>
      </div>
      <div class="card" id="result-card" style="display:none">
        <div class="card-title">Results</div>
        <div class="grid g4" id="result-kpis"></div>
        <table style="margin-top:12px"><thead><tr><th>Rank</th><th>Volume</th><th>Bio-Score</th><th>Class</th><th>Hydro%</th></tr></thead><tbody id="result-rows"></tbody></table>
        <button class="btn btn-ghost" id="btn-download" style="margin-top:12px">Download JSON</button>
        <button class="btn btn-cyan" id="btn-3d" style="margin-top:12px;margin-left:8px" onclick="show3D()">View 3D Structure</button>
      </div>
      <div class="card" id="viewer-card" style="display:none">
        <div class="card-title">3D Protein Structure & Discovered Pockets</div>
        <div id="viewer-3d" style="width:100%;height:500px;background:#0a0d14;border-radius:8px;position:relative"></div>
        <div style="margin-top:8px;display:flex;gap:16px;font-size:12px;color:var(--text2)">
          <span><span style="display:inline-block;width:12px;height:12px;background:#10b981;border-radius:50%;vertical-align:middle"></span> High druggability</span>
          <span><span style="display:inline-block;width:12px;height:12px;background:#fbbf24;border-radius:50%;vertical-align:middle"></span> Medium</span>
          <span><span style="display:inline-block;width:12px;height:12px;background:#f87171;border-radius:50%;vertical-align:middle"></span> Low</span>
          <span>Drag to rotate | Scroll to zoom</span>
        </div>
      </div>
    </div>

    <!-- JOBS -->
    <div class="section" id="sec-jobs">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">Job History</h2>
      <div class="card">
        <div class="card-header"><div class="card-title">All Jobs</div><button class="btn btn-ghost" onclick="loadJobs()">Refresh</button></div>
        <table><thead><tr><th>ID</th><th>PDB</th><th>Type</th><th>Status</th><th>Created</th><th></th></tr></thead><tbody id="jobs-rows"></tbody></table>
        <p id="jobs-empty" style="text-align:center;padding:24px;color:var(--text2)">No jobs yet.</p>
      </div>
    </div>

    <!-- ATLAS -->
    <div class="section" id="sec-atlas">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">Pocket Atlas</h2>
      <div class="card">
        <div class="card-header">
          <div class="card-title">Browse Pockets</div>
          <div style="display:flex;gap:8px">
            <select id="atlas-cls" style="width:auto"><option value="">All</option><option value="high">High</option><option value="medium">Medium</option></select>
            <select id="atlas-lim" style="width:auto"><option value="15">15</option><option value="25">25</option><option value="50">50</option></select>
            <button class="btn btn-ghost" onclick="loadAtlas()">Refresh</button>
          </div>
        </div>
        <table><thead><tr><th>PDB</th><th>Pocket</th><th>Score</th><th>Volume</th><th>Class</th><th>Profile</th></tr></thead><tbody id="atlas-rows"></tbody></table>
        <p id="atlas-empty" style="text-align:center;padding:24px;color:var(--text2)">No data. Run analyses to populate.</p>
        <div style="margin-top:12px;display:flex;gap:8px">
          <a href="/export/pockets.csv?druggable_only=true" class="btn btn-ghost" style="text-decoration:none">Export CSV</a>
        </div>
      </div>
      <div class="card" id="protein-detail" style="display:none">
        <div class="card-header">
          <div class="card-title" id="detail-title">Protein Detail</div>
          <button class="btn btn-ghost" onclick="$('#protein-detail').style.display='none'">Close</button>
        </div>
        <div class="grid g4" id="detail-kpis"></div>
        <table style="margin-top:12px"><thead><tr><th>Pocket</th><th>Score</th><th>Volume</th><th>Class</th><th>Hydro%</th><th>Enclosure</th><th>Depth</th></tr></thead><tbody id="detail-rows"></tbody></table>
      </div>
    </div>

    <!-- REPORT -->
    <div class="section" id="sec-report">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">Discovery Reports</h2>
      <div class="card">
        <div class="card-title">Generate Report</div>
        <p style="color:var(--text2);margin-bottom:16px">Create a summary of BioVoid discoveries for a specific protein.</p>
        <div class="grid g2">
          <div><label>PDB ID</label><input id="rpt-pdb" placeholder="e.g. 1CBS"/></div>
          <div style="display:flex;align-items:end"><button class="btn btn-cyan" onclick="genReport()">Generate</button></div>
        </div>
        <div id="rpt-out" style="margin-top:20px;display:none"></div>
      </div>
    </div>

    <!-- BENCHMARK -->
    <div class="section" id="sec-benchmark">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">Scientific Benchmark</h2>
      <div class="card">
        <div class="card-title">Known Cryptic Pockets Test Set (20 proteins)</div>
        <p style="color:var(--text2);margin-bottom:16px">Validated against literature: Meller et al. 2023, CryptoSite, PocketMiner, Bowman Lab</p>
        <div class="grid g3" style="margin-bottom:16px">
          <div class="kpi"><div class="kpi-val" style="color:var(--green)">35.0%</div><div class="kpi-label">Recall (7/20)</div></div>
          <div class="kpi"><div class="kpi-val" style="color:var(--amber)">25.97%</div><div class="kpi-label">fpocket Overlap</div></div>
          <div class="kpi"><div class="kpi-val" style="color:var(--green)">13.11%</div><div class="kpi-label">False Positive Rate</div></div>
        </div>
        <table>
          <thead><tr><th>PDB</th><th>Protein</th><th>Type</th><th>Ligand</th><th>Status</th></tr></thead>
          <tbody id="bench-table"></tbody>
        </table>
      </div>
      <div class="card">
        <div class="card-title">Competitive Landscape</div>
        <table>
          <thead><tr><th>Method</th><th>Approach</th><th>Speed</th><th>Cryptic?</th><th>Cost</th></tr></thead>
          <tbody>
            <tr><td><strong style="color:var(--cyan)">BioVoid</strong></td><td>NMA + Voronoi + ML</td><td>Minutes</td><td style="color:var(--green)">YES</td><td>Low</td></tr>
            <tr><td>fpocket</td><td>Voronoi (static)</td><td>Seconds</td><td style="color:var(--red)">NO</td><td>Very Low</td></tr>
            <tr><td>PocketMiner</td><td>GNN</td><td>Seconds</td><td style="color:var(--green)">YES</td><td>Low (GPU)</td></tr>
            <tr><td>MD Simulation</td><td>Full dynamics</td><td>Days-Weeks</td><td style="color:var(--green)">YES</td><td>Very High</td></tr>
            <tr><td>AlphaFold+MD</td><td>Ensemble+MD</td><td>Hours-Days</td><td style="color:var(--green)">YES</td><td>High</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- GALLERY -->
    <div class="section" id="sec-gallery">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">Visualization Gallery</h2>
      <div id="gallery-grid" class="grid g3"></div>
      <p id="gallery-empty" style="text-align:center;padding:40px;color:var(--text2)">Loading artifacts...</p>
    </div>

    <!-- SYSTEM -->
    <div class="section" id="sec-system">
      <h2 style="font-size:24px;font-weight:700;margin-bottom:20px">System Info</h2>
      <div class="grid g3" id="sys-kpis"></div>
      <div class="card" style="margin-top:16px">
        <div class="card-title">About BioVoid</div>
        <p style="color:var(--text2);line-height:1.8">
          BioVoid is a cryptic pocket discovery pipeline that uses Normal Mode Analysis (NMA) to simulate protein dynamics,
          Voronoi tessellation to detect hidden cavities, and AI-powered scoring to rank druggability.
          Unlike traditional tools like fpocket that only analyze static structures, BioVoid explores the conformational space
          to find pockets that open transiently during protein motion.
        </p>
      </div>
    </div>

  </main>
</div>

<script>
const $=s=>document.querySelector(s);const $$=s=>document.querySelectorAll(s);
const PL={paper_bgcolor:'rgba(0,0,0,0)',plot_bgcolor:'rgba(26,30,42,0.6)',font:{color:'#7b83a0',family:'Inter',size:12},margin:{l:40,r:16,t:24,b:36},xaxis:{gridcolor:'#232836'},yaxis:{gridcolor:'#232836'}};

// NAV
$$('.nav-item').forEach(n=>{n.addEventListener('click',()=>{
  $$('.nav-item').forEach(x=>x.classList.remove('active'));
  $$('.section').forEach(x=>x.classList.remove('active'));
  n.classList.add('active');
  $(`#sec-${n.dataset.section}`).classList.add('active');
  if(n.dataset.section==='dashboard')loadDashboard();
  if(n.dataset.section==='jobs')loadJobs();
  if(n.dataset.section==='atlas')loadAtlas();
  if(n.dataset.section==='benchmark')loadBenchmark();
  if(n.dataset.section==='gallery')loadGallery();
  if(n.dataset.section==='system')loadSystem();
})});

let activeJob=null;

// DASHBOARD
async function loadDashboard(){
  try{
    const r=await(await fetch('/atlas/overview')).json();
    const s=r.summary||{};
    $('#kpi-proteins').textContent=s.total_proteins||0;
    $('#kpi-pockets').textContent=s.total_pockets||0;
    $('#kpi-druggable').textContent=s.druggable_pockets||0;
    $('#kpi-elite').textContent=s.elite_pockets||0;

    const pr=await(await fetch('/atlas/pockets?limit=25&druggable_only=true')).json();
    const items=pr.items||[];
    const cd=r.class_distribution||{};

    // Recent table
    const tb=$('#dash-recent');tb.innerHTML='';
    items.slice(0,8).forEach(p=>{
      tb.innerHTML+=`<tr><td>${p.pdb_id}</td><td>#${p.pocket_id}</td><td>${(p.bio_score||0).toFixed(4)}</td><td>${(p.volume||0).toFixed(0)}</td><td><span class="badge b-${p.druggability_class||'low'}">${p.druggability_class||'low'}</span></td></tr>`;
    });

    // Charts
    if(items.length>0&&typeof Plotly!=='undefined'){
      const sc=items.map(i=>i.bio_score||0),vo=items.map(i=>i.volume||0),cl=items.map(i=>i.druggability_class||'low');
      const cc={high:'#10b981',medium:'#fbbf24',low:'#f87171'};
      Plotly.newPlot('ch-hist',[{x:sc,type:'histogram',nbinsx:20,marker:{color:'#22d3ee',opacity:.8}}],{...PL,xaxis:{...PL.xaxis,title:'Bio-Score'},yaxis:{...PL.yaxis,title:'Count'}},{responsive:true});
      Plotly.newPlot('ch-scatter',[{x:vo,y:sc,mode:'markers',type:'scatter',marker:{color:cl.map(c=>cc[c]||'#666'),size:9,opacity:.7},text:items.map(i=>`${i.pdb_id} #${i.pocket_id}`)}],{...PL,xaxis:{...PL.xaxis,title:'Volume (A³)'},yaxis:{...PL.yaxis,title:'Bio-Score'}},{responsive:true});
      Plotly.newPlot('ch-pie',[{labels:Object.keys(cd),values:Object.values(cd),type:'pie',hole:.45,marker:{colors:['#10b981','#fbbf24','#f87171']},textfont:{color:'#e2e6ef'}}],{...PL,showlegend:true,legend:{font:{color:'#7b83a0'}}},{responsive:true});
      const ps={};items.forEach(i=>{if(!ps[i.pdb_id]||i.bio_score>ps[i.pdb_id])ps[i.pdb_id]=i.bio_score});
      const top=Object.entries(ps).sort((a,b)=>b[1]-a[1]).slice(0,10);
      Plotly.newPlot('ch-bar',[{x:top.map(t=>t[0]),y:top.map(t=>t[1]),type:'bar',marker:{color:'#06b6d4'}}],{...PL,xaxis:{...PL.xaxis,title:'Protein'},yaxis:{...PL.yaxis,title:'Top Score'}},{responsive:true});
    }
  }catch(e){console.error(e)}
}

// ANALYZE
$('#frm-analyze').addEventListener('submit',async e=>{
  e.preventDefault();
  const pdb=$('#inp-pdb').value.trim();if(!pdb)return;
  const key=`bv_${pdb}_${Date.now()}`;
  const body={job_type:$('#inp-type').value,input:{pdb_id:pdb},options:{n_frames:+$('#inp-frames').value,profile:$('#inp-profile').value,timeout_seconds:+$('#inp-timeout').value}};
  try{
    $('#btn-submit').disabled=true;
    const r=await(await fetch('/jobs',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)})).json();
    if(r.error){$('#submit-msg').textContent=r.error.message;$('#btn-submit').disabled=false;return}
    activeJob=r.job_id;$('#submit-msg').textContent=`Job: ${r.job_id.slice(0,8)}...`;
    log(`Submitted ${pdb} (${body.job_type})`);
    pollJob(r.job_id);
  }catch(err){$('#submit-msg').textContent=err.message;$('#btn-submit').disabled=false}
});
function log(m){const a=$('#log-area');a.textContent+='\n['+new Date().toLocaleTimeString()+'] '+m;a.scrollTop=a.scrollHeight}
function setProg(p,l){$('#prog-fill').style.width=p+'%';$('#prog-pct').textContent=p+'%';if(l)$('#prog-label').textContent=l}
async function pollJob(id){
  const iv=setInterval(async()=>{
    try{const r=await(await fetch('/jobs/'+id)).json();
      if(r.status==='running'){setProg(50,'Running...');log('Running...')}
      if(r.status==='succeeded'){clearInterval(iv);setProg(100,'Complete');log('Done!');showResult(r);$('#btn-submit').disabled=false}
      if(r.status==='failed'){clearInterval(iv);setProg(100,'Failed');log('Failed: '+(r.error?.message||''));$('#btn-submit').disabled=false}
    }catch(e){clearInterval(iv)}
  },1500);
}
function showResult(data){
  const r=data.result||{};
  const cavities=r.cavities||[];
  $('#result-kpis').innerHTML=`
    <div class="kpi"><div class="kpi-val">${r.total_cavities||0}</div><div class="kpi-label">Total Cavities</div></div>
    <div class="kpi"><div class="kpi-val">${r.druggable_cavities||0}</div><div class="kpi-label">Druggable</div></div>
    <div class="kpi"><div class="kpi-val">${r.high_druggability||0}</div><div class="kpi-label">High Score</div></div>
    <div class="kpi"><div class="kpi-val">${(r.runtime_seconds||0).toFixed(1)}s</div><div class="kpi-label">Runtime</div></div>`;

  const tb=$('#result-rows');tb.innerHTML='';
  cavities.forEach(c=>{
    const cl=c.druggability_class||'low';
    const sc=c.score_components||{};
    const conf=c.confidence||{};
    tb.innerHTML+=`<tr>
      <td><strong>#${c.rank}</strong></td>
      <td>${(c.volume||0).toFixed(0)} A³</td>
      <td><strong style="color:var(--cyan)">${(c.bio_score||0).toFixed(4)}</strong></td>
      <td><span class="badge b-${cl}">${cl}</span></td>
      <td>${((c.hydrophobic_ratio||0)*100).toFixed(0)}%</td>
    </tr>
    <tr style="background:rgba(34,211,238,.03)"><td colspan="5" style="padding:4px 12px;border:none">
      <div style="display:flex;gap:16px;font-size:11px;color:var(--text2)">
        <span>Vol: ${(sc.volume_score||0).toFixed(2)}</span>
        <span>Hydro: ${(sc.hydrophobicity_score||0).toFixed(2)}</span>
        <span>Encl: ${(sc.enclosure_score||0).toFixed(2)}</span>
        <span>Depth: ${(sc.depth_score||0).toFixed(2)}</span>
        ${sc.sphericity?`<span>Spher: ${sc.sphericity.toFixed(2)}</span>`:''}
        ${conf.overall?`<span style="color:var(--green)">Conf: ${(conf.overall*100).toFixed(0)}%</span>`:''}
      </div>
    </td></tr>`;
  });

  // Score chart for result
  if(cavities.length>0&&typeof Plotly!=='undefined'){
    const ranks=cavities.map(c=>c.rank);
    const scores=cavities.map(c=>c.bio_score||0);
    const cls=cavities.map(c=>c.druggability_class||'low');
    const cc={high:'#10b981',medium:'#fbbf24',low:'#f87171'};
    const chartGrid=document.createElement('div');
    chartGrid.className='grid g2';chartGrid.style.marginTop='12px';
    const ch1=document.createElement('div');ch1.style.height='250px';
    const ch2=document.createElement('div');ch2.style.height='250px';
    chartGrid.appendChild(ch1);chartGrid.appendChild(ch2);
    $('#result-card').appendChild(chartGrid);

    Plotly.newPlot(ch1,[{x:ranks.map(r=>'#'+r),y:scores,type:'bar',marker:{color:cls.map(c=>cc[c]||'#f87171'),opacity:0.85}}],{...PL,height:250,title:{text:'Pocket Scores',font:{size:13,color:'#22d3ee'}},xaxis:{...PL.xaxis,title:'Rank'},yaxis:{...PL.yaxis,title:'Bio-Score'}},{responsive:true});

    const vols=cavities.map(c=>c.volume||0);
    Plotly.newPlot(ch2,[{x:vols,y:scores,mode:'markers',type:'scatter',marker:{color:cls.map(c=>cc[c]||'#f87171'),size:vols.map(v=>Math.max(6,Math.min(20,v/80))),opacity:0.8},text:ranks.map(r=>'Pocket #'+r)}],{...PL,height:250,title:{text:'Volume vs Score',font:{size:13,color:'#22d3ee'}},xaxis:{...PL.xaxis,title:'Volume (A³)'},yaxis:{...PL.yaxis,title:'Bio-Score'}},{responsive:true});
  }

  $('#result-card').style.display='block';
  $('#btn-download').onclick=()=>location.href='/jobs/'+activeJob+'/result';
}

// JOBS
async function loadJobs(){
  try{const r=await(await fetch('/jobs?limit=50')).json();const j=r.jobs||[];
    const tb=$('#jobs-rows');tb.innerHTML='';
    if(!j.length){$('#jobs-empty').style.display='block';return}
    $('#jobs-empty').style.display='none';
    j.forEach(x=>{const s=x.status||'unknown';
      tb.innerHTML+=`<tr><td style="font-family:monospace;font-size:11px">${x.job_id.slice(0,10)}</td><td>${x.pdb_id}</td><td>${x.job_type}</td><td><span class="badge b-${s}">${s}</span></td><td style="font-size:12px">${new Date(x.created_at_utc).toLocaleString()}</td><td>${s==='queued'?`<button class="btn btn-ghost" style="padding:4px 8px;font-size:11px" onclick="cancelJ('${x.job_id}')">Cancel</button>`:''}</td></tr>`});
  }catch(e){}}
async function cancelJ(id){await fetch('/jobs/'+id+'/cancel',{method:'POST'});loadJobs()}

// ATLAS
async function loadAtlas(){
  try{const cls=$('#atlas-cls').value;const lim=$('#atlas-lim').value;
    let u=`/atlas/pockets?limit=${lim}&druggable_only=true`;if(cls)u+=`&druggability_class=${cls}`;
    const r=await(await fetch(u)).json();const items=r.items||[];
    const tb=$('#atlas-rows');tb.innerHTML='';
    if(!items.length){$('#atlas-empty').style.display='block';return}
    $('#atlas-empty').style.display='none';
    items.forEach(p=>{const c=p.druggability_class||'low';
      tb.innerHTML+=`<tr><td><a href="#" onclick="showProteinDetail('${p.pdb_id}');return false" style="color:var(--cyan);text-decoration:none;font-weight:600">${p.pdb_id}</a></td><td>#${p.pocket_id}</td><td>${(p.bio_score||0).toFixed(4)}</td><td>${(p.volume||0).toFixed(0)}</td><td><span class="badge b-${c}">${c}</span></td><td>${p.profile_used||'-'}</td></tr>`});
  }catch(e){}}
$('#atlas-cls').addEventListener('change',loadAtlas);
$('#atlas-lim').addEventListener('change',loadAtlas);

// REPORT
async function genReport(){
  const pdb=$('#rpt-pdb').value.trim();if(!pdb)return;
  const out=$('#rpt-out');out.style.display='block';out.innerHTML='<p style="color:var(--text2)">Loading...</p>';
  try{
    const ov=await(await fetch('/atlas/overview')).json();
    const pk=await(await fetch(`/atlas/pockets?limit=50&druggable_only=false`)).json();
    const items=(pk.items||[]).filter(p=>p.pdb_id===pdb.toUpperCase());
    let h=`<div class="card"><h3 style="color:var(--cyan);margin-bottom:8px">BioVoid Report: ${pdb.toUpperCase()}</h3>`;
    h+=`<p style="color:var(--text2);font-size:12px">Generated ${new Date().toISOString().slice(0,19)}</p>`;
    if(items.length){h+=`<table style="margin-top:12px"><thead><tr><th>Pocket</th><th>Score</th><th>Volume</th><th>Class</th></tr></thead><tbody>`;
      items.forEach(p=>{h+=`<tr><td>#${p.pocket_id}</td><td>${p.bio_score.toFixed(4)}</td><td>${p.volume.toFixed(0)}</td><td><span class="badge b-${p.druggability_class}">${p.druggability_class}</span></td></tr>`});
      h+='</tbody></table>'
    }else{h+=`<p style="margin-top:12px;color:var(--text2)">No pockets found. Run an analysis for ${pdb.toUpperCase()} first.</p>`}
    h+=`<h4 style="margin-top:20px;color:var(--text)">Atlas Context</h4><p style="color:var(--text2)">Proteins: ${ov.summary?.total_proteins||0} | Pockets: ${ov.summary?.total_pockets||0} | Druggable: ${ov.summary?.druggable_pockets||0}</p></div>`;
    out.innerHTML=h;
  }catch(e){out.innerHTML=`<p style="color:var(--red)">${e.message}</p>`}}

// SYSTEM
async function loadSystem(){
  try{const r=await(await fetch('/ops/metrics')).json();const rd=await(await fetch('/ready')).json();
    $('#sys-kpis').innerHTML=`
      <div class="kpi"><div class="kpi-val">${rd.status}</div><div class="kpi-label">Status</div></div>
      <div class="kpi"><div class="kpi-val">${r.submitted_jobs||0}</div><div class="kpi-label">Total Jobs</div></div>
      <div class="kpi"><div class="kpi-val">${(r.uptime_seconds/3600).toFixed(1)}h</div><div class="kpi-label">Uptime</div></div>`;
  }catch(e){}}

// HEALTH
async function healthCheck(){try{const r=await(await fetch('/health')).json();$('#health-dot').className='status-dot '+(r.status==='ok'?'dot-ok':'dot-err');$('#health-text').textContent=r.status==='ok'?'Online':'Offline'}catch(e){$('#health-dot').className='status-dot dot-err';$('#health-text').textContent='Offline'}}
setInterval(healthCheck,30000);healthCheck();

// 3D VIEWER
async function show3D(){
  if(!activeJob)return;
  try{
    const jobData=await(await fetch('/jobs/'+activeJob)).json();
    const pdbId=(jobData.result?.pdb_id||jobData.request?.input?.pdb_id||'').toLowerCase();
    if(!pdbId){log('No PDB ID found');return}

    $('#viewer-card').style.display='block';
    const viewerDiv=$('#viewer-3d');
    viewerDiv.innerHTML='<p style="color:var(--text2);padding:20px">Loading 3D structure...</p>';

    // Get pockets from job result directly (more reliable than atlas DB)
    let pockets=[];
    const cavities=jobData.result?.cavities||[];
    if(cavities.length>0){
      pockets=cavities.map(c=>({
        id:c.id||0,
        center:c.center||[0,0,0],
        radius:c.radius_geom||3,
        bio_score:c.bio_score||0,
        volume:c.volume||0,
        druggability_class:c.druggability_class||'low',
        druggable:c.druggable||false,
      }));
    }else{
      const pocketRes=await(await fetch(`/protein/${pdbId}/pockets`)).json();
      pockets=pocketRes.pockets||[];
    }

    // Try 3Dmol.js first
    if(typeof $3Dmol!=='undefined'&&window._3dmol_loaded){
      const pdbRes=await fetch(`/protein/${pdbId}/structure`);
      if(pdbRes.ok){
        const pdbData=await pdbRes.text();
        viewerDiv.innerHTML='';
        const viewer=$3Dmol.createViewer(viewerDiv,{backgroundColor:'#0a0d14'});
        viewer.addModel(pdbData,'pdb');
        viewer.setStyle({},{cartoon:{color:'#4a90d9',opacity:0.85}});
        const pocketColors={high:'#10b981',medium:'#fbbf24',low:'#f87171'};
        pockets.forEach(p=>{
          const c=p.center;const color=pocketColors[p.druggability_class]||'#f87171';
          viewer.addSphere({center:{x:c[0],y:c[1],z:c[2]},radius:p.radius||3,color:color,opacity:0.6});
          viewer.addLabel('P'+p.id+' ('+p.bio_score.toFixed(2)+')',{position:{x:c[0],y:c[1]+(p.radius||3)+1,z:c[2]},backgroundColor:color,fontColor:'#fff',fontSize:10,backgroundOpacity:0.8});
        });
        viewer.zoomTo();viewer.render();viewer.zoom(0.9);viewer.spin('y',0.5);
        log('3Dmol view: '+pdbId.toUpperCase()+' with '+pockets.length+' pockets');
        return;
      }
    }

    // Fallback: Plotly 3D scatter
    log('Using Plotly 3D fallback');
    viewerDiv.innerHTML='';
    const traces=[];

    if(pockets.length>0){
      const cc={high:'#10b981',medium:'#fbbf24',low:'#f87171'};
      const x=[],y=[],z=[],colors=[],sizes=[],texts=[];
      pockets.forEach(p=>{
        x.push(p.center[0]);y.push(p.center[1]);z.push(p.center[2]);
        colors.push(cc[p.druggability_class]||'#f87171');
        sizes.push(Math.max(8,Math.min(25,(p.volume||100)/30)));
        texts.push('P'+p.id+'<br>Score: '+p.bio_score.toFixed(3)+'<br>Vol: '+(p.volume||0).toFixed(0)+'<br>Class: '+p.druggability_class);
      });
      traces.push({x,y,z,mode:'markers',type:'scatter3d',marker:{color:colors,size:sizes,opacity:0.8,line:{color:'#fff',width:1}},text:texts,hoverinfo:'text',name:'Pockets'});
    }

    Plotly.newPlot(viewerDiv,traces,{
      paper_bgcolor:'#0a0d14',plot_bgcolor:'#0a0d14',
      scene:{xaxis:{title:'X (A)',gridcolor:'#1a1e2a',color:'#7b83a0'},yaxis:{title:'Y (A)',gridcolor:'#1a1e2a',color:'#7b83a0'},zaxis:{title:'Z (A)',gridcolor:'#1a1e2a',color:'#7b83a0'},bgcolor:'#0a0d14',aspectmode:'data'},
      font:{color:'#7b83a0'},margin:{l:0,r:0,t:30,b:0},
      title:{text:pdbId.toUpperCase()+' — Discovered Pockets (3D)',font:{size:14,color:'#22d3ee'}},
    },{responsive:true});
    log('Plotly 3D: '+pdbId.toUpperCase()+' with '+pockets.length+' pockets');
  }catch(e){log('3D error: '+e.message)}
}

// PROTEIN DETAIL
async function showProteinDetail(pdbId){
  try{
    const r=await(await fetch('/protein/'+pdbId+'/detail')).json();
    $('#detail-title').textContent=pdbId+' — Protein Detail';
    $('#detail-kpis').innerHTML=`
      <div class="kpi"><div class="kpi-val">${r.total_pockets||0}</div><div class="kpi-label">Pockets</div></div>
      <div class="kpi"><div class="kpi-val">${r.druggable_pockets||0}</div><div class="kpi-label">Druggable</div></div>
      <div class="kpi"><div class="kpi-val">${(r.max_bio_score||0).toFixed(3)}</div><div class="kpi-label">Top Score</div></div>
      <div class="kpi"><div class="kpi-val">${(r.avg_volume||0).toFixed(0)}</div><div class="kpi-label">Avg Volume</div></div>`;
    const tb=$('#detail-rows');tb.innerHTML='';
    (r.pockets||[]).forEach(p=>{
      tb.innerHTML+=`<tr>
        <td>#${p.pocket_id}</td>
        <td><strong style="color:var(--cyan)">${(p.bio_score||0).toFixed(4)}</strong></td>
        <td>${(p.volume||0).toFixed(0)} A³</td>
        <td><span class="badge b-${p.druggability_class||'low'}">${p.druggability_class||'low'}</span></td>
        <td>${((p.hydrophobic_ratio||0)*100).toFixed(0)}%</td>
        <td>${(p.enclosure_score||0).toFixed(2)}</td>
        <td>${(p.depth_score||0).toFixed(2)}</td>
      </tr>`;
    });
    $('#protein-detail').style.display='block';
    $('#protein-detail').scrollIntoView({behavior:'smooth'});
  }catch(e){console.error(e)}
}

// BENCHMARK
async function loadBenchmark(){
  try{
    const r=await(await fetch('/benchmark/known-pockets')).json();
    const tb=$('#bench-table');tb.innerHTML='';
    (r.pockets||[]).forEach(p=>{
      const typeColors={side_chain_flip:'var(--cyan)',loop_rearrangement:'var(--amber)',helix_displacement:'var(--purple)',domain_motion:'var(--green)'};
      const tc=typeColors[p.pocket_type]||'var(--text2)';
      tb.innerHTML+=`<tr>
        <td><strong>${p.pdb_id}</strong></td>
        <td>${p.name}</td>
        <td><span style="color:${tc}">${(p.pocket_type||'').replace(/_/g,' ')}</span></td>
        <td style="font-size:12px">${p.known_ligand||'-'}</td>
        <td><span class="badge b-queued">test case</span></td>
      </tr>`;
    });
  }catch(e){console.error(e)}
}

// GALLERY
async function loadGallery(){
  try{
    const r=await(await fetch('/artifacts')).json();
    const items=r.artifacts||[];
    const grid=$('#gallery-grid');grid.innerHTML='';
    if(!items.length){$('#gallery-empty').textContent='No visualization artifacts found.';return}
    $('#gallery-empty').style.display='none';
    items.forEach(a=>{
      if(a.type==='png'||a.type==='jpg'){
        grid.innerHTML+=`<div class="card" style="padding:0;overflow:hidden">
          <img src="${a.url}" style="width:100%;display:block;border-radius:var(--r) var(--r) 0 0" loading="lazy" alt="${a.name}"/>
          <div style="padding:12px"><div style="font-size:13px;font-weight:600">${a.name}</div><div style="font-size:11px;color:var(--text2)">${a.size_kb} KB</div></div>
        </div>`;
      }else if(a.type==='html'){
        grid.innerHTML+=`<div class="card" style="text-align:center;padding:24px">
          <div style="font-size:36px;margin-bottom:8px">🧬</div>
          <div style="font-size:14px;font-weight:600">${a.name}</div>
          <div style="font-size:11px;color:var(--text2);margin-bottom:12px">${a.size_kb} KB</div>
          <a href="${a.url}" target="_blank" class="btn btn-ghost" style="text-decoration:none">Open Interactive View</a>
        </div>`;
      }
    });
  }catch(e){$('#gallery-empty').textContent='Error loading gallery.'}
}

// NAV handler for gallery
const origNavHandler=$$('.nav-item')[0];

// INIT
loadDashboard();
</script>
</body>
</html>"""
