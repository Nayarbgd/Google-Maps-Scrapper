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

app = Flask(__name__)
app.secret_key = "gmaps-scraper-2024"

state = {
    "places": [],
    "worker": None,
    "stop_event": threading.Event(),
    "queue": queue.Queue(),
    "running": False,
    "total_expected": 0,
    "session_id": None,
}

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Google Maps Business Scraper</title>
<style>
  :root {
    --bg:        #0f0f17;
    --sidebar:   #13131f;
    --card:      #1a1a2e;
    --card2:     #16213e;
    --border:    #2a2a45;
    --accent:    #4f8ef7;
    --accent-h:  #6ba3ff;
    --success:   #4ade80;
    --warning:   #facc15;
    --danger:    #f87171;
    --muted:     #6b7280;
    --text:      #e2e8f0;
    --text-dim:  #94a3b8;
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); font-size: 14px; }
  body { display: flex; overflow: hidden; height: 100vh; }

  /* ── Sidebar ─────────────────────────────── */
  #sidebar {
    width: 300px; min-width: 280px; background: var(--sidebar);
    display: flex; flex-direction: column; padding: 24px 0; border-right: 1px solid var(--border);
    overflow-y: auto;
  }
  .logo { padding: 0 24px 20px; }
  .logo h1 { font-size: 18px; font-weight: 700; color: var(--accent); letter-spacing: -0.3px; }
  .logo p  { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .sep { height: 1px; background: var(--border); margin: 4px 16px 16px; }
  .section-label { font-size: 10px; font-weight: 700; color: var(--muted); letter-spacing: 0.8px; padding: 0 24px 10px; text-transform: uppercase; }

  .field { padding: 0 16px 14px; }
  .field label { display: block; font-size: 12px; color: var(--text-dim); margin-bottom: 5px; }
  .field input {
    width: 100%; padding: 9px 12px; background: var(--card);
    border: 1px solid var(--border); border-radius: 8px; color: var(--text);
    font-size: 13px; outline: none; transition: border-color .15s;
  }
  .field input:focus { border-color: var(--accent); }
  .field input::placeholder { color: var(--muted); }

  .btn-group { padding: 4px 16px; display: flex; flex-direction: column; gap: 8px; }
  .btn-row { display: flex; gap: 8px; }
  button {
    flex: 1; padding: 10px 14px; border: none; border-radius: 10px;
    font-size: 13px; font-weight: 600; cursor: pointer; transition: background .15s, opacity .15s;
  }
  button:disabled { opacity: .4; cursor: not-allowed; }
  .btn-primary { background: var(--accent); color: #fff; font-size: 14px; padding: 12px; }
  .btn-primary:hover:not(:disabled) { background: var(--accent-h); }
  .btn-stop { background: #3b1f2b; color: var(--danger); border: 1px solid var(--danger); }
  .btn-stop:hover:not(:disabled) { background: #5a2d3e; }
  .btn-clear { background: var(--card); color: var(--text-dim); border: 1px solid var(--border); }
  .btn-clear:hover:not(:disabled) { background: var(--border); }
  .btn-export { background: #1a2e1a; color: var(--success); border: 1px solid var(--success); }
  .btn-export:hover:not(:disabled) { background: #243824; }

  .stats-card { margin: 16px; background: var(--card); border-radius: 12px; padding: 16px; }
  .stats-card .label { font-size: 10px; font-weight: 700; color: var(--muted); letter-spacing: .8px; text-transform: uppercase; margin-bottom: 12px; }
  .stats-row { display: flex; gap: 8px; }
  .stat { flex: 1; }
  .stat-num { font-size: 28px; font-weight: 800; line-height: 1; }
  .stat-lbl { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .stat-found .stat-num { color: var(--accent); }
  .stat-saved .stat-num { color: var(--success); }

  /* ── Main area ───────────────────────────── */
  #main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

  #progress-bar {
    background: var(--card); border-bottom: 1px solid var(--border);
    padding: 14px 20px 12px; flex-shrink: 0;
  }
  #status-text { font-size: 13px; color: var(--text-dim); margin-bottom: 8px; }
  .bar-row { display: flex; align-items: center; gap: 10px; }
  .bar-track { flex: 1; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }
  .bar-fill { height: 100%; width: 0%; background: var(--accent); border-radius: 4px; transition: width .4s ease; }
  #count-text { font-size: 13px; font-weight: 700; color: var(--accent); min-width: 54px; text-align: right; }

  /* ── Table ───────────────────────────────── */
  #table-wrap { flex: 1; overflow: auto; background: #12121e; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  thead th {
    position: sticky; top: 0; background: #0f1929;
    color: var(--accent); font-size: 11px; font-weight: 700; letter-spacing: .5px;
    text-transform: uppercase; padding: 10px 14px; text-align: left;
    border-bottom: 1px solid var(--border); white-space: nowrap;
  }
  tbody tr { border-bottom: 1px solid rgba(42,42,69,.5); }
  tbody tr:nth-child(even) { background: rgba(26,26,46,.4); }
  tbody tr:hover { background: rgba(79,142,247,.08); }
  tbody td { padding: 8px 14px; vertical-align: middle; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
  td.rating { color: var(--warning); font-weight: 600; }
  td.phone { color: #a78bfa; }
  td.website { color: var(--accent); }
  td.name { font-weight: 500; }
  .empty-state { text-align: center; padding: 60px 20px; color: var(--muted); }
  .empty-state .icon { font-size: 48px; margin-bottom: 12px; }
  .empty-state p { font-size: 14px; }

  /* ── Log panel ───────────────────────────── */
  #log-panel {
    height: 170px; flex-shrink: 0; background: var(--sidebar);
    border-top: 1px solid var(--border); display: flex; flex-direction: column;
  }
  #log-header { font-size: 10px; font-weight: 700; color: var(--muted); letter-spacing: .8px; padding: 10px 16px 4px; text-transform: uppercase; }
  #log-box {
    flex: 1; overflow-y: auto; padding: 0 16px 8px;
    font-family: 'Courier New', monospace; font-size: 11px; color: var(--text-dim); line-height: 1.6;
  }
  #log-box::-webkit-scrollbar { width: 4px; }
  #log-box::-webkit-scrollbar-track { background: transparent; }
  #log-box::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

  .tag { display: inline-block; padding: 1px 7px; border-radius: 99px; font-size: 10px; font-weight: 600; }
  .tag-warn { background: rgba(250,204,21,.15); color: var(--warning); }
  .tag-err  { background: rgba(248,113,113,.15); color: var(--danger); }
  .tag-ok   { background: rgba(74,222,128,.15); color: var(--success); }
  .scrollbar-thin::-webkit-scrollbar { width: 5px; }
  .scrollbar-thin::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>

<!-- ── SIDEBAR ─────────────────────────────── -->
<div id="sidebar">
  <div class="logo">
    <h1>🗺&nbsp; Maps Scraper</h1>
    <p>Google Maps Business Intelligence</p>
  </div>
  <div class="sep"></div>
  <div class="section-label">Search Parameters</div>

  <div class="field">
    <label>Business Keyword</label>
    <input id="inp-keyword" type="text" placeholder="e.g.  italian restaurant"/>
  </div>
  <div class="field">
    <label>Location</label>
    <input id="inp-location" type="text" placeholder="e.g.  Toronto, Canada"/>
  </div>
  <div class="field">
    <label>Max Results</label>
    <input id="inp-max" type="number" placeholder="e.g.  20" min="1" max="500" value="10"/>
  </div>

  <div class="sep"></div>

  <div class="btn-group">
    <button class="btn-primary" id="btn-start" onclick="startScrape()">▶&nbsp;&nbsp;Start Search</button>
    <div class="btn-row">
      <button class="btn-stop" id="btn-stop" onclick="stopScrape()" disabled>■&nbsp; Stop</button>
      <button class="btn-clear" id="btn-clear" onclick="clearResults()">✕&nbsp; Clear</button>
    </div>
    <div class="sep" style="margin:4px 0;"></div>
    <div class="btn-row">
      <button class="btn-export" id="btn-csv" onclick="exportData('csv')">⬇&nbsp; Export CSV</button>
      <button class="btn-export" id="btn-xlsx" onclick="exportData('excel')">⬇&nbsp; Excel</button>
    </div>
  </div>

  <div class="stats-card">
    <div class="label">Session Stats</div>
    <div class="stats-row">
      <div class="stat stat-found"><div class="stat-num" id="stat-found">0</div><div class="stat-lbl">Found</div></div>
      <div class="stat stat-saved"><div class="stat-num" id="stat-saved">0</div><div class="stat-lbl">Saved</div></div>
    </div>
  </div>
</div>

<!-- ── MAIN ────────────────────────────────── -->
<div id="main">
  <!-- Progress bar -->
  <div id="progress-bar">
    <div id="status-text">Ready — enter a query and press Start Search</div>
    <div class="bar-row">
      <div class="bar-track"><div class="bar-fill" id="bar-fill"></div></div>
      <div id="count-text">0 / 0</div>
    </div>
  </div>

  <!-- Results table -->
  <div id="table-wrap">
    <table id="results-table">
      <thead>
        <tr>
          <th style="min-width:200px">Business Name</th>
          <th style="min-width:130px">Phone</th>
          <th style="min-width:160px">Website</th>
          <th style="min-width:220px">Address</th>
          <th style="min-width:65px">Rating</th>
          <th style="min-width:75px">Reviews</th>
          <th style="min-width:130px">Category</th>
        </tr>
      </thead>
      <tbody id="results-body">
        <tr id="empty-row">
          <td colspan="7">
            <div class="empty-state">
              <div class="icon">🔍</div>
              <p>No results yet — enter a search query and press Start Search</p>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- Log panel -->
  <div id="log-panel">
    <div id="log-header">Activity Log</div>
    <div id="log-box"></div>
  </div>
</div>

<script>
let evtSource = null;
let rowCount = 0;

function ts() {
  return new Date().toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
}

function log(msg, type) {
  const box = document.getElementById('log-box');
  const line = document.createElement('div');
  let prefix = '';
  if (type === 'warn')    prefix = '<span class="tag tag-warn">WARN</span> ';
  else if (type === 'err') prefix = '<span class="tag tag-err">ERROR</span> ';
  else if (type === 'ok')  prefix = '<span class="tag tag-ok">OK</span> ';
  line.innerHTML = `<span style="color:#4a4a6a">[${ts()}]</span> ${prefix}${msg}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

function setStatus(msg, color) {
  const el = document.getElementById('status-text');
  el.textContent = msg;
  el.style.color = color || 'var(--text-dim)';
}

function setProgress(current, total) {
  const pct = total ? (current / total * 100) : 0;
  document.getElementById('bar-fill').style.width = pct + '%';
  document.getElementById('count-text').textContent = `${current} / ${total}`;
}

function addRow(place) {
  const tbody = document.getElementById('results-body');
  const empty = document.getElementById('empty-row');
  if (empty) empty.remove();

  rowCount++;
  const tr = document.createElement('tr');
  const rating = place.reviews_average ? `${parseFloat(place.reviews_average).toFixed(1)} ★` : '—';
  const reviews = place.reviews_count ? Number(place.reviews_count).toLocaleString() : '—';
  tr.innerHTML = `
    <td class="name" title="${esc(place.name)}">${esc(place.name)}</td>
    <td class="phone">${esc(place.phone_number || '—')}</td>
    <td class="website" title="${esc(place.website)}">${esc(place.website || '—')}</td>
    <td title="${esc(place.address)}">${esc(place.address || '—')}</td>
    <td class="rating">${rating}</td>
    <td>${reviews}</td>
    <td title="${esc(place.place_type)}">${esc(place.place_type || '—')}</td>
  `;
  tbody.appendChild(tr);
  tr.scrollIntoView({ block: 'nearest' });

  document.getElementById('stat-found').textContent = rowCount;
  document.getElementById('stat-saved').textContent = rowCount;
}

function esc(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function startScrape() {
  const keyword  = document.getElementById('inp-keyword').value.trim();
  const location = document.getElementById('inp-location').value.trim();
  const maxRes   = parseInt(document.getElementById('inp-max').value) || 10;

  if (!keyword) { alert('Please enter a business keyword.'); return; }

  const query = location ? `${keyword} in ${location}` : keyword;

  document.getElementById('btn-start').disabled = true;
  document.getElementById('btn-stop').disabled  = false;
  rowCount = 0;

  setStatus(`Launching browser — searching for: ${query}`, 'var(--warning)');
  setProgress(0, maxRes);
  log(`Starting scrape: "${query}" — up to ${maxRes} results`);

  await fetch('/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, total: maxRes })
  });

  if (evtSource) evtSource.close();
  evtSource = new EventSource('/stream');

  evtSource.addEventListener('progress', e => {
    const d = JSON.parse(e.data);
    addRow(d.place);
    setProgress(d.current, d.total);
    setStatus(`Scraping: ${d.place.name}`, 'var(--text)');
  });

  evtSource.addEventListener('log', e => {
    const d = JSON.parse(e.data);
    const t = d.msg.startsWith('WARNING') ? 'warn' : d.msg.startsWith('ERROR') ? 'err' : null;
    log(d.msg, t);
  });

  evtSource.addEventListener('done', e => {
    const d = JSON.parse(e.data);
    setStatus(`Complete — ${d.count} businesses found`, 'var(--success)');
    log(`Scrape complete. ${d.count} results collected.`, 'ok');
    document.getElementById('bar-fill').style.width = '100%';
    document.getElementById('btn-start').disabled = false;
    document.getElementById('btn-stop').disabled  = true;
    evtSource.close();
  });

  evtSource.addEventListener('stopped', () => {
    setStatus(`Stopped — ${rowCount} businesses collected`, 'var(--warning)');
    log(`Scrape stopped by user. ${rowCount} results collected.`, 'warn');
    document.getElementById('btn-start').disabled = false;
    document.getElementById('btn-stop').disabled  = true;
    evtSource.close();
  });

  evtSource.addEventListener('error_event', e => {
    const d = JSON.parse(e.data);
    setStatus(`Error: ${d.msg.slice(0, 80)}`, 'var(--danger)');
    log(`ERROR: ${d.msg}`, 'err');
    document.getElementById('btn-start').disabled = false;
    document.getElementById('btn-stop').disabled  = true;
    evtSource.close();
  });
}

async function stopScrape() {
  document.getElementById('btn-stop').disabled = true;
  setStatus('Stop requested — finishing current item…', 'var(--warning)');
  log('Stop requested by user.');
  await fetch('/stop', { method: 'POST' });
}

async function clearResults() {
  if (!confirm('Clear all results?')) return;
  await fetch('/clear', { method: 'POST' });
  document.getElementById('results-body').innerHTML = `
    <tr id="empty-row"><td colspan="7">
      <div class="empty-state"><div class="icon">🔍</div>
      <p>No results yet — enter a search query and press Start Search</p></div>
    </td></tr>`;
  rowCount = 0;
  document.getElementById('stat-found').textContent = '0';
  document.getElementById('stat-saved').textContent = '0';
  document.getElementById('bar-fill').style.width = '0%';
  document.getElementById('count-text').textContent = '0 / 0';
  document.getElementById('log-box').innerHTML = '';
  setStatus('Ready — enter a query and press Start Search', '');
}

function exportData(fmt) {
  if (rowCount === 0) { alert('No results to export yet.'); return; }
  window.location.href = `/export/${fmt}`;
}
</script>
</body>
</html>"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/start", methods=["POST"])
def start():
    if state["running"]:
        return jsonify({"ok": False, "msg": "Already running"})

    data = request.get_json()
    query = data.get("query", "")
    total = int(data.get("total", 10))

    state["places"] = []
    state["stop_event"].clear()
    state["queue"] = queue.Queue()
    state["running"] = True
    state["total_expected"] = total
    state["session_id"] = datetime.now().strftime("%Y%m%d_%H%M%S")

    state["worker"] = ScrapeWorker(query, total, state["queue"], state["stop_event"])
    state["worker"].start()

    return jsonify({"ok": True})


@app.route("/stop", methods=["POST"])
def stop():
    state["stop_event"].set()
    return jsonify({"ok": True})


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
                payload = json.dumps({"msg": msg[1]})
                yield f"event: log\ndata: {payload}\n\n"

            elif kind == "progress":
                _, current, total, place = msg
                state["places"].append(place)
                payload = json.dumps({
                    "current": current,
                    "total": total,
                    "place": asdict(place),
                })
                yield f"event: progress\ndata: {payload}\n\n"

            elif kind == "done":
                _, places = msg
                state["places"] = places
                state["running"] = False
                payload = json.dumps({"count": len(places)})
                yield f"event: done\ndata: {payload}\n\n"
                break

            elif kind == "stopped":
                state["running"] = False
                yield "event: stopped\ndata: {}\n\n"
                break

            elif kind == "error":
                state["running"] = False
                payload = json.dumps({"msg": msg[1]})
                yield f"event: error_event\ndata: {payload}\n\n"
                break

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/export/csv")
def export_csv():
    if not state["places"]:
        return jsonify({"error": "No data"}), 400

    import pandas as pd
    from dataclasses import asdict as _asdict

    exports_dir = os.path.join(os.path.dirname(__file__), "exports")
    os.makedirs(exports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(exports_dir, f"results_{ts}.csv")
    df = pd.DataFrame([_asdict(p) for p in state["places"]])
    df.to_csv(path, index=False)
    return send_file(path, as_attachment=True, download_name=f"results_{ts}.csv")


@app.route("/export/excel")
def export_excel():
    if not state["places"]:
        return jsonify({"error": "No data"}), 400

    import pandas as pd
    from dataclasses import asdict as _asdict

    exports_dir = os.path.join(os.path.dirname(__file__), "exports")
    os.makedirs(exports_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(exports_dir, f"results_{ts}.xlsx")
    df = pd.DataFrame([_asdict(p) for p in state["places"]])
    df.to_excel(path, index=False, engine="openpyxl")
    return send_file(path, as_attachment=True, download_name=f"results_{ts}.xlsx")


if __name__ == "__main__":
    os.makedirs(os.path.join(os.path.dirname(__file__), "exports"), exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), "database"), exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
