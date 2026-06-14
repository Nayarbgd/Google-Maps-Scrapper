import sys
import os
import json
import queue
import threading
import time
from datetime import datetime
from dataclasses import asdict

from flask import Flask, Response, jsonify, request, send_file, render_template_string

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gui.worker import ScrapeWorker
import database.db as db

app = Flask(__name__)
app.secret_key = "gmaps-scraper-pro-2024"

db.init_db()

state = {
    "places":        [],
    "worker":        None,
    "stop_event":    threading.Event(),
    "pause_event":   threading.Event(),
    "queue":         queue.Queue(),
    "running":       False,
    "paused":        False,
    "total_expected": 0,
    "filters":       {},
    "start_time":    None,
    "db_session_id": None,
    "dup_skipped":   0,
    "filtered_out":  0,
}

# ─────────────────────────────────────────────────────────────────────────────
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Maps Lead Generator</title>
<style>
:root {
  --bg:       #0f0f17; --sidebar: #13131f; --card: #1a1a2e; --card2: #16213e;
  --border:   #2a2a45; --accent: #4f8ef7; --accent-h: #6ba3ff;
  --success:  #4ade80; --warning: #facc15; --danger: #f87171;
  --muted:    #6b7280; --text: #e2e8f0;   --text-dim: #94a3b8;
  --tree-bg:  #12121e; --tree-sel: #1e3a5f; --tree-head: #0f1929;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:14px}
body{display:flex;overflow:hidden;height:100vh}

/* ── Scrollbar ─────────────────────────────── */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px}

/* ── Sidebar ───────────────────────────────── */
#sidebar{width:310px;min-width:290px;background:var(--sidebar);display:flex;flex-direction:column;padding:20px 0 8px;border-right:1px solid var(--border);overflow-y:auto;flex-shrink:0}
.logo{padding:0 22px 16px}
.logo h1{font-size:17px;font-weight:700;color:var(--accent)}
.logo p{font-size:11px;color:var(--muted);margin-top:2px}
.sep{height:1px;background:var(--border);margin:6px 14px 14px}
.sec-lbl{font-size:10px;font-weight:700;color:var(--muted);letter-spacing:.8px;padding:0 22px 8px;text-transform:uppercase}

.field{padding:0 14px 10px}
.field label{display:block;font-size:12px;color:var(--text-dim);margin-bottom:4px}
.field input{width:100%;padding:8px 11px;background:var(--card);border:1px solid var(--border);border-radius:7px;color:var(--text);font-size:12px;outline:none;transition:border-color .15s}
.field input:focus{border-color:var(--accent)}
.field input::placeholder{color:var(--muted)}

/* Filters accordion */
.filter-toggle{display:flex;justify-content:space-between;align-items:center;width:calc(100% - 28px);margin:0 14px 6px;padding:7px 12px;background:transparent;border:1px solid var(--border);border-radius:7px;color:var(--text-dim);font-size:11px;font-weight:700;cursor:pointer;letter-spacing:.4px}
.filter-toggle:hover{background:var(--border)}
.filter-arrow{transition:transform .2s}
.filter-arrow.open{transform:rotate(180deg)}
#filters-panel{padding:0 14px 4px;display:none}
.f-row{display:flex;align-items:center;gap:8px;margin-bottom:7px}
.f-row label{font-size:11px;color:var(--text-dim);min-width:86px}
.f-row input[type=number]{flex:1;padding:5px 8px;background:var(--card);border:1px solid var(--border);border-radius:5px;color:var(--text);font-size:11px;outline:none}
.f-row input[type=number]:focus{border-color:var(--accent)}
.f-check{display:flex;align-items:center;gap:7px;font-size:11px;color:var(--text-dim);margin-bottom:5px;padding-left:2px;cursor:pointer;user-select:none}
.f-check input[type=checkbox]{width:13px;height:13px;accent-color:var(--accent)}

/* Buttons */
.btn-group{padding:4px 14px;display:flex;flex-direction:column;gap:7px}
.btn-row{display:flex;gap:6px}
button{flex:1;padding:9px 12px;border:none;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;transition:background .15s,opacity .15s;white-space:nowrap}
button:disabled{opacity:.35;cursor:not-allowed}
.btn-primary{background:var(--accent);color:#fff;font-size:13px;padding:11px}
.btn-primary:hover:not(:disabled){background:var(--accent-h)}
.btn-stop{background:#3b1f2b;color:var(--danger);border:1px solid var(--danger)}
.btn-stop:hover:not(:disabled){background:#5a2d3e}
.btn-pause{background:#2a2a1a;color:var(--warning);border:1px solid var(--warning)}
.btn-pause:hover:not(:disabled){background:#3a3a20}
.btn-pause.is-paused{background:#1a2e1a;color:var(--success);border-color:var(--success)}
.btn-clear{background:var(--card);color:var(--text-dim);border:1px solid var(--border)}
.btn-clear:hover:not(:disabled){background:var(--border)}
.btn-export{background:#1a2e1a;color:var(--success);border:1px solid var(--success)}
.btn-export:hover:not(:disabled){background:#243824}
.btn-copy{background:#1a1a2e;color:#a78bfa;border:1px solid #6d28d9;font-size:11px;padding:7px 8px}
.btn-copy:hover:not(:disabled){background:#2d1f4e}
.btn-history{background:transparent;color:var(--text-dim);border:1px solid var(--border);margin-top:4px}
.btn-history:hover{background:var(--border)}

/* Stats card */
.stats-card{margin:10px 14px 8px;background:var(--card);border-radius:10px;padding:13px 14px}
.stats-card .s-lbl{font-size:10px;font-weight:700;color:var(--muted);letter-spacing:.8px;text-transform:uppercase;margin-bottom:10px}
.stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.s-item .s-num{font-size:20px;font-weight:800;line-height:1}
.s-item .s-tag{font-size:10px;color:var(--muted);margin-top:1px}
.c-found{color:var(--accent)}
.c-saved{color:var(--success)}
.c-dup{color:var(--warning)}
.c-filt{color:#a78bfa}

/* ── Main ──────────────────────────────────── */
#main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0}

/* Progress area */
#prog-area{background:var(--card);border-bottom:1px solid var(--border);padding:12px 18px 10px;flex-shrink:0}
.prog-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
#status-text{font-size:12px;color:var(--text-dim);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.timer-group{display:flex;gap:12px;font-size:11px;color:var(--muted);flex-shrink:0;margin-left:12px}
#timer-el{font-family:'Courier New',monospace;font-weight:700;color:var(--text)}
.bar-row{display:flex;align-items:center;gap:8px;margin-bottom:5px}
.bar-track{flex:1;height:7px;background:var(--border);border-radius:4px;overflow:hidden}
.bar-fill{height:100%;width:0%;background:linear-gradient(90deg,var(--accent),var(--accent-h));border-radius:4px;transition:width .5s ease}
#count-text{font-size:12px;font-weight:700;color:var(--accent);min-width:52px;text-align:right;flex-shrink:0}
.bar-extras{display:flex;gap:14px;font-size:10px;color:var(--muted)}
.bar-ext-n{font-weight:700;color:var(--text-dim)}

/* Quick-stats bar */
#qstats{display:flex;background:var(--card2);border-bottom:1px solid var(--border);flex-shrink:0}
.qs-item{flex:1;padding:9px 0;text-align:center;border-right:1px solid var(--border)}
.qs-item:last-child{border-right:none}
.qs-num{font-size:15px;font-weight:800;display:block;line-height:1.2}
.qs-lbl{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.qs-acc{color:var(--accent)}
.qs-suc{color:var(--success)}
.qs-pur{color:#a78bfa}
.qs-war{color:var(--warning)}
.qs-dim{color:var(--text-dim)}

/* Results table */
#table-wrap{flex:1;overflow:auto;background:var(--tree-bg)}
table{width:100%;border-collapse:collapse;font-size:12px}
thead th{position:sticky;top:0;background:var(--tree-head);color:var(--accent);font-size:10px;font-weight:700;letter-spacing:.4px;text-transform:uppercase;padding:9px 12px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap;z-index:2}
tbody tr{border-bottom:1px solid rgba(42,42,69,.4);transition:background .1s}
tbody tr:nth-child(even){background:rgba(26,26,46,.5)}
tbody tr:hover{background:rgba(79,142,247,.1)}
tbody td{padding:7px 12px;vertical-align:middle;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
td.td-name{font-weight:500;color:var(--text);max-width:220px}
td.td-phone{color:#a78bfa}
td.td-web{color:var(--accent)}
td.td-email{color:#34d399}
td.td-rating{color:var(--warning);font-weight:700}
td.td-status-open{color:var(--success);font-weight:600}
td.td-status-closed{color:var(--danger);font-weight:600}
td.td-status-dim{color:var(--muted)}
td.td-opp-critical{color:#ff4444;font-weight:700}
td.td-opp-high{color:#f87171}
td.td-opp-med{color:#facc15}
td.td-opp-low{color:#4ade80}
td.td-ws-working{color:#4ade80;font-weight:600}
td.td-ws-protected{color:#facc15;font-weight:600}
td.td-ws-slow{color:#a78bfa;font-weight:600}
td.td-ws-broken{color:#f87171;font-weight:600}
td.td-ws-notfound{color:#f87171;font-weight:600}
td.td-ws-dim{color:#6b7280}
.empty-state{text-align:center;padding:60px 20px;color:var(--muted)}
.empty-state .ei{font-size:44px;margin-bottom:10px}

/* Log panel */
#log-panel{height:160px;flex-shrink:0;background:var(--sidebar);border-top:1px solid var(--border);display:flex;flex-direction:column}
#log-header{font-size:10px;font-weight:700;color:var(--muted);letter-spacing:.8px;padding:8px 14px 3px;text-transform:uppercase;flex-shrink:0}
#log-box{flex:1;overflow-y:auto;padding:0 14px 6px;font-family:'Courier New',monospace;font-size:11px;color:var(--text-dim);line-height:1.65}
.tag{display:inline-block;padding:1px 6px;border-radius:99px;font-size:9px;font-weight:700;letter-spacing:.3px}
.tw{background:rgba(250,204,21,.12);color:var(--warning)}
.te{background:rgba(248,113,113,.12);color:var(--danger)}
.to{background:rgba(74,222,128,.12);color:var(--success)}
.ti{background:rgba(79,142,247,.12);color:var(--accent)}

/* Modal */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.75);z-index:1000;align-items:center;justify-content:center}
.modal-overlay.open{display:flex}
.modal-box{background:var(--card);border:1px solid var(--border);border-radius:14px;width:660px;max-width:95vw;max-height:82vh;display:flex;flex-direction:column;box-shadow:0 25px 60px rgba(0,0,0,.5)}
.modal-head{display:flex;justify-content:space-between;align-items:center;padding:18px 22px;border-bottom:1px solid var(--border);flex-shrink:0}
.modal-head h2{font-size:15px;font-weight:700;color:var(--text)}
.modal-close{background:transparent;border:none;color:var(--muted);font-size:18px;cursor:pointer;padding:0 4px;flex:0}
.modal-close:hover{color:var(--text)}
.modal-body{overflow-y:auto;padding:14px}
.session-item{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;border:1px solid var(--border);border-radius:9px;margin-bottom:8px;background:var(--bg);gap:12px}
.session-query{font-weight:600;color:var(--text);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:300px}
.session-meta{color:var(--muted);font-size:10px;margin-top:3px}
.session-acts{display:flex;gap:5px;flex-shrink:0}
.btn-sm{padding:5px 9px;font-size:10px;font-weight:700;border:none;border-radius:5px;cursor:pointer}
.bsm-exp{background:#1a2e1a;color:var(--success);border:1px solid var(--success)}
.bsm-del{background:#2e1a1a;color:var(--danger);border:1px solid var(--danger)}
.bsm-exp:hover,.bsm-del:hover{filter:brightness(1.2)}
.no-sessions{text-align:center;padding:40px;color:var(--muted);font-size:13px}

/* Toast */
#toast{position:fixed;bottom:22px;right:22px;background:#252538;color:var(--text);padding:11px 18px;border-radius:9px;z-index:9999;font-size:12px;border:1px solid var(--border);opacity:0;transition:opacity .3s;pointer-events:none;max-width:280px}
#toast.show{opacity:1}
</style>
</head>
<body>

<!-- ═══════════════ SIDEBAR ═══════════════ -->
<div id="sidebar">
  <div class="logo">
    <h1>🗺&nbsp; Maps Lead Generator</h1>
    <p>Professional Google Maps Business Intelligence</p>
  </div>
  <div class="sep"></div>
  <div class="sec-lbl">Search Parameters</div>

  <div class="field">
    <label>Business Keyword</label>
    <input id="inp-kw" type="text" placeholder="e.g.  dental clinic"/>
  </div>
  <div class="field">
    <label>Location</label>
    <input id="inp-loc" type="text" placeholder="e.g.  Madrid, Spain"/>
  </div>
  <div class="field">
    <label>Max Results</label>
    <input id="inp-max" type="number" placeholder="e.g.  25" min="1" max="500" value="20"/>
  </div>

  <!-- Filters accordion -->
  <button class="filter-toggle" onclick="toggleFilters()">
    <span>⚙&nbsp; FILTERS</span>
    <span class="filter-arrow" id="farrow">▼</span>
  </button>
  <div id="filters-panel">
    <div class="f-row">
      <label>Min Rating</label>
      <input id="f-rating" type="number" step="0.1" min="0" max="5" placeholder="e.g. 4.0"/>
    </div>
    <div class="f-row">
      <label>Min Reviews</label>
      <input id="f-reviews" type="number" min="0" placeholder="e.g. 10"/>
    </div>
    <label class="f-check"><input type="checkbox" id="f-web"/>  Website required</label>
    <label class="f-check"><input type="checkbox" id="f-phone"/>  Phone required</label>
    <label class="f-check"><input type="checkbox" id="f-email"/>  Email required</label>
    <label class="f-check"><input type="checkbox" id="f-no-web"/>  Only businesses without website</label>
    <label class="f-check"><input type="checkbox" id="f-broken-web"/>  Only businesses with broken websites</label>
  </div>

  <div class="sep"></div>

  <div class="btn-group">
    <button class="btn-primary" id="btn-start" onclick="startScrape()">▶&nbsp;&nbsp;Start Search</button>
    <div class="btn-row">
      <button class="btn-stop"  id="btn-stop"  onclick="stopScrape()"  disabled>■&nbsp; Stop</button>
      <button class="btn-pause" id="btn-pause" onclick="togglePause()" disabled>⏸&nbsp; Pause</button>
    </div>
    <div class="btn-row">
      <button class="btn-clear"  id="btn-clear" onclick="clearResults()">✕&nbsp; Clear</button>
      <button class="btn-export" id="btn-csv"   onclick="exportData('csv')">⬇&nbsp; CSV</button>
      <button class="btn-export" id="btn-xlsx"  onclick="exportData('excel')">⬇&nbsp; Excel</button>
    </div>
  </div>

  <div class="sep"></div>
  <div class="sec-lbl">Copy Leads</div>
  <div class="btn-group" style="padding-top:0">
    <div class="btn-row">
      <button class="btn-copy" onclick="copyLeads('phones')">📞&nbsp;Phones</button>
      <button class="btn-copy" onclick="copyLeads('emails')">📧&nbsp;Emails</button>
      <button class="btn-copy" onclick="copyLeads('webs')">🌐&nbsp;Webs</button>
    </div>
  </div>

  <div class="sep"></div>
  <div class="btn-group" style="padding-top:0;padding-bottom:4px">
    <button class="btn-history" onclick="openSessions()">📋&nbsp;&nbsp;Session History</button>
  </div>

  <!-- Stats card -->
  <div class="stats-card">
    <div class="s-lbl">Session Stats</div>
    <div class="stats-grid">
      <div class="s-item"><div class="s-num c-found" id="st-found">0</div><div class="s-tag">Found</div></div>
      <div class="s-item"><div class="s-num c-saved" id="st-saved">0</div><div class="s-tag">Saved</div></div>
      <div class="s-item"><div class="s-num c-dup"   id="st-dup">0</div><div class="s-tag">Dupes</div></div>
      <div class="s-item"><div class="s-num c-filt"  id="st-filt">0</div><div class="s-tag">Filtered</div></div>
    </div>
  </div>
</div>

<!-- ═══════════════ MAIN ═══════════════════ -->
<div id="main">

  <!-- Progress bar -->
  <div id="prog-area">
    <div class="prog-top">
      <div id="status-text">Ready — enter a query and press Start Search</div>
      <div class="timer-group">
        <span id="timer-el">00:00:00</span>
        <span id="eta-el" style="color:var(--muted)">ETA&nbsp;—</span>
      </div>
    </div>
    <div class="bar-row">
      <div class="bar-track"><div class="bar-fill" id="bar-fill"></div></div>
      <div id="count-text">0 / 0</div>
    </div>
    <div class="bar-extras">
      <span>Scraped: <span class="bar-ext-n" id="be-scraped">0</span></span>
      <span>Duplicates skipped: <span class="bar-ext-n" id="be-dup">0</span></span>
      <span>Filtered out: <span class="bar-ext-n" id="be-filt">0</span></span>
    </div>
  </div>

  <!-- Quick stats bar -->
  <div id="qstats">
    <div class="qs-item"><span class="qs-num qs-acc" id="qs-total">0</span><span class="qs-lbl">Total Found</span></div>
    <div class="qs-item"><span class="qs-num qs-suc" id="qs-web">0%</span><span class="qs-lbl">With Website</span></div>
    <div class="qs-item"><span class="qs-num qs-pur" id="qs-email">0%</span><span class="qs-lbl">With Email</span></div>
    <div class="qs-item"><span class="qs-num qs-war" id="qs-rating">—</span><span class="qs-lbl">Avg Rating</span></div>
    <div class="qs-item"><span class="qs-num qs-dim" id="qs-reviews">0</span><span class="qs-lbl">Total Reviews</span></div>
  </div>

  <!-- Results table -->
  <div id="table-wrap">
    <table id="results-table">
      <thead><tr>
        <th style="min-width:200px">Business Name</th>
        <th style="min-width:120px">Phone</th>
        <th style="min-width:150px">Website</th>
        <th style="min-width:190px">Address</th>
        <th style="min-width:62px">Rating</th>
        <th style="min-width:72px">Reviews</th>
        <th style="min-width:120px">Category</th>
        <th style="min-width:165px">Email</th>
        <th style="min-width:72px">Status</th>
        <th style="min-width:130px">Opportunity</th>
        <th style="min-width:110px">Website Status</th>
        <th style="min-width:210px">Website Error</th>
        <th style="min-width:80px">Confidence</th>
      </tr></thead>
      <tbody id="results-body">
        <tr id="empty-row"><td colspan="13">
          <div class="empty-state">
            <div class="ei">🔍</div>
            <p>No results yet — enter a search and press Start Search</p>
          </div>
        </td></tr>
      </tbody>
    </table>
  </div>

  <!-- Log panel -->
  <div id="log-panel">
    <div id="log-header">Activity Log</div>
    <div id="log-box"></div>
  </div>
</div>

<!-- ═══════════════ SESSION MODAL ══════════ -->
<div class="modal-overlay" id="session-modal">
  <div class="modal-box">
    <div class="modal-head">
      <h2>📋&nbsp; Session History</h2>
      <button class="modal-close" onclick="closeModal()">✕</button>
    </div>
    <div class="modal-body" id="session-list">
      <div class="no-sessions">Loading…</div>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
// ─── State ────────────────────────────────────────────────────────────────
let places      = [];
let stats       = { webCnt:0, emailCnt:0, ratingSum:0, ratingCnt:0, reviewsSum:0 };
let currentCnt  = 0;
let totalExp    = 0;
let startTime   = null;
let timerIv     = null;
let evtSrc      = null;
let paused      = false;
let running     = false;

// ─── Utility ──────────────────────────────────────────────────────────────
function ts()  { return new Date().toLocaleTimeString('en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'}); }
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function fmt(n){ return n!=null ? Number(n).toLocaleString() : '—'; }

function pad(n){ return String(n).padStart(2,'0'); }
function fmtSecs(s){
  s = Math.max(0, Math.floor(s));
  return pad(Math.floor(s/3600)) + ':' + pad(Math.floor((s%3600)/60)) + ':' + pad(s%60);
}

function showToast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(()=>t.classList.remove('show'), 3000);
}

// ─── Timer ────────────────────────────────────────────────────────────────
function startTimer(){
  startTime = Date.now();
  timerIv = setInterval(()=>{
    const el = Math.floor((Date.now()-startTime)/1000);
    document.getElementById('timer-el').textContent = fmtSecs(el);
    if(currentCnt>0 && totalExp>0){
      const rate = el/currentCnt;
      const rem  = (totalExp-currentCnt)*rate;
      document.getElementById('eta-el').textContent = 'ETA '+fmtSecs(rem);
    }
  }, 1000);
}
function stopTimer(){ clearInterval(timerIv); timerIv=null; }

// ─── Stats ────────────────────────────────────────────────────────────────
function resetStats(){
  stats = { webCnt:0, emailCnt:0, ratingSum:0, ratingCnt:0, reviewsSum:0 };
  places = []; currentCnt=0;
  ['qs-total','qs-web','qs-email','qs-rating','qs-reviews'].forEach(id=>{
    document.getElementById(id).textContent = id==='qs-web'||id==='qs-email' ? '0%' : id==='qs-rating' ? '—' : '0';
  });
  document.getElementById('st-found').textContent='0';
  document.getElementById('st-saved').textContent='0';
  document.getElementById('st-dup').textContent='0';
  document.getElementById('st-filt').textContent='0';
}

function pushStats(place){
  places.push(place);
  currentCnt++;
  if(place.website)          stats.webCnt++;
  if(place.email)            stats.emailCnt++;
  if(place.reviews_average){ stats.ratingSum+=parseFloat(place.reviews_average); stats.ratingCnt++; }
  if(place.reviews_count)    stats.reviewsSum+=parseInt(place.reviews_count)||0;

  const tot = places.length;
  document.getElementById('qs-total').textContent   = tot;
  document.getElementById('qs-web').textContent     = tot ? Math.round(stats.webCnt/tot*100)+'%'   : '0%';
  document.getElementById('qs-email').textContent   = tot ? Math.round(stats.emailCnt/tot*100)+'%' : '0%';
  document.getElementById('qs-rating').textContent  = stats.ratingCnt ? (stats.ratingSum/stats.ratingCnt).toFixed(1)+'★' : '—';
  document.getElementById('qs-reviews').textContent = stats.reviewsSum.toLocaleString();
  document.getElementById('st-found').textContent   = tot;
  document.getElementById('st-saved').textContent   = tot;
}

// ─── Opportunity ──────────────────────────────────────────────────────────
function hasValidWebsite(place){
  const ws = (place.website||'').trim();
  return ws && ws !== '-' && ws !== '—' && (ws.includes('.')||ws.toLowerCase().includes('http'));
}
const _BROKEN_STATUSES = new Set(['Domain Not Found','Server Unreachable','Server Error','Parked Domain']);
function getOpportunity(place){
  const ws = place.website_status||'';
  if(ws && _BROKEN_STATUSES.has(ws))
    return {label:'🔥 Critical', cls:'td-opp-critical'};
  if(!hasValidWebsite(place))
    return {label:'🔥 High',     cls:'td-opp-high'};
  const rev = parseInt(place.reviews_count)||0;
  if(rev < 20)
    return {label:'🟡 Medium',   cls:'td-opp-med'};
  return   {label:'🟢 Low',      cls:'td-opp-low'};
}
function getWsCell(place){
  const s = place.website_status||'';
  if(!s) return {label:'—', cls:'td-ws-dim'};
  const map = {
    'Working':                  {label:'🟢 Working',                  cls:'td-ws-working'},
    'Accessible but Protected': {label:'🟡 Protected',                 cls:'td-ws-protected'},
    'Very Slow but Working':    {label:'🟣 Very Slow',                 cls:'td-ws-slow'},
    'Domain Not Found':         {label:'🔴 Domain Not Found',          cls:'td-ws-notfound'},
    'Server Unreachable':       {label:'🔴 Server Unreachable',        cls:'td-ws-broken'},
    'Server Error':             {label:'🔴 Server Error',              cls:'td-ws-broken'},
    'Parked Domain':            {label:'🔴 Parked Domain',             cls:'td-ws-broken'},
  };
  return map[s] || {label:s, cls:'td-ws-dim'};
}
function fmtConfidence(place){
  const c = place.website_confidence;
  if(c === undefined || c === null || c < 0) return '—';
  if(c === 0) return '—';
  return c + '%';
}

// ─── Table ────────────────────────────────────────────────────────────────
function addRow(place){
  const tbody = document.getElementById('results-body');
  document.getElementById('empty-row')?.remove();
  const rating  = place.reviews_average ? parseFloat(place.reviews_average).toFixed(1)+' ★' : '—';
  const reviews = place.reviews_count   ? Number(place.reviews_count).toLocaleString() : '—';
  let   statusCls = 'td-status-dim', statusTxt = place.open_status || '—';
  if(place.open_status==='Open')   statusCls='td-status-open';
  if(place.open_status==='Closed') statusCls='td-status-closed';
  const opp = getOpportunity(place);
  const wsc = getWsCell(place);
  const wsErr = (place.website_error_reason||'').trim();

  const tr = document.createElement('tr');
  tr.innerHTML = `
    <td class="td-name"  title="${esc(place.name)}">${esc(place.name)}</td>
    <td class="td-phone">${esc(place.phone_number||'—')}</td>
    <td class="td-web"   title="${esc(place.website)}">${esc(place.website||'—')}</td>
    <td title="${esc(place.address)}">${esc(place.address||'—')}</td>
    <td class="td-rating">${rating}</td>
    <td>${reviews}</td>
    <td title="${esc(place.place_type)}">${esc(place.place_type||'—')}</td>
    <td class="td-email" title="${esc(place.email)}">${esc(place.email||'—')}</td>
    <td class="${statusCls}">${esc(statusTxt)}</td>
    <td class="${opp.cls}" style="font-weight:600">${opp.label}</td>
    <td class="${wsc.cls}">${wsc.label}</td>
    <td class="td-ws-dim" title="${esc(wsErr)}">${esc(wsErr||'—')}</td>
    <td class="td-ws-dim" style="text-align:center">${fmtConfidence(place)}</td>`;
  tbody.appendChild(tr);
  tr.scrollIntoView({block:'nearest'});
}

// ─── Log ──────────────────────────────────────────────────────────────────
function log(msg, type){
  const box  = document.getElementById('log-box');
  const line = document.createElement('div');
  const tagMap = {warn:'<span class="tag tw">WARN</span> ',error:'<span class="tag te">ERR</span> ',ok:'<span class="tag to">OK</span> ',info:'<span class="tag ti">INFO</span> '};
  line.innerHTML = `<span style="color:#3a3a5a">[${ts()}]</span> ${tagMap[type]||''}${esc(msg)}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

// ─── Status helpers ────────────────────────────────────────────────────────
function setStatus(msg, col){ const el=document.getElementById('status-text'); el.textContent=msg; el.style.color=col||'var(--text-dim)'; }
function setProgress(cur, tot){
  const pct = tot ? cur/tot*100 : 0;
  document.getElementById('bar-fill').style.width  = pct+'%';
  document.getElementById('count-text').textContent = `${cur} / ${tot}`;
}
function setExtras(scraped, dup, filt){
  document.getElementById('be-scraped').textContent = scraped;
  document.getElementById('be-dup').textContent     = dup;
  document.getElementById('be-filt').textContent    = filt;
  document.getElementById('st-dup').textContent     = dup;
  document.getElementById('st-filt').textContent    = filt;
}

// ─── Controls ─────────────────────────────────────────────────────────────
function setBtns(isRunning){
  running = isRunning;
  document.getElementById('btn-start').disabled = isRunning;
  document.getElementById('btn-stop').disabled  = !isRunning;
  document.getElementById('btn-pause').disabled = !isRunning;
}

function getFilters(){
  const f={};
  const r = parseFloat(document.getElementById('f-rating').value);
  const v = parseInt(document.getElementById('f-reviews').value);
  if(r>0)  f.min_rating  = r;
  if(v>0)  f.min_reviews = v;
  if(document.getElementById('f-web').checked)        f.require_web         = true;
  if(document.getElementById('f-phone').checked)      f.require_phone       = true;
  if(document.getElementById('f-email').checked)      f.require_email       = true;
  if(document.getElementById('f-no-web').checked)     f.no_website          = true;
  if(document.getElementById('f-broken-web').checked) f.only_broken_websites = true;
  return f;
}

// ─── Scrape actions ────────────────────────────────────────────────────────
async function startScrape(){
  const kw  = document.getElementById('inp-kw').value.trim();
  const loc = document.getElementById('inp-loc').value.trim();
  const max = parseInt(document.getElementById('inp-max').value)||20;
  if(!kw){ alert('Please enter a business keyword.'); return; }
  const query = loc ? `${kw} in ${loc}` : kw;

  resetStats();
  document.getElementById('results-body').innerHTML=`<tr id="empty-row"><td colspan="13"><div class="empty-state"><div class="ei">🔍</div><p>Searching…</p></div></td></tr>`;
  document.getElementById('log-box').innerHTML='';
  setProgress(0,max); setExtras(0,0,0);
  document.getElementById('bar-fill').style.width='0%';
  document.getElementById('timer-el').textContent='00:00:00';
  document.getElementById('eta-el').textContent='ETA —';
  totalExp=max; paused=false;

  const pauseBtn=document.getElementById('btn-pause');
  pauseBtn.textContent='⏸\u00a0Pause'; pauseBtn.className='btn-pause';

  setBtns(true);
  setStatus(`Launching browser — searching: ${query}`,'var(--warning)');
  log(`Starting scrape: "${query}" — up to ${max} results`,'info');
  startTimer();

  const filters = getFilters();
  await fetch('/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query,total:max,filters})});

  if(evtSrc){ evtSrc.close(); }
  evtSrc = new EventSource('/stream');

  evtSrc.addEventListener('progress', e=>{
    const d = JSON.parse(e.data);
    pushStats(d.place);
    addRow(d.place);
    setProgress(d.current, d.total);
    setExtras(d.scraped_idx, d.dup_skipped, d.filtered);
    setStatus(`Scraping: ${d.place.name}`,'var(--text)');
  });

  evtSrc.addEventListener('log', e=>{
    const d=JSON.parse(e.data);
    const t=d.msg.startsWith('WARNING')?'warn':d.msg.startsWith('ERROR')?'error':'info';
    log(d.msg,t);
  });

  evtSrc.addEventListener('paused', ()=>{
    setStatus('⏸ Paused — click Resume to continue','var(--warning)');
    log('Scrape paused.','warn');
  });

  evtSrc.addEventListener('resumed', ()=>{
    setStatus('▶ Resumed…','var(--text)');
    log('Scrape resumed.','info');
  });

  evtSrc.addEventListener('done', e=>{
    const d=JSON.parse(e.data);
    setStatus(`✅ Complete — ${d.count} businesses found`,'var(--success)');
    log(`Scrape complete. ${d.count} results saved.`,'ok');
    document.getElementById('bar-fill').style.width='100%';
    stopTimer(); setBtns(false);
    evtSrc.close();
  });

  evtSrc.addEventListener('stopped', ()=>{
    setStatus(`⏹ Stopped — ${currentCnt} businesses collected`,'var(--warning)');
    log(`Scrape stopped. ${currentCnt} results collected.`,'warn');
    stopTimer(); setBtns(false);
    evtSrc.close();
  });

  evtSrc.addEventListener('error_event', e=>{
    const d=JSON.parse(e.data);
    setStatus(`❌ Error: ${d.msg.slice(0,80)}`,'var(--danger)');
    log(`ERROR: ${d.msg}`,'error');
    stopTimer(); setBtns(false);
    evtSrc.close();
  });
}

async function stopScrape(){
  document.getElementById('btn-stop').disabled=true;
  setStatus('Stopping — finishing current item…','var(--warning)');
  log('Stop requested by user.','warn');
  await fetch('/stop',{method:'POST'});
}

async function togglePause(){
  const resp = await fetch('/pause',{method:'POST'});
  const d    = await resp.json();
  paused = d.paused;
  const btn = document.getElementById('btn-pause');
  if(paused){
    btn.textContent='▶\u00a0Resume'; btn.className='btn-pause is-paused';
  } else {
    btn.textContent='⏸\u00a0Pause'; btn.className='btn-pause';
  }
}

async function clearResults(){
  if(running){ alert('Stop the scrape first.'); return; }
  if(places.length && !confirm('Clear all current results from the view?')) return;
  await fetch('/clear',{method:'POST'});
  resetStats();
  document.getElementById('results-body').innerHTML=`<tr id="empty-row"><td colspan="13"><div class="empty-state"><div class="ei">🔍</div><p>No results yet — enter a search query and press Start Search</p></div></td></tr>`;
  document.getElementById('log-box').innerHTML='';
  document.getElementById('bar-fill').style.width='0%';
  document.getElementById('count-text').textContent='0 / 0';
  document.getElementById('be-scraped').textContent='0';
  document.getElementById('be-dup').textContent='0';
  document.getElementById('be-filt').textContent='0';
  document.getElementById('timer-el').textContent='00:00:00';
  document.getElementById('eta-el').textContent='ETA —';
  setStatus('Ready — enter a query and press Start Search','');
}

// ─── Export ───────────────────────────────────────────────────────────────
function exportData(fmt){
  if(!places.length){ alert('No results to export yet.'); return; }
  window.location.href=`/export/${fmt}`;
}

// ─── Copy Leads ───────────────────────────────────────────────────────────
function copyLeads(type){
  let lines=[];
  if(type==='phones') lines=places.filter(p=>p.phone_number).map(p=>p.phone_number);
  else if(type==='emails') lines=places.filter(p=>p.email).map(p=>p.email);
  else if(type==='webs')   lines=places.filter(p=>p.website).map(p=>p.website);
  if(!lines.length){ showToast(`No ${type} found in current results.`); return; }
  navigator.clipboard.writeText(lines.join('\n'))
    .then(()=>showToast(`✅ Copied ${lines.length} ${type} to clipboard!`))
    .catch(()=>showToast('⚠ Clipboard access denied — try HTTPS'));
}

// ─── Filters accordion ────────────────────────────────────────────────────
function toggleFilters(){
  const panel=document.getElementById('filters-panel');
  const arrow=document.getElementById('farrow');
  const open=panel.style.display==='block';
  panel.style.display=open?'none':'block';
  arrow.classList.toggle('open',!open);
}

// ─── Session History ──────────────────────────────────────────────────────
async function openSessions(){
  document.getElementById('session-modal').classList.add('open');
  document.getElementById('session-list').innerHTML='<div class="no-sessions">Loading…</div>';
  const resp=await fetch('/sessions');
  const d=await resp.json();
  renderSessions(d.sessions);
}
function closeModal(){ document.getElementById('session-modal').classList.remove('open'); }

function fmtDate(iso){
  try{ return new Date(iso).toLocaleString('en-GB',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}); }
  catch{ return iso; }
}

function renderSessions(sessions){
  const c=document.getElementById('session-list');
  if(!sessions||!sessions.length){ c.innerHTML='<div class="no-sessions">No sessions saved yet.<br>Run a scrape and results will appear here.</div>'; return; }
  c.innerHTML=sessions.map(s=>`
    <div class="session-item" id="si-${s.id}">
      <div style="min-width:0;flex:1">
        <div class="session-query" title="${esc(s.query)}">"${esc(s.query)}"</div>
        <div class="session-meta">${fmtDate(s.created_at)} &nbsp;·&nbsp; ${s.total_found} results &nbsp;·&nbsp; ${s.dup_skipped} dupes &nbsp;·&nbsp; ${s.filtered} filtered</div>
      </div>
      <div class="session-acts">
        <button class="btn-sm bsm-exp" onclick="exportSession(${s.id},'csv')">CSV</button>
        <button class="btn-sm bsm-exp" onclick="exportSession(${s.id},'excel')">Excel</button>
        <button class="btn-sm bsm-del" onclick="deleteSession(${s.id})">🗑</button>
      </div>
    </div>`).join('');
}

function exportSession(id,fmt){ window.location.href=`/export/${fmt}?session_id=${id}`; }

async function deleteSession(id){
  if(!confirm('Delete this session and all its data?')) return;
  await fetch(`/sessions/${id}`,{method:'DELETE'});
  document.getElementById(`si-${id}`)?.remove();
  const c=document.getElementById('session-list');
  if(!c.querySelector('.session-item')) c.innerHTML='<div class="no-sessions">No sessions saved yet.</div>';
}

// Close modal on overlay click
document.getElementById('session-modal').addEventListener('click', e=>{ if(e.target===e.currentTarget) closeModal(); });
</script>
</body>
</html>"""

# ─────────────────────────────────────────────────────────────────────────────
# Flask routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/start", methods=["POST"])
def start():
    if state["running"]:
        return jsonify({"ok": False, "msg": "Already running"})

    data    = request.get_json() or {}
    query   = data.get("query", "").strip()
    total   = max(1, int(data.get("total", 20)))
    raw_f   = data.get("filters", {}) or {}

    # Validate and clean filters
    filters = {}
    try:
        v = float(raw_f.get("min_rating", 0) or 0)
        if v > 0: filters["min_rating"] = v
    except Exception: pass
    try:
        v = int(raw_f.get("min_reviews", 0) or 0)
        if v > 0: filters["min_reviews"] = v
    except Exception: pass
    if raw_f.get("require_web"):          filters["require_web"]          = True
    if raw_f.get("require_phone"):        filters["require_phone"]        = True
    if raw_f.get("require_email"):        filters["require_email"]        = True
    if raw_f.get("no_website"):           filters["no_website"]           = True
    if raw_f.get("only_broken_websites"): filters["only_broken_websites"] = True

    # Reset state
    state["places"]        = []
    state["running"]       = True
    state["paused"]        = False
    state["total_expected"]= total
    state["filters"]       = filters
    state["start_time"]    = time.time()
    state["dup_skipped"]   = 0
    state["filtered_out"]  = 0
    state["stop_event"].clear()
    state["pause_event"].clear()
    state["queue"]         = queue.Queue()

    # Create DB session
    state["db_session_id"] = db.create_session(query, total, filters or None)

    state["worker"] = ScrapeWorker(
        query, total, state["queue"], state["stop_event"],
        pause_event=state["pause_event"],
        filters=filters if filters else None,
    )
    state["worker"].start()
    return jsonify({"ok": True})


@app.route("/stop", methods=["POST"])
def stop():
    state["stop_event"].set()
    return jsonify({"ok": True})


@app.route("/pause", methods=["POST"])
def pause_toggle():
    if not state["running"]:
        return jsonify({"ok": False, "paused": False})

    if state["paused"]:
        state["pause_event"].clear()
        state["paused"] = False
        state["queue"].put(("resumed",))
        return jsonify({"ok": True, "paused": False})
    else:
        state["pause_event"].set()
        state["paused"] = True
        state["queue"].put(("paused",))
        return jsonify({"ok": True, "paused": True})


@app.route("/clear", methods=["POST"])
def clear():
    state["places"] = []
    return jsonify({"ok": True})


@app.route("/stream")
def stream():
    def generate():
        while True:
            try:
                msg = state["queue"].get(timeout=0.5)
            except queue.Empty:
                if not state["running"]:
                    break
                yield ": heartbeat\n\n"
                continue

            kind = msg[0]

            if kind == "log":
                yield f"event: log\ndata: {json.dumps({'msg': msg[1]})}\n\n"

            elif kind == "progress":
                _, current, total_lst, place, extras = msg if len(msg) >= 5 else (*msg, {})
                state["places"].append(place)
                state["dup_skipped"]  = extras.get("dup_skipped", 0)
                state["filtered_out"] = extras.get("filtered", 0)

                # Persist to DB
                if state["db_session_id"]:
                    db.save_place(state["db_session_id"], place)

                payload = json.dumps({
                    "current":    current,
                    "total":      total_lst,
                    "place":      asdict(place),
                    "scraped_idx":extras.get("scraped_idx", current),
                    "dup_skipped":extras.get("dup_skipped", 0),
                    "filtered":   extras.get("filtered", 0),
                })
                yield f"event: progress\ndata: {payload}\n\n"

            elif kind == "paused":
                yield "event: paused\ndata: {}\n\n"

            elif kind == "resumed":
                yield "event: resumed\ndata: {}\n\n"

            elif kind == "done":
                _, places = msg
                state["places"]  = places
                state["running"] = False
                if state["db_session_id"]:
                    db.update_session(
                        state["db_session_id"], len(places),
                        state["dup_skipped"], state["filtered_out"]
                    )
                yield f"event: done\ndata: {json.dumps({'count': len(places)})}\n\n"
                break

            elif kind == "stopped":
                state["running"] = False
                if state["db_session_id"]:
                    db.update_session(
                        state["db_session_id"], len(state["places"]),
                        state["dup_skipped"], state["filtered_out"]
                    )
                yield "event: stopped\ndata: {}\n\n"
                break

            elif kind == "error":
                state["running"] = False
                yield f"event: error_event\ndata: {json.dumps({'msg': msg[1]})}\n\n"
                break

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Sessions ────────────────────────────────────────────────────────────────

@app.route("/sessions")
def list_sessions():
    return jsonify({"sessions": db.list_sessions()})


@app.route("/sessions/<int:sid>", methods=["DELETE"])
def delete_session(sid):
    db.delete_session(sid)
    return jsonify({"ok": True})


# ─── Export ───────────────────────────────────────────────────────────────────

_BROKEN_STATUSES_PY = {"Domain Not Found", "Server Unreachable", "Server Error", "Parked Domain"}

def _compute_opportunity(row) -> str:
    ws_status = str(row.get("website_status") or "").strip()
    if ws_status in _BROKEN_STATUSES_PY:
        return "Critical Opportunity"
    ws = str(row.get("website") or "").strip()
    has_web = bool(ws and ws != "-" and ws != "—" and ("." in ws or "http" in ws.lower()))
    if not has_web:
        return "High Opportunity"
    try:
        rev = int(row.get("reviews_count") or 0)
    except Exception:
        rev = 0
    if rev < 20:
        return "Medium Opportunity"
    return "Low Opportunity"


def _build_dataframe(session_id=None):
    import pandas as pd
    if session_id:
        rows = db.get_session_places(session_id)
        df = pd.DataFrame(rows).drop(columns=["id","session_id"], errors="ignore")
    else:
        from dataclasses import asdict as _ad
        df = pd.DataFrame([_ad(p) for p in state["places"]])
    if not df.empty:
        df["opportunity"] = df.apply(_compute_opportunity, axis=1)
    return df


@app.route("/export/csv")
def export_csv():
    session_id = request.args.get("session_id", type=int)
    if not session_id and not state["places"]:
        return jsonify({"error": "No data"}), 400

    exports_dir = os.path.join(os.path.dirname(__file__), "exports")
    os.makedirs(exports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(exports_dir, f"results_{ts}.csv")
    _build_dataframe(session_id).to_csv(path, index=False)
    return send_file(path, as_attachment=True, download_name=f"results_{ts}.csv")


@app.route("/export/excel")
def export_excel():
    session_id = request.args.get("session_id", type=int)
    if not session_id and not state["places"]:
        return jsonify({"error": "No data"}), 400

    exports_dir = os.path.join(os.path.dirname(__file__), "exports")
    os.makedirs(exports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(exports_dir, f"results_{ts}.xlsx")
    _build_dataframe(session_id).to_excel(path, index=False, engine="openpyxl")
    return send_file(path, as_attachment=True, download_name=f"results_{ts}.xlsx")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    os.makedirs(os.path.join(os.path.dirname(__file__), "exports"),  exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "database"), exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
