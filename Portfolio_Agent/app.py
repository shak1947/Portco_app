"""
Portfolio Analysis Agent — Web UI
Run:  py app.py   (from Portfolio_Agent/)
Open: http://localhost:5000
"""

import os, json, threading, queue
from flask import Flask, Response, jsonify, send_file, request, render_template_string
from dotenv import load_dotenv
from agent import PortfolioSession, list_excel_files, OUTPUT_FILE

load_dotenv()
app = Flask(__name__)

_last_excel_path = [None]  # mutable so the SSE thread can update it


def _run_analysis(selected_files, q):
    def callback(event):
        if event.get("type") == "results":
            _last_excel_path[0] = event.get("excel_path")
        q.put(event)

    try:
        session = PortfolioSession(status_callback=callback)
        session.run(selected_files)
    except Exception as e:
        q.put({"type": "error", "msg": str(e)})
    finally:
        q.put(None)  # sentinel → close stream


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/files")
def api_files():
    files = list_excel_files()
    return jsonify({"files": files, "dir": os.getenv("PORTFOLIO_DIR", "")})


@app.route("/api/analyze")
def api_analyze():
    files_param = request.args.get("files", "")
    selected = [f.strip() for f in files_param.split(",") if f.strip()]
    if not selected:
        def _err():
            yield f"data: {json.dumps({'type':'error','msg':'No files selected.'})}\n\n"
        return Response(_err(), mimetype="text/event-stream")

    q = queue.Queue()
    threading.Thread(target=_run_analysis, args=(selected, q), daemon=True).start()

    def generate():
        while True:
            event = q.get()
            if event is None:
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                break
            yield f"data: {json.dumps(event)}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/download")
def api_download():
    path = _last_excel_path[0] or OUTPUT_FILE
    if not path or not os.path.exists(path):
        return "No report available yet. Run an analysis first.", 404
    return send_file(path, as_attachment=True, download_name="Portfolio_Summary.xlsx")


# ── HTML template ─────────────────────────────────────────────────────────────

HTML = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Portfolio Analysis Agent</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --navy:  #0D2137;
  --navy2: #0F1F3D;
  --blue:  #1565C0;
  --teal:  #006064;
  --gold:  #F9A825;
  --green: #2E7D32;
  --red:   #C62828;
  --amber: #E65100;
  --grey1: #F5F6F8;
  --grey2: #E8EAED;
  --grey3: #9E9E9E;
  --text:  #212121;
  --white: #FFFFFF;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Sora", sans-serif; background: var(--grey1); color: var(--text); min-height: 100vh; }

/* ── Header ── */
.header {
  height: 58px; background: var(--navy); display: flex; align-items: center;
  padding: 0 28px; gap: 14px; border-bottom: 2px solid var(--gold);
  position: sticky; top: 0; z-index: 100;
}
.header-logo {
  width: 34px; height: 34px; background: var(--gold); border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 18px; flex-shrink: 0;
}
.header-text { display: flex; flex-direction: column; }
.header-title { font-size: 15px; font-weight: 700; color: white; letter-spacing: -0.2px; }
.header-sub   { font-size: 10px; color: var(--grey3); letter-spacing: 0.8px; text-transform: uppercase; }
.header-spacer { flex: 1; }
.header-badge {
  font-family: "JetBrains Mono", monospace; font-size: 11px;
  color: var(--teal); background: rgba(0,96,100,0.15);
  border: 1px solid rgba(0,96,100,0.35); padding: 4px 12px; border-radius: 20px;
  transition: all 0.3s;
}
.header-badge.running { color: var(--gold); background: rgba(249,168,37,0.12); border-color: rgba(249,168,37,0.35); }
.header-badge.done    { color: var(--green); background: rgba(46,125,50,0.12); border-color: rgba(46,125,50,0.35); }

/* ── Panels ── */
.panel { display: none; }
.panel.active { display: block; }
.page { max-width: 1440px; margin: 0 auto; padding: 36px 28px 60px; }

/* ── Cards ── */
.card {
  background: white; border-radius: 16px;
  box-shadow: 0 2px 16px rgba(0,0,0,0.07); overflow: hidden;
}
.card-hd { background: var(--navy); padding: 22px 28px; }
.card-hd h2 { color: white; font-size: 18px; font-weight: 700; }
.card-hd p  { color: var(--grey3); font-size: 12px; margin-top: 5px; line-height: 1.5; }
.card-body  { padding: 28px; }
.card-foot  {
  padding: 16px 28px; border-top: 1px solid var(--grey2);
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}

/* ── File grid ── */
.file-grid {
  display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px; margin-bottom: 8px;
}
.file-item {
  display: flex; align-items: center; gap: 12px; padding: 13px 16px;
  border: 2px solid var(--grey2); border-radius: 10px;
  cursor: pointer; transition: all 0.18s; user-select: none;
}
.file-item:hover { border-color: var(--blue); background: rgba(21,101,192,0.04); }
.file-item.selected { border-color: var(--blue); background: rgba(21,101,192,0.07); }
.file-item input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; accent-color: var(--blue); }
.file-name { font-size: 13px; font-weight: 500; flex: 1; line-height: 1.3; }
.file-ext  { font-size: 10px; color: var(--grey3); font-family: "JetBrains Mono", monospace; }
.file-placeholder { color: var(--grey3); font-size: 13px; padding: 24px 0; text-align: center; }

/* ── Buttons ── */
.btn {
  padding: 10px 22px; border: none; border-radius: 10px;
  font-family: "Sora", sans-serif; font-size: 13px; font-weight: 600;
  cursor: pointer; transition: all 0.18s; white-space: nowrap;
}
.btn-primary  { background: var(--blue); color: white; }
.btn-primary:hover:not(:disabled) { background: #1256A7; transform: translateY(-1px); }
.btn-primary:disabled { background: var(--grey3); cursor: not-allowed; }
.btn-secondary { background: var(--grey2); color: var(--text); }
.btn-secondary:hover { background: #D5D8DF; }
.btn-ghost { background: none; border: 1.5px solid var(--grey2); color: var(--grey3); }
.btn-ghost:hover { border-color: var(--navy); color: var(--navy); }
.sel-count { font-size: 12px; color: var(--grey3); margin-left: auto; }

/* ── Progress ── */
.prog-header {
  display: flex; align-items: center; gap: 14px;
  padding: 18px 28px; border-bottom: 1px solid var(--grey2);
}
.spinner {
  width: 22px; height: 22px; border: 3px solid var(--grey2);
  border-top-color: var(--blue); border-radius: 50%;
  animation: spin 0.7s linear infinite; flex-shrink: 0;
}
.spinner.done { border-top-color: var(--green); animation: none; border-color: var(--green); }
@keyframes spin { to { transform: rotate(360deg); } }
.status-text { font-size: 14px; font-weight: 500; }
.prog-log {
  height: 380px; overflow-y: auto; padding: 16px 28px;
  font-family: "JetBrains Mono", monospace; font-size: 12px;
  display: flex; flex-direction: column; gap: 6px;
}
.log-row { display: flex; align-items: baseline; gap: 10px; }
.log-icon { font-size: 13px; flex-shrink: 0; width: 16px; text-align: center; }
.log-msg  { line-height: 1.4; }
.log-row.status  .log-msg { color: var(--grey3); }
.log-row.company .log-msg { color: var(--navy); font-weight: 600; font-family: "Sora", sans-serif; }
.log-row.company .log-icon { color: var(--teal); }
.log-row.comp    .log-msg  { color: var(--grey3); font-size: 11px; padding-left: 18px; }
.log-row.agent   .log-msg  { color: var(--text); font-family: "Sora", sans-serif; font-size: 12px; }
.log-row.error   .log-msg  { color: var(--red); }

/* ── Stats bar ── */
.stats-bar {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px; margin-bottom: 24px;
}
.stat-card { background: white; border-radius: 12px; padding: 20px 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
.stat-val   { font-size: 28px; font-weight: 700; color: var(--navy); font-family: "JetBrains Mono", monospace; }
.stat-label { font-size: 11px; color: var(--grey3); margin-top: 5px; text-transform: uppercase; letter-spacing: 0.8px; }

/* ── Tabs ── */
.tab-nav {
  display: flex; align-items: center; gap: 4px; background: white;
  padding: 8px 10px; border-radius: 14px 14px 0 0;
  border-bottom: 1px solid var(--grey2);
  box-shadow: 0 2px 8px rgba(0,0,0,0.05); flex-wrap: wrap;
}
.tab-btn {
  padding: 8px 16px; border: none; border-radius: 8px;
  font-family: "Sora", sans-serif; font-size: 12px; font-weight: 500;
  cursor: pointer; transition: all 0.18s; background: none; color: var(--grey3);
}
.tab-btn:hover  { background: var(--grey1); color: var(--text); }
.tab-btn.active { background: var(--blue); color: white; }
.tab-spacer { flex: 1; min-width: 8px; }
.download-link {
  padding: 8px 16px; background: var(--navy); color: white; border-radius: 8px;
  font-size: 12px; font-weight: 600; text-decoration: none;
  display: inline-flex; align-items: center; gap: 6px; transition: all 0.18s;
}
.download-link:hover { background: var(--blue); }
.rerun-btn {
  padding: 8px 14px; border: 1.5px solid var(--grey2); background: none;
  color: var(--grey3); border-radius: 8px; font-family: "Sora", sans-serif;
  font-size: 12px; cursor: pointer; transition: all 0.18s;
}
.rerun-btn:hover { border-color: var(--navy); color: var(--navy); }

/* ── Tab content ── */
.tab-wrap {
  background: white; border-radius: 0 0 16px 16px;
  overflow-x: auto; box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}
.tab-pane { display: none; }
.tab-pane.active { display: block; }

/* ── Dashboard table ── */
.dash-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.dash-table th {
  background: var(--navy); color: white; padding: 12px 18px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.4px; white-space: nowrap;
}
.dash-table th.co-hdr { background: var(--blue); text-align: center; min-width: 150px; }
.dash-table .sec-row td {
  background: var(--teal); color: white; font-weight: 700;
  font-size: 11px; letter-spacing: 0.8px; padding: 9px 18px; text-transform: uppercase;
}
.dash-table .data-row td { padding: 10px 18px; border-bottom: 1px solid var(--grey2); }
.dash-table .data-row:nth-child(even) td { background: var(--grey1); }
.dash-table .data-row:hover td { background: rgba(21,101,192,0.04); }
.dash-table .data-row:nth-child(even):hover td { background: rgba(21,101,192,0.06); }
td.metric-col { font-weight: 500; }
td.unit-col   { color: var(--grey3); font-size: 11px; font-style: italic; text-align: center !important; font-family: "JetBrains Mono", monospace; }
td.val-col    { text-align: right !important; font-family: "JetBrains Mono", monospace; white-space: nowrap; }
td.val-col.pos { color: var(--green); }
td.val-col.neg { color: var(--red); }
td.val-col.margin { color: var(--blue); }
td.val-col.np  { color: var(--grey3); font-style: italic; text-align: center !important; font-size: 11px; font-family: "Sora", sans-serif; }

/* ── General tables ── */
.gen-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.gen-table th {
  background: var(--blue); color: white; padding: 11px 18px;
  font-size: 11px; font-weight: 600; letter-spacing: 0.4px; text-align: left; white-space: nowrap;
}
.gen-table td { padding: 10px 18px; border-bottom: 1px solid var(--grey2); }
.gen-table tr:nth-child(even) td { background: var(--grey1); }
.gen-table tr:hover td { background: rgba(21,101,192,0.04); }
.gen-table .co-cell { font-weight: 700; color: var(--navy); }
.gen-table .num { font-family: "JetBrains Mono", monospace; text-align: right; }
.gen-table .pos { color: var(--green); }
.gen-table .neg { color: var(--red); }
.gen-table .np  { color: var(--grey3); font-style: italic; }
.gen-table .clean { color: var(--green); font-weight: 600; }
.gen-table .issue { color: var(--amber); font-weight: 600; }
.sector-pill {
  display: inline-block; padding: 2px 9px; border-radius: 10px;
  font-size: 10px; font-weight: 600; background: rgba(0,96,100,0.1); color: var(--teal);
  text-transform: uppercase; letter-spacing: 0.4px;
}

/* ── Comps sections ── */
.comp-block { border-top: 2px solid var(--grey2); }
.comp-block:first-child { border-top: none; }
.comp-block-hdr {
  background: rgba(21,101,192,0.05); padding: 13px 22px;
  font-weight: 700; font-size: 13px; color: var(--navy);
  display: flex; align-items: center; gap: 12px;
}
.median-row td { background: var(--grey2) !important; font-weight: 700; }
.median-row .lbl { color: var(--teal); font-family: "JetBrains Mono", monospace; }
.median-row .num { color: var(--teal) !important; font-family: "JetBrains Mono", monospace; }

/* ── Empty state ── */
.empty { text-align: center; padding: 60px 24px; color: var(--grey3); font-size: 13px; }
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="header-logo">📊</div>
  <div class="header-text">
    <div class="header-title">Portfolio Analysis Agent</div>
    <div class="header-sub">Private Equity Intelligence</div>
  </div>
  <div class="header-spacer"></div>
  <div class="header-badge" id="hdr-badge">Ready</div>
</div>

<!-- ── SETUP PANEL ── -->
<div class="panel active" id="panel-setup">
  <div class="page">
    <div class="card">
      <div class="card-hd">
        <h2>Select Portfolio Company Files</h2>
        <p id="dir-label">Loading available files…</p>
      </div>
      <div class="card-body">
        <div class="file-grid" id="file-grid">
          <div class="file-placeholder">Scanning portfolio directory…</div>
        </div>
      </div>
      <div class="card-foot">
        <button class="btn btn-secondary" onclick="selectAll()">Select All</button>
        <button class="btn btn-ghost"     onclick="clearSel()">Clear</button>
        <span class="sel-count" id="sel-count">0 selected</span>
        <button class="btn btn-primary" id="run-btn" onclick="runAnalysis()" disabled>
          Run Analysis
        </button>
      </div>
    </div>
  </div>
</div>

<!-- ── PROGRESS PANEL ── -->
<div class="panel" id="panel-progress">
  <div class="page">
    <div class="card">
      <div class="prog-header">
        <div class="spinner" id="spin"></div>
        <span class="status-text" id="status-text">Starting…</span>
      </div>
      <div class="prog-log" id="prog-log"></div>
    </div>
  </div>
</div>

<!-- ── RESULTS PANEL ── -->
<div class="panel" id="panel-results">
  <div class="page">
    <div class="stats-bar" id="stats-bar"></div>

    <div class="tab-nav" id="tab-nav">
      <button class="tab-btn active" onclick="switchTab('dashboard')">Executive Dashboard</button>
      <button class="tab-btn"        onclick="switchTab('comps')">Market Comps</button>
      <button class="tab-btn"        onclick="switchTab('kpis')">Company KPIs</button>
      <button class="tab-btn"        onclick="switchTab('flags')">Data Flags</button>
      <button class="tab-btn"        onclick="switchTab('labels')">Reporting Labels</button>
      <div class="tab-spacer"></div>
      <a href="/api/download" class="download-link" target="_blank">⬇ Download Excel</a>
      <button class="rerun-btn" onclick="goSetup()">Re-analyze</button>
    </div>

    <div class="tab-wrap">
      <div class="tab-pane active" id="tab-dashboard"></div>
      <div class="tab-pane"        id="tab-comps"></div>
      <div class="tab-pane"        id="tab-kpis"></div>
      <div class="tab-pane"        id="tab-flags"></div>
      <div class="tab-pane"        id="tab-labels"></div>
    </div>
  </div>
</div>

<script>
// ── State ─────────────────────────────────────────────────────────────────────
let selected = new Set();
let es = null;
let lastResults = null;

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', loadFiles);

async function loadFiles() {
  try {
    const r = await fetch('/api/files');
    const d = await r.json();
    document.getElementById('dir-label').textContent =
      `${d.files.length} file${d.files.length !== 1 ? 's' : ''} found in: ${d.dir}`;
    buildFileGrid(d.files);
  } catch(e) {
    document.getElementById('file-grid').innerHTML =
      `<div class="file-placeholder">Error loading files: ${esc(e.message)}</div>`;
  }
}

function buildFileGrid(files) {
  const grid = document.getElementById('file-grid');
  if (!files.length) {
    grid.innerHTML = '<div class="file-placeholder">No Excel files found in the portfolio directory.</div>';
    return;
  }
  grid.innerHTML = files.map(f => {
    const display = f.replace(/\.xlsx$/i, '');
    const id = 'fi-' + btoa(unescape(encodeURIComponent(f))).replace(/[^a-zA-Z0-9]/g,'');
    return `
      <div class="file-item" id="${id}" data-file="${esc(f)}" onclick="toggleFile(this)">
        <input type="checkbox" onclick="event.stopPropagation();toggleFile(this.closest('.file-item'))">
        <span class="file-name">${esc(display)}</span>
        <span class="file-ext">.xlsx</span>
      </div>`;
  }).join('');
  updateBtn();
}

// ── Selection ─────────────────────────────────────────────────────────────────
function toggleFile(el) {
  const name = el.dataset.file;
  selected.has(name) ? selected.delete(name) : selected.add(name);
  el.classList.toggle('selected', selected.has(name));
  el.querySelector('input').checked = selected.has(name);
  updateBtn();
}

function selectAll() {
  document.querySelectorAll('.file-item').forEach(el => {
    selected.add(el.dataset.file);
    el.classList.add('selected');
    el.querySelector('input').checked = true;
  });
  updateBtn();
}

function clearSel() {
  selected.clear();
  document.querySelectorAll('.file-item').forEach(el => {
    el.classList.remove('selected');
    el.querySelector('input').checked = false;
  });
  updateBtn();
}


function updateBtn() {
  const n = selected.size;
  const btn = document.getElementById('run-btn');
  btn.disabled = n === 0;
  btn.textContent = n === 0 ? 'Run Analysis' : `Run Analysis (${n} file${n > 1 ? 's' : ''})`;
  document.getElementById('sel-count').textContent = `${n} selected`;
}

// ── Analysis ──────────────────────────────────────────────────────────────────
function runAnalysis() {
  if (!selected.size) return;
  document.getElementById('prog-log').innerHTML = '';
  document.getElementById('status-text').textContent = 'Initializing…';
  document.getElementById('spin').classList.remove('done');
  setBadge('running', 'Analyzing…');
  showPanel('panel-progress');

  const files = Array.from(selected).join(',');
  if (es) es.close();
  es = new EventSource('/api/analyze?files=' + encodeURIComponent(files));

  es.onmessage = ev => {
    try { handleEvent(JSON.parse(ev.data)); } catch(_) {}
  };
  es.onerror = () => {
    addLog('error', '⚠', 'Stream closed or connection error.');
    es.close(); es = null;
  };
}

function handleEvent(ev) {
  switch (ev.type) {
    case 'status':
      document.getElementById('status-text').textContent = ev.msg;
      addLog('status', '→', ev.msg);
      break;
    case 'company_done':
      const flag = ev.flagged ? ` (${ev.flagged} flag${ev.flagged > 1 ? 's' : ''})` : ' ✓';
      addLog('company', '■', `${ev.company}  ·  ${ev.sector || '—'}${flag}`);
      break;
    case 'comp_tick':
      const evStr = ev.ev_ebitda != null ? `${ev.ev_ebitda}x` : 'N/A';
      addLog('comp', '·', `${ev.ticker}: EV/EBITDA = ${evStr}`);
      break;
    case 'agent_text':
      if (ev.msg) addLog('agent', '✓', ev.msg.slice(0, 160) + (ev.msg.length > 160 ? '…' : ''));
      break;
    case 'results':
      lastResults = { companies: ev.companies, comps: ev.comps };
      break;
    case 'done':
      document.getElementById('status-text').textContent = 'Analysis complete';
      document.getElementById('spin').classList.add('done');
      setBadge('done', 'Complete');
      if (es) { es.close(); es = null; }
      if (lastResults) setTimeout(() => renderResults(lastResults.companies, lastResults.comps), 400);
      break;
    case 'error':
      addLog('error', '⚠', ev.msg);
      document.getElementById('status-text').textContent = 'Error — see log';
      setBadge('', 'Error');
      if (es) { es.close(); es = null; }
      break;
  }
}

function addLog(type, icon, msg) {
  const log = document.getElementById('prog-log');
  const row = document.createElement('div');
  row.className = `log-row ${type}`;
  row.innerHTML = `<span class="log-icon">${icon}</span><span class="log-msg">${esc(msg)}</span>`;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
}

// ── Render results ────────────────────────────────────────────────────────────
function renderResults(companies, comps) {
  renderStats(companies, comps);
  renderDashboard(companies, comps);
  renderComps(comps);
  renderKPIs(companies);
  renderFlags(companies);
  renderLabels(companies);
  showPanel('panel-results');
  switchTab('dashboard');
}

// Stats bar
function renderStats(companies, comps) {
  const n = companies.length;
  const sectors = new Set(companies.map(c => c.sector_key).filter(Boolean));
  const revenues = companies.map(co => normalize(co, 'revenue_fy2024')).filter(v => v !== null);
  const total = revenues.reduce((a, b) => a + b, 0);
  const margins = companies.map(co => co.ebitda_margin_fy2024).filter(v => v != null).map(v => parseFloat(v));
  const avgMargin = margins.length ? margins.reduce((a, b) => a + b, 0) / margins.length : null;

  const stats = [
    { val: n,                                              label: 'Companies Analyzed' },
    { val: sectors.size,                                   label: 'Sectors Covered' },
    { val: total ? '$' + Math.round(total/1000).toLocaleString() + 'M' : 'N/A', label: 'Total FY24 Revenue (norm.)' },
    { val: avgMargin ? (avgMargin * 100).toFixed(1) + '%' : 'N/A',              label: 'Avg EBITDA Margin' },
  ];
  document.getElementById('stats-bar').innerHTML = stats.map(s =>
    `<div class="stat-card"><div class="stat-val">${s.val}</div><div class="stat-label">${s.label}</div></div>`
  ).join('');
}

// Executive Dashboard
const SECTIONS = [
  { name: 'REVENUE', rows: [
    { label: 'FY2024 Revenue',       unit: '$000s', fn: (co,_) => normalize(co,'revenue_fy2024'),   fmt:'currency' },
    { label: 'Q1 2025 Revenue',      unit: '$000s', fn: (co,_) => normalize(co,'revenue_q1_2025'),  fmt:'currency' },
    { label: 'YoY Revenue Growth',   unit: '%',     fn: (co,_) => co.yoy_revenue_growth,            fmt:'pct', color:'growth' },
  ]},
  { name: 'PROFITABILITY', rows: [
    { label: 'FY2024 EBITDA',        unit: '$000s', fn: (co,_) => normalize(co,'ebitda_fy2024'),    fmt:'currency' },
    { label: 'Q1 2025 EBITDA',       unit: '$000s', fn: (co,_) => normalize(co,'ebitda_q1_2025'),   fmt:'currency' },
    { label: 'FY2024 EBITDA Margin', unit: '%',     fn: (co,_) => co.ebitda_margin_fy2024,          fmt:'pct', color:'margin' },
    { label: 'YoY EBITDA Growth',    unit: '%',     fn: (co,_) => co.yoy_ebitda_growth,             fmt:'pct', color:'growth' },
  ]},
  { name: 'BALANCE SHEET', rows: [
    { label: 'Net Debt',             unit: '$000s', fn: (co,_) => normalize(co,'net_debt'),         fmt:'currency' },
    { label: 'Net Leverage',         unit: 'x',     fn: (co,_) => {
        const d = normalize(co,'net_debt'), e = normalize(co,'ebitda_fy2024');
        return (d !== null && e !== null && e !== 0) ? Math.round(Math.abs(d)/e*10)/10 : null;
    }, fmt:'multiple' },
  ]},
  { name: 'PUBLIC MARKET COMPS  (Yahoo Finance — Live)', rows: [
    { label: 'Peer Median EV/EBITDA',    unit: 'x', fn: (co,c) => (c[co.company]||{}).median_ev_ebitda    ?? null, fmt:'multiple' },
    { label: 'Peer Median Rev Growth',   unit: '%', fn: (co,c) => (c[co.company]||{}).median_rev_growth   ?? null, fmt:'pct' },
    { label: 'Peer Median EBITDA Margin',unit: '%', fn: (co,c) => (c[co.company]||{}).median_ebitda_margin?? null, fmt:'pct' },
  ]},
  { name: 'COMPANY-SPECIFIC KPIs', rows: [
    { label: 'KPI 1', unit: '', fn: (co,_) => co.key_metric_1_value ?? null, fmt:'raw' },
    { label: 'KPI 2', unit: '', fn: (co,_) => co.key_metric_2_value ?? null, fmt:'raw' },
  ]},
];

function renderDashboard(companies, comps) {
  const cols = 2 + companies.length;
  let h = '<table class="dash-table"><thead><tr>';
  h += '<th style="text-align:left;min-width:220px">METRIC</th>';
  h += '<th style="text-align:center;width:60px">UNIT</th>';
  companies.forEach(co => {
    const name = co.company
      .replace(/ Holdings| Inc\.| LLC| Corp\.?| Group| Partners LP| Partners/g,'').trim();
    h += `<th class="co-hdr">${esc(name)}</th>`;
  });
  h += '</tr></thead><tbody>';

  SECTIONS.forEach(sec => {
    h += `<tr class="sec-row"><td colspan="${cols}">${sec.name}</td></tr>`;
    sec.rows.forEach(row => {
      h += '<tr class="data-row">';
      h += `<td class="metric-col">${row.label}</td>`;
      h += `<td class="unit-col">${row.unit}</td>`;
      companies.forEach(co => {
        const val = row.fn(co, comps);
        h += valCell(val, row.fmt, row.color);
      });
      h += '</tr>';
    });
  });

  h += '</tbody></table>';
  document.getElementById('tab-dashboard').innerHTML = h;
}

function valCell(val, fmt, color) {
  if (val === null || val === undefined) return '<td class="val-col np">Not Provided</td>';
  const display = fmtNum(val, fmt);
  let cls = 'val-col';
  if (color === 'growth') cls += parseFloat(val) >= 0 ? ' pos' : ' neg';
  else if (color === 'margin') cls += ' margin';
  return `<td class="${cls}">${esc(display)}</td>`;
}

function fmtNum(v, fmt) {
  if (v === null || v === undefined) return 'N/A';
  switch (fmt) {
    case 'currency': return '$' + Math.abs(v).toLocaleString('en-US',{maximumFractionDigits:0}) + (v < 0 ? ' (debt)' : '');
    case 'pct':      return (parseFloat(v) * 100).toFixed(1) + '%';
    case 'multiple': return parseFloat(v).toFixed(1) + 'x';
    default:         return String(v);
  }
}

// Market Comps
function renderComps(comps) {
  const entries = Object.entries(comps);
  if (!entries.length) {
    document.getElementById('tab-comps').innerHTML = '<div class="empty">No comps data available.</div>';
    return;
  }
  let h = '';
  entries.forEach(([coName, data]) => {
    h += `<div class="comp-block">`;
    h += `<div class="comp-block-hdr">${esc(coName)}<span class="sector-pill">${esc(data.sector||'')}</span></div>`;
    h += '<table class="gen-table"><thead><tr>';
    ['Ticker','Company','Mkt Cap ($MM)','EV/EBITDA','Rev Growth','EBITDA Margin','Price'].forEach(col =>
      h += `<th>${col}</th>`);
    h += '</tr></thead><tbody>';

    (data.comps || []).forEach(c => {
      if (c.error) {
        h += `<tr><td><strong>${esc(c.ticker)}</strong></td><td colspan="6" class="np">Error: ${esc(c.error)}</td></tr>`;
        return;
      }
      const gClass = c.revenue_growth != null ? (c.revenue_growth >= 0 ? 'pos' : 'neg') : '';
      h += '<tr>';
      h += `<td><strong>${esc(c.ticker)}</strong></td>`;
      h += `<td>${esc(c.name||'')}</td>`;
      h += numCell(c.market_cap_mm, v => '$'+v.toLocaleString('en-US',{maximumFractionDigits:0}));
      h += numCell(c.ev_ebitda,      v => v.toFixed(1)+'x');
      h += numCell(c.revenue_growth, v => (v*100).toFixed(1)+'%', gClass);
      h += numCell(c.ebitda_margin,  v => (v*100).toFixed(1)+'%');
      h += numCell(c.price,          v => '$'+v.toFixed(2));
      h += '</tr>';
    });

    if (data.median_ev_ebitda != null) {
      h += '<tr class="median-row">';
      h += '<td class="lbl">MEDIAN</td><td>—</td><td>—</td>';
      h += `<td class="num">${data.median_ev_ebitda.toFixed(1)}x</td>`;
      h += `<td class="num">${data.median_rev_growth != null ? (data.median_rev_growth*100).toFixed(1)+'%' : '—'}</td>`;
      h += `<td class="num">${data.median_ebitda_margin != null ? (data.median_ebitda_margin*100).toFixed(1)+'%' : '—'}</td>`;
      h += '<td>—</td></tr>';
    }
    h += '</tbody></table></div>';
  });
  document.getElementById('tab-comps').innerHTML = h;
}

function numCell(v, fmtFn, extraClass='') {
  if (v == null) return '<td class="num np">N/A</td>';
  return `<td class="num ${extraClass}">${fmtFn(v)}</td>`;
}

// Company KPIs
function renderKPIs(companies) {
  let h = '<table class="gen-table"><thead><tr>';
  ['Company','KPI 1 Name','KPI 1 Value','KPI 2 Name','KPI 2 Value'].forEach(c => h += `<th>${c}</th>`);
  h += '</tr></thead><tbody>';
  companies.forEach(co => {
    h += '<tr>';
    h += `<td class="co-cell">${esc(co.company)}</td>`;
    h += npCell(co.key_metric_1_name);
    h += npCell(co.key_metric_1_value);
    h += npCell(co.key_metric_2_name);
    h += npCell(co.key_metric_2_value);
    h += '</tr>';
  });
  h += '</tbody></table>';
  document.getElementById('tab-kpis').innerHTML = h;
}

// Data Flags
function renderFlags(companies) {
  let h = '<table class="gen-table"><thead><tr>';
  ['Company','Status','Flagged Fields','Data Fetched'].forEach(c => h += `<th>${c}</th>`);
  h += '</tr></thead><tbody>';
  companies.forEach(co => {
    const flags = co.flagged || [];
    const statusCls = flags.length ? 'issue' : 'clean';
    const statusTxt = flags.length ? `⚠ ${flags.length} issue${flags.length>1?'s':''}` : '✓ Clean';
    h += '<tr>';
    h += `<td class="co-cell">${esc(co.company)}</td>`;
    h += `<td class="${statusCls}">${statusTxt}</td>`;
    h += `<td>${flags.length ? esc(flags.join(', ')) : '<span class="np">None</span>'}</td>`;
    h += `<td>${esc(co.data_fetched||'')}</td>`;
    h += '</tr>';
  });
  h += '</tbody></table>';
  document.getElementById('tab-flags').innerHTML = h;
}

// Reporting Labels
function renderLabels(companies) {
  let h = '<table class="gen-table"><thead><tr>';
  ['Company','Revenue Label','EBITDA Label','Unit','FY24 EBITDA Margin','Sector','Notable Observation'].forEach(c =>
    h += `<th>${c}</th>`);
  h += '</tr></thead><tbody>';
  companies.forEach(co => {
    const margin = co.ebitda_margin_fy2024 != null
      ? `<span style="color:var(--blue);font-family:'JetBrains Mono',monospace">${(co.ebitda_margin_fy2024*100).toFixed(1)}%</span>`
      : '<span class="np">N/A</span>';
    h += '<tr>';
    h += `<td class="co-cell">${esc(co.company)}</td>`;
    h += npCell(co.revenue_label);
    h += npCell(co.ebitda_label);
    h += npCell(co.revenue_unit);
    h += `<td>${margin}</td>`;
    h += co.sector_key ? `<td><span class="sector-pill">${esc(co.sector_key)}</span></td>` : '<td class="np">N/A</td>';
    h += `<td style="max-width:320px;white-space:normal">${co.notable_observation ? esc(co.notable_observation) : '<span class="np">N/A</span>'}</td>`;
    h += '</tr>';
  });
  h += '</tbody></table>';
  document.getElementById('tab-labels').innerHTML = h;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function normalize(co, key) {
  let v = co[key];
  if (v === null || v === undefined) return null;
  v = parseFloat(v);
  if (isNaN(v)) return null;
  const unit = String(co.revenue_unit || '000s').toLowerCase();
  if (unit.includes('mm')) v *= 1000;
  return Math.round(v * 10) / 10;
}

function npCell(v) {
  if (v === null || v === undefined || v === '') return '<td class="np">Not Provided</td>';
  return `<td>${esc(String(v))}</td>`;
}

function esc(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

// ── Navigation ────────────────────────────────────────────────────────────────
function showPanel(id) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}

function switchTab(name) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.querySelectorAll('.tab-btn').forEach(b => {
    b.classList.toggle('active', b.textContent.trim().toLowerCase().startsWith(name === 'dashboard' ? 'exec' : name));
  });
}

function goSetup() {
  setBadge('', 'Ready');
  showPanel('panel-setup');
}

function setBadge(cls, text) {
  const b = document.getElementById('hdr-badge');
  b.className = 'header-badge ' + cls;
  b.textContent = text;
}
</script>
</body>
</html>
'''

if __name__ == "__main__":
    print("Portfolio Analysis Agent  →  http://localhost:5000")
    app.run(debug=True, use_reloader=False)
