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

import json
import math
import os
import re
import time
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

load_dotenv()

SHIELD_URL = f"http://localhost:{os.environ.get('SHIELD_PORT', '9090')}"
LLAMA_SERVER_URL = os.environ.get("LLAMA_SERVER_URL", "").rstrip("/")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8765"))
LOG_PATH = Path(__file__).parent / "shield.log"
RESULTS_DIR = Path(__file__).parent.parent / "results"

app = FastAPI(title="Shield Dashboard")


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


@app.get("/api/state")
async def api_state():
    # Run all three checks concurrently, not sequentially -- with a 3s timeout
    # each, three sequential awaits against an unreachable host added up to a
    # ~6-7s response time in testing, which is much too slow for a 1s-refresh
    # live dashboard. Fixed and reverified before shipping.
    import asyncio

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

    recon = read_reconciliation_stats()

    return JSONResponse(
        {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "shield": {"url": SHIELD_URL, "up": bool(shield_health and shield_health["ok"] and shield_health["status"] == 200)},
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
            "recent_log": [line.rstrip("\n") for line in log_lines[-25:]],
            "reconciliation": recon,
        }
    )


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
    <div class="badge"><span id="dotLlama" class="dot"></span><span id="txtLlama">llama-server: checking...</span></div>
    <div class="badge"><span id="dotQueue" class="dot"></span><span id="txtQueue">queue: --</span></div>
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

async function tick(){
  if (frozen) return;
  document.getElementById('clock').textContent = new Date().toLocaleTimeString();

  let d;
  try {
    const res = await fetch('/api/state');
    d = await res.json();
  } catch (e) {
    return;
  }

  const dotShield = document.getElementById('dotShield');
  dotShield.className = 'dot ' + (d.shield.up ? '-up' : '-down');
  document.getElementById('txtShield').textContent = 'Shield: ' + (d.shield.up ? 'UP' : 'DOWN');

  const dotLlama = document.getElementById('dotLlama');
  dotLlama.className = 'dot ' + (d.llama_server.up ? '-up' : '-down');
  document.getElementById('txtLlama').textContent = 'llama-server: ' + (d.llama_server.up ? 'UP' : 'DOWN');

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
