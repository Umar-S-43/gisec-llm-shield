"""
Local web dashboard for watching the Shield's live activity and getting a
final report of how it performed, replacing the PowerShell dashboard for
anyone who'd rather have a browser tab than a terminal window.

Why a separate local server, not a hosted page: this needs to read
shield/shield.log off disk and reach llama-server on the local hotspot
network (10.185.191.x) -- neither is reachable from a page hosted outside
this machine. Run this, then open the URL it prints in any browser on THIS
machine (or another machine on the same hotspot, via this machine's IP).

Usage:
    python shield/dashboard_server.py
    # or, matching shield/main.py's own interpreter note:
    py -3.11 shield/dashboard_server.py

Runs on port 8765 by default (separate from the Shield's own 9090, so this
can run alongside it without conflict). Override with DASHBOARD_PORT.
"""

import asyncio
import json
import math
import os
import re
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

SHIELD_PORT = int(os.environ.get("SHIELD_PORT", "9090"))
SHIELD_URL = f"http://localhost:{SHIELD_PORT}"
LLAMA_SERVER_URL = os.environ.get("LLAMA_SERVER_URL", "").rstrip("/")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))
SHIELD_DIR = Path(__file__).parent
LOG_PATH = SHIELD_DIR / "shield.log"
RESULTS_DIR = SHIELD_DIR.parent / "results"

app = FastAPI(title="Shield Dashboard")

# History buffer for the queue-depth-over-time chart. Populated by a
# background poller (not by /api/state -- that only runs when a browser tab
# is open and polling; this keeps history even if nobody's watching for a
# stretch) so the chart isn't empty the moment someone opens the page after
# a test's been running a while. Capped at 600 points (10 min at 1s/point)
# so this can't grow unbounded over a long session.
_history: deque = deque(maxlen=600)

# Tracks a Shield process WE started, so /api/control/stop can terminate it
# directly. Not the only mechanism, though -- see kill_port_owner() below,
# which is needed regardless for orphaned/externally-started processes (this
# exact scenario happened live earlier this session: a Shield started from a
# separate terminal, invisible to this variable, kept the port occupied
# after being "stopped").
_shield_proc: subprocess.Popen | None = None


def wilson_ci(successes: int, n: int, confidence: float = 0.90) -> tuple[float, float]:
    """Wilson score interval, pure Python (no scipy/numpy dependency for this
    small standalone tool). z=1.6449 for the project's standard 90% CI."""
    if n == 0:
        return (0.0, 0.0)
    z = 1.6449 if abs(confidence - 0.90) < 1e-9 else 1.9600
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


async def fetch_json_or_none(url: str, timeout: float = 1.5):
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=timeout)
            return {"ok": True, "status": r.status_code, "text": r.text}
    except Exception:
        return {"ok": False, "status": None, "text": None}


def parse_metric(text: str | None, name: str) -> int | None:
    if not text:
        return None
    m = re.search(rf"^{re.escape(name)}\s+(\d+)", text, re.MULTILINE)
    return int(m.group(1)) if m else None


def latest_reconciliation_file() -> Path | None:
    if not RESULTS_DIR.exists():
        return None
    files = sorted(RESULTS_DIR.glob("shield_reconciliation_*.csv"), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def read_reconciliation_stats():
    f = latest_reconciliation_file()
    if not f:
        return None
    import csv

    rows = list(csv.DictReader(open(f, newline="")))
    if not rows:
        return None
    errs = [float(r["relative_error_pct"]) for r in rows]
    return {
        "file": f.name,
        "n": len(rows),
        "mean_signed_error_pct": round(sum(errs) / len(errs), 2),
        "mean_abs_error_pct": round(sum(abs(e) for e in errs) / len(errs), 2),
        "worst_case_pct": round(max(errs, key=abs), 2),
    }


async def gather_state(include_log_tail: bool = True) -> dict:
    """Shared by /api/state (on-demand, browser polling) and the background
    history poller (runs regardless of whether a browser tab is open) -- was
    duplicated between the two at first draft; pulled out to avoid the two
    copies drifting apart."""
    # Run all three checks concurrently, not sequentially -- with a 3s timeout
    # each, three sequential awaits against an unreachable host added up to a
    # ~6-7s response time in testing, which is much too slow for a 1s-refresh
    # live dashboard. Fixed and reverified before shipping.
    shield_health_task = fetch_json_or_none(f"{SHIELD_URL}/health")
    if LLAMA_SERVER_URL:
        llama_health_task = fetch_json_or_none(f"{LLAMA_SERVER_URL}/health")
        llama_metrics_task = fetch_json_or_none(f"{LLAMA_SERVER_URL}/metrics")
        shield_health, llama_health, llama_metrics = await asyncio.gather(
            shield_health_task, llama_health_task, llama_metrics_task
        )
    else:
        shield_health = await shield_health_task
        llama_health, llama_metrics = None, None

    deferred = parse_metric(llama_metrics["text"] if llama_metrics else None, "llamacpp:requests_deferred")
    processing = parse_metric(llama_metrics["text"] if llama_metrics else None, "llamacpp:requests_processing")

    log_lines: list[str] = []
    if LOG_PATH.exists():
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as f:
            log_lines = f.readlines()

    def count(pattern: str) -> int:
        rx = re.compile(pattern)
        return sum(1 for line in log_lines if rx.search(line))

    n_success = count(r'"POST /completion HTTP/1\.1" 200')
    n_429 = count(r"Token budget exceeded")
    n_503_deferred = count(r"Shedding load: requests_deferred")
    n_503_noslot = count(r"No slot available on llama-server")
    n_503_reservation = count(r"Slot reservation:")
    n_total_shed = n_429 + n_503_deferred + n_503_noslot + n_503_reservation
    n_total = n_success + n_total_shed

    success_ci = wilson_ci(n_success, n_total) if n_total else (0.0, 0.0)

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "shield": {
            "url": SHIELD_URL,
            "up": bool(shield_health and shield_health["ok"] and shield_health["status"] == 200),
        },
        "llama_server": {
            "url": LLAMA_SERVER_URL,
            "up": bool(llama_health and llama_health["ok"] and llama_health["status"] == 200),
            "requests_deferred": deferred,
            "requests_processing": processing,
        },
        "log_found": LOG_PATH.exists(),
        "counts": {
            "success_200": n_success,
            "shed_429_token_budget": n_429,
            "shed_503_deferred_queue": n_503_deferred,
            "shed_503_no_slot": n_503_noslot,
            "shed_503_slot_reservation": n_503_reservation,
            "total_shed": n_total_shed,
            "total_requests": n_total,
        },
        "success_rate": {
            "pct": round(100 * n_success / n_total, 1) if n_total else None,
            "ci_lower_pct": round(success_ci[0] * 100, 1),
            "ci_upper_pct": round(success_ci[1] * 100, 1),
        },
        "recent_log": [line.rstrip("\n") for line in log_lines[-25:]] if include_log_tail else [],
        "reconciliation": read_reconciliation_stats(),
    }


async def _history_poller():
    while True:
        try:
            s = await gather_state(include_log_tail=False)
            _history.append(
                {
                    "t": s["generated_at"],
                    "deferred": s["llama_server"]["requests_deferred"],
                    "processing": s["llama_server"]["requests_processing"],
                    "success_cum": s["counts"]["success_200"],
                    "shed_cum": s["counts"]["total_shed"],
                }
            )
        except Exception:
            pass
        await asyncio.sleep(1)


@app.on_event("startup")
async def _start_poller():
    asyncio.create_task(_history_poller())


@app.get("/api/state")
async def api_state():
    return JSONResponse(await gather_state())


@app.get("/api/history")
async def api_history():
    return JSONResponse(list(_history))


# --- Shield process control -------------------------------------------------
# Launching/stopping the Shield from the dashboard, requested after a real
# live incident this session: a Shield started from a separate terminal
# window kept an orphaned process holding port 9090 after being "stopped,"
# and a duplicate instance kept retrying and failing to bind every 2s,
# spamming the log. Both start and stop sweep the actual port owner (not
# just a tracked subprocess handle), which is the only thing that's robust
# against that exact scenario recurring.

def find_port_owner_pids(port: int) -> list[str]:
    """Windows-specific (this project runs on Windows laptops over a phone
    hotspot, per CLAUDE.md) -- parses `netstat -ano` for PIDs LISTENING on
    `port`. Returns [] if nothing is listening."""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return []
    pids = set()
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                pids.add(parts[-1])
    return list(pids)


def kill_port_owner(port: int) -> list[str]:
    killed = []
    for pid in find_port_owner_pids(port):
        try:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=5)
            killed.append(pid)
        except Exception:
            pass
    return killed


@app.post("/api/control/start")
async def control_start():
    global _shield_proc
    if find_port_owner_pids(SHIELD_PORT):
        return JSONResponse({"ok": False, "message": f"Port {SHIELD_PORT} is already in use -- Shield (or something) is already running. Use Reset if it's misbehaving."})

    _shield_proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=str(SHIELD_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await asyncio.sleep(1.5)
    up = bool(find_port_owner_pids(SHIELD_PORT))
    return JSONResponse({"ok": up, "message": "Shield started." if up else "Started the process but it doesn't appear to be listening yet -- check shield.log."})


@app.post("/api/control/stop")
async def control_stop():
    global _shield_proc
    if _shield_proc is not None:
        try:
            _shield_proc.terminate()
        except Exception:
            pass
        _shield_proc = None
    killed = kill_port_owner(SHIELD_PORT)
    return JSONResponse({"ok": True, "message": f"Stopped. Killed PIDs: {killed}" if killed else "Nothing was listening on that port."})


@app.post("/api/control/reset")
async def control_reset():
    """Stop whatever's running (tracked or orphaned), clear shield.log and
    the in-memory history buffer, then start fresh. This resets the Shield's
    OWN state only -- it does NOT and CANNOT reset llama-server's internal
    queue, which lives on a different machine entirely; the frontend says so
    explicitly rather than implying a full system reset."""
    global _shield_proc
    if _shield_proc is not None:
        try:
            _shield_proc.terminate()
        except Exception:
            pass
        _shield_proc = None
    kill_port_owner(SHIELD_PORT)
    await asyncio.sleep(0.5)

    if LOG_PATH.exists():
        LOG_PATH.write_text("", encoding="utf-8")
    _history.clear()

    _shield_proc = subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=str(SHIELD_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await asyncio.sleep(1.5)
    up = bool(find_port_owner_pids(SHIELD_PORT))
    return JSONResponse({"ok": up, "message": "Shield reset: log cleared, restarted fresh." if up else "Reset attempted but Shield doesn't appear to be listening -- check shield.log."})


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_PAGE


HTML_PAGE = r"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Shield Live Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root{
    --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --ink-muted:#898781;
    --grid:#e1e0d9; --border:rgba(11,11,11,.10);
    --blue:#2a78d6; --orange:#eb6834; --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b;
    --shadow:0 1px 2px rgba(11,11,11,.04), 0 6px 20px rgba(11,11,11,.05);
  }
  @media (prefers-color-scheme: dark){
    :root{ --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink-2:#c3c2b7; --ink-muted:#898781;
           --grid:#2c2c2a; --border:rgba(255,255,255,.10); --blue:#3987e5; --orange:#d95926; }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--plane);color:var(--ink);font-family:"IBM Plex Sans",system-ui,sans-serif;line-height:1.5}
  h1,h2{font-family:"Fraunces",Georgia,serif;margin:0}
  .mono{font-family:"IBM Plex Mono",monospace;font-variant-numeric:tabular-nums}
  .page{max-width:1000px;margin:0 auto;padding:36px 24px 80px}
  header{display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:28px}
  h1{font-size:28px;font-weight:600}
  #clock{font-family:"IBM Plex Mono";font-size:13px;color:var(--ink-muted)}
  .badges{display:flex;gap:10px;margin-bottom:24px;flex-wrap:wrap}
  .badge{display:flex;align-items:center;gap:8px;background:var(--surface);border:1px solid var(--border);
         border-radius:999px;padding:7px 14px;font-size:13px;box-shadow:var(--shadow)}
  .dot{width:9px;height:9px;border-radius:50%;background:var(--ink-muted)}
  .dot.-up{background:var(--good)} .dot.-down{background:var(--critical)}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
  @media (max-width:700px){.grid{grid-template-columns:1fr}}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:20px 22px;box-shadow:var(--shadow)}
  .card h2{font-size:15px;font-weight:600;margin-bottom:14px;color:var(--ink-muted);text-transform:uppercase;letter-spacing:.03em}
  .stat-row{display:flex;justify-content:space-between;padding:6px 0;font-size:14px;border-bottom:1px solid var(--grid)}
  .stat-row:last-child{border-bottom:none}
  .stat-row .v{font-family:"IBM Plex Mono";font-weight:600}
  .v.-good{color:var(--good)} .v.-warn{color:var(--warning)} .v.-bad{color:var(--critical)}
  #log{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px 20px;
       font-family:"IBM Plex Mono";font-size:12.5px;max-height:280px;overflow-y:auto;box-shadow:var(--shadow);margin-bottom:16px}
  #log div{padding:2px 0;white-space:pre-wrap;word-break:break-all}
  .log-err{color:var(--critical)} .log-warn{color:var(--warning)} .log-ok{color:var(--good)} .log-info{color:var(--ink-muted)}
  #report{margin-top:36px;padding-top:28px;border-top:2px solid var(--border)}
  #report h1{font-size:24px;margin-bottom:6px}
  #report .sub{color:var(--ink-muted);font-size:13.5px;margin-bottom:20px}
  .hero-row{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:20px}
  .hero{flex:1;min-width:180px;background:var(--surface);border:1px solid var(--border);border-radius:12px;
        padding:18px 20px;box-shadow:var(--shadow)}
  .hero .label{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--ink-muted);font-weight:500}
  .hero .value{font-family:"Fraunces";font-size:34px;font-weight:600;margin-top:6px}
  .hero .ci{font-size:12px;color:var(--ink-muted);margin-top:4px}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  thead th{text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.03em;color:var(--ink-muted);
            padding:0 10px 8px;border-bottom:1px solid var(--ink-muted)}
  tbody td{padding:9px 10px;border-bottom:1px solid var(--grid);font-family:"IBM Plex Mono"}
  tbody tr:last-child td{border-bottom:none}
  td.num{text-align:right}
  #snapshotBtn{background:var(--blue);color:#fff;border:none;border-radius:8px;padding:10px 18px;
               font-family:"IBM Plex Sans";font-weight:600;font-size:13.5px;cursor:pointer;margin-top:8px}
  #snapshotBtn:hover{opacity:.9}
  #snapshotNote{font-size:12.5px;color:var(--ink-muted);margin-top:8px}

  .controls{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px;align-items:center}
  .ctrl-btn{border:1px solid var(--border);border-radius:8px;padding:9px 16px;font-family:"IBM Plex Sans";
            font-weight:600;font-size:13.5px;cursor:pointer;background:var(--surface);color:var(--ink)}
  .ctrl-btn:hover{border-color:var(--ink-muted)}
  .ctrl-btn:disabled{opacity:.5;cursor:default}
  .ctrl-btn.-start{background:var(--good);color:#fff;border-color:transparent}
  .ctrl-btn.-stop{background:var(--critical);color:#fff;border-color:transparent}
  .ctrl-btn.-reset{background:var(--orange);color:#fff;border-color:transparent}
  #controlMsg{font-size:12.5px;color:var(--ink-muted)}
  #controlMsg.-err{color:var(--critical)}

  .chart-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
              padding:18px 22px;box-shadow:var(--shadow);margin-bottom:16px}
  .chart-card h2{font-size:13px;font-weight:600;margin-bottom:12px;color:var(--ink-muted);
                 text-transform:uppercase;letter-spacing:.03em}
  .chart-row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  @media (max-width:700px){.chart-row{grid-template-columns:1fr}}
  svg text{font-family:"IBM Plex Mono",monospace;font-size:10.5px;fill:var(--ink-muted)}
  .bar-label{font-family:"IBM Plex Sans",sans-serif;font-size:11.5px;fill:var(--ink);font-weight:500}
  .val-label{font-weight:600;fill:var(--ink);font-size:11px}
</style>
</head>
<body>
<div class="page">
  <header>
    <h1>Shield Live Dashboard</h1>
    <span id="clock" class="mono"></span>
  </header>

  <div class="badges">
    <div class="badge"><span id="dotShield" class="dot"></span><span id="txtShield">Shield: checking...</span></div>
    <div class="badge"><span id="dotQueue" class="dot"></span><span id="txtQueue">queue: --</span></div>
  </div>

  <div class="controls">
    <button class="ctrl-btn -start" id="btnStart">Start Shield</button>
    <button class="ctrl-btn -stop" id="btnStop">Stop Shield</button>
    <button class="ctrl-btn -reset" id="btnReset">Reset Shield (clear log + restart)</button>
    <span id="controlMsg"></span>
  </div>

  <div class="chart-card">
    <h2>Queue depth over time (requests_deferred, last 10 min)</h2>
    <div id="chartQueue"></div>
  </div>

  <div class="chart-row">
    <div class="chart-card">
      <h2>Defense firing breakdown</h2>
      <div id="chartDefense"></div>
    </div>
    <div class="chart-card">
      <h2>Response outcome composition</h2>
      <div id="chartOutcome"></div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <h2>Right now</h2>
      <div class="stat-row"><span>requests_deferred (queue depth)</span><span class="v mono" id="deferred">--</span></div>
      <div class="stat-row"><span>requests_processing (of 4 slots)</span><span class="v mono" id="processing">--</span></div>
    </div>
    <div class="card">
      <h2>Cumulative since Shield start</h2>
      <div class="stat-row"><span>200 Success</span><span class="v mono -good" id="c200">--</span></div>
      <div class="stat-row"><span>429 Token budget (Defense A)</span><span class="v mono" id="c429">--</span></div>
      <div class="stat-row"><span>503 Deferred queue (Defense B)</span><span class="v mono" id="c503a">--</span></div>
      <div class="stat-row"><span>503 No slot avail. (Defense B)</span><span class="v mono" id="c503b">--</span></div>
      <div class="stat-row"><span>503 Slot reservation (Defense C)</span><span class="v mono" id="c503c">--</span></div>
    </div>
  </div>

  <div class="card" style="margin-bottom:16px">
    <h2>Live log tail</h2>
    <div id="log"></div>
  </div>

  <div id="report">
    <h1>Final Report</h1>
    <div class="sub">Live-updating unless snapshotted below. All numbers computed directly from <span class="mono">shield/shield.log</span> and the Shield's own reconciliation CSV -- nothing simulated.</div>

    <div class="hero-row">
      <div class="hero">
        <div class="label">Total requests seen</div>
        <div class="value mono" id="rTotal">--</div>
      </div>
      <div class="hero">
        <div class="label">Success rate</div>
        <div class="value mono" id="rSuccessRate">--</div>
        <div class="ci" id="rSuccessCI"></div>
      </div>
      <div class="hero">
        <div class="label">Total shed</div>
        <div class="value mono" id="rShed">--</div>
      </div>
    </div>

    <table id="defenseTable">
      <thead><tr><th>Defense</th><th class="num">Fired</th><th class="num">Share of shed</th></tr></thead>
      <tbody></tbody>
    </table>

    <div id="reconSection" style="margin-top:18px"></div>

    <button id="snapshotBtn">Snapshot report (freeze at this moment)</button>
    <div id="snapshotNote"></div>
  </div>
</div>

<script>
let frozen = false;

function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;'); }

function classifyLine(line){
  if (line.includes('ERROR')) return 'log-err';
  if (line.includes('WARNING')) return 'log-warn';
  if (line.includes('" 200')) return 'log-ok';
  return 'log-info';
}

function renderQueueChart(history){
  const el = document.getElementById('chartQueue');
  if (!history.length) { el.innerHTML = '<div style="color:var(--ink-muted);font-size:13px;padding:20px 0">No history yet -- give it a few seconds.</div>'; return; }

  const w = 900, h = 160, padL = 34, padR = 10, padT = 10, padB = 20;
  const vals = history.map(p => p.deferred || 0);
  const maxV = Math.max(5, ...vals);
  const n = history.length;
  const x = i => padL + (n <= 1 ? 0 : (i/(n-1)) * (w - padL - padR));
  const y = v => padT + (h - padT - padB) * (1 - v/maxV);

  let path = vals.map((v,i) => `${i===0?'M':'L'} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  const gridLines = [0, 0.25, 0.5, 0.75, 1].map(f => {
    const yy = padT + (h-padT-padB)*(1-f);
    const val = Math.round(maxV*f);
    return `<line x1="${padL}" y1="${yy}" x2="${w-padR}" y2="${yy}" stroke="var(--grid)"/><text x="${padL-6}" y="${yy+3}" text-anchor="end">${val}</text>`;
  }).join('');

  el.innerHTML = `<svg viewBox="0 0 ${w} ${h}" width="100%" style="max-width:${w}px" role="img" aria-label="Line chart of queue depth over time">
    ${gridLines}
    <path d="${path}" fill="none" stroke="var(--blue)" stroke-width="2"/>
    <circle cx="${x(n-1)}" cy="${y(vals[n-1])}" r="3.5" fill="var(--blue)"/>
  </svg>`;
}

function renderBarChart(elId, rows, color){
  const el = document.getElementById(elId);
  const total = rows.reduce((s,r) => s + r[1], 0) || 1;
  const w = 440, barH = 22, gap = 10, padL = 190, padR = 50;
  const h = rows.length * (barH+gap);
  const maxV = Math.max(1, ...rows.map(r => r[1]));
  const bars = rows.map(([label, val], i) => {
    const y = i*(barH+gap);
    const bw = (w - padL - padR) * (val/maxV);
    return `<text class="bar-label" x="${padL-8}" y="${y+barH/2+4}" text-anchor="end">${label}</text>
      <rect x="${padL}" y="${y}" width="${bw}" height="${barH}" rx="3" fill="${color}"/>
      <text class="val-label" x="${padL+bw+8}" y="${y+barH/2+4}">${val} (${(100*val/total).toFixed(0)}%)</text>`;
  }).join('');
  el.innerHTML = `<svg viewBox="0 0 ${w} ${h+4}" width="100%" style="max-width:${w}px" role="img" aria-label="Bar chart">${bars}</svg>`;
}

function renderOutcomeStack(counts){
  const el = document.getElementById('chartOutcome');
  const segs = [
    ['Success', counts.success_200, 'var(--good)'],
    ['Token budget (429)', counts.shed_429_token_budget, 'var(--serious)'],
    ['Deferred queue (503)', counts.shed_503_deferred_queue, 'var(--warning)'],
    ['No slot (503)', counts.shed_503_no_slot, 'var(--critical)'],
    ['Slot reservation (503)', counts.shed_503_slot_reservation, 'var(--orange)'],
  ];
  const total = segs.reduce((s,r) => s+r[1], 0);
  if (!total) { el.innerHTML = '<div style="color:var(--ink-muted);font-size:13px;padding:20px 0">No requests yet.</div>'; return; }
  const w = 440, barH = 40, y = 10;
  let cx = 0;
  const rects = segs.filter(s=>s[1]>0).map(([label, val, color]) => {
    const bw = (w) * (val/total);
    const r = `<rect x="${cx}" y="${y}" width="${Math.max(0,bw-1)}" height="${barH}" fill="${color}"/>`;
    cx += bw;
    return r;
  }).join('');
  const legend = segs.filter(s=>s[1]>0).map(([label,val,color]) =>
    `<div style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--ink-2);margin-top:4px">
      <span style="width:9px;height:9px;border-radius:2px;background:${color};display:inline-block"></span>
      ${label} — ${val} (${(100*val/total).toFixed(1)}%)
    </div>`
  ).join('');
  el.innerHTML = `<svg viewBox="0 0 ${w} ${barH+y+4}" width="100%" style="max-width:${w}px" role="img" aria-label="Stacked bar of response outcomes">${rects}</svg>${legend}`;
}

async function tick(){
  if (frozen) return;
  document.getElementById('clock').textContent = new Date().toLocaleTimeString();

  let d, hist;
  try {
    const [res, hres] = await Promise.all([fetch('/api/state'), fetch('/api/history')]);
    d = await res.json();
    hist = await hres.json();
  } catch (e) {
    return;
  }

  renderQueueChart(hist);
  renderBarChart('chartDefense', [
    ['A — Token budget', d.counts.shed_429_token_budget],
    ['B — Deferred queue', d.counts.shed_503_deferred_queue],
    ['B — No slot avail.', d.counts.shed_503_no_slot],
    ['C — Slot reservation', d.counts.shed_503_slot_reservation],
  ], 'var(--orange)');
  renderOutcomeStack(d.counts);

  const dotShield = document.getElementById('dotShield');
  dotShield.className = 'dot ' + (d.shield.up ? '-up' : '-down');
  document.getElementById('txtShield').textContent = 'Shield: ' + (d.shield.up ? 'UP' : 'DOWN');

  const dq = d.llama_server.requests_deferred;
  const dotQueue = document.getElementById('dotQueue');
  dotQueue.className = 'dot ' + (dq === null ? '' : dq > 10 ? '-down' : dq > 0 ? '' : '-up');
  document.getElementById('txtQueue').textContent = 'queue: ' + (dq === null ? '--' : dq);

  document.getElementById('deferred').textContent = dq === null ? '--' : dq;
  document.getElementById('processing').textContent = d.llama_server.requests_processing === null ? '--' : d.llama_server.requests_processing + ' / 4';

  document.getElementById('c200').textContent = d.counts.success_200;
  document.getElementById('c429').textContent = d.counts.shed_429_token_budget;
  document.getElementById('c503a').textContent = d.counts.shed_503_deferred_queue;
  document.getElementById('c503b').textContent = d.counts.shed_503_no_slot;
  document.getElementById('c503c').textContent = d.counts.shed_503_slot_reservation;

  const logDiv = document.getElementById('log');
  logDiv.innerHTML = d.recent_log.map(l => `<div class="${classifyLine(l)}">${esc(l)}</div>`).join('');
  logDiv.scrollTop = logDiv.scrollHeight;

  document.getElementById('rTotal').textContent = d.counts.total_requests;
  document.getElementById('rShed').textContent = d.counts.total_shed;
  document.getElementById('rSuccessRate').textContent = d.success_rate.pct === null ? '--' : d.success_rate.pct + '%';
  document.getElementById('rSuccessCI').textContent = d.counts.total_requests
    ? `90% CI: ${d.success_rate.ci_lower_pct}–${d.success_rate.ci_upper_pct}%` : '';

  const tbody = document.querySelector('#defenseTable tbody');
  const shed = d.counts.total_shed || 1;
  const rows = [
    ['A — Token budget (429)', d.counts.shed_429_token_budget],
    ['B — Deferred queue threshold (503)', d.counts.shed_503_deferred_queue],
    ['B — No slot available (503)', d.counts.shed_503_no_slot],
    ['C — Slot reservation (503)', d.counts.shed_503_slot_reservation],
  ];
  tbody.innerHTML = rows.map(([name, n]) =>
    `<tr><td>${name}</td><td class="num">${n}</td><td class="num">${(100*n/shed).toFixed(1)}%</td></tr>`
  ).join('');

  const reconDiv = document.getElementById('reconSection');
  if (d.reconciliation) {
    const r = d.reconciliation;
    reconDiv.innerHTML = `<h2 style="font-size:15px;font-weight:600;color:var(--ink-muted);text-transform:uppercase;letter-spacing:.03em;margin-bottom:10px">Cost estimate accuracy</h2>
      <div class="stat-row"><span>Requests reconciled (${esc(r.file)})</span><span class="v mono">${r.n}</span></div>
      <div class="stat-row"><span>Mean absolute error</span><span class="v mono">${r.mean_abs_error_pct}%</span></div>
      <div class="stat-row"><span>Mean signed error</span><span class="v mono">${r.mean_signed_error_pct}%</span></div>`;
  } else {
    reconDiv.innerHTML = '';
  }
}

async function callControl(path, busyLabel){
  const msg = document.getElementById('controlMsg');
  const btns = document.querySelectorAll('.ctrl-btn');
  btns.forEach(b => b.disabled = true);
  msg.className = ''; msg.textContent = busyLabel;
  try {
    const res = await fetch(path, {method: 'POST'});
    const d = await res.json();
    msg.textContent = d.message;
    msg.className = d.ok ? '' : '-err';
  } catch (e) {
    msg.textContent = 'Request failed -- is the dashboard server itself still running?';
    msg.className = '-err';
  } finally {
    btns.forEach(b => b.disabled = false);
  }
}

document.getElementById('btnStart').addEventListener('click', () => callControl('/api/control/start', 'Starting...'));
document.getElementById('btnStop').addEventListener('click', () => callControl('/api/control/stop', 'Stopping...'));
document.getElementById('btnReset').addEventListener('click', () => {
  if (!confirm('This clears shield.log and restarts the Shield fresh. It does NOT reset llama-server\'s own queue (that\'s on a different machine). Continue?')) return;
  callControl('/api/control/reset', 'Resetting...');
});

document.getElementById('snapshotBtn').addEventListener('click', () => {
  frozen = !frozen;
  const btn = document.getElementById('snapshotBtn');
  const note = document.getElementById('snapshotNote');
  if (frozen) {
    btn.textContent = 'Resume live updates';
    note.textContent = 'Frozen at ' + new Date().toLocaleString() + ' -- numbers above are static until resumed.';
  } else {
    btn.textContent = 'Snapshot report (freeze at this moment)';
    note.textContent = '';
  }
});

tick();
setInterval(tick, 1000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    print(f"Shield dashboard: http://localhost:{DASHBOARD_PORT}")
    print(f"  (reachable from other machines on the hotspot too, via this machine's IP:{DASHBOARD_PORT})")
    uvicorn.run(app, host="0.0.0.0", port=DASHBOARD_PORT, log_config=None)
