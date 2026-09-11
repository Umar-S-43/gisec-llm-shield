"""
Very basic local demo control panel: a web page with an "Attack" button that
launches the same k6 attack + probe combo used in the real test sessions
(see docs/SESSION_LOG.md), with LIVE stats and charts while it runs (not just
a final summary), and shows the legitimate-user survival result once it
finishes.

This is a demo/presentation convenience, not part of the core CLAUDE.md
deliverables (service/shield/loadgen/analysis) -- it just wires a button to
the existing loadgen scripts and analysis pipeline so a live demo doesn't
require typing commands in front of judges.

Zero new dependencies: pure standard library (http.server, threading,
subprocess, csv) plus pandas, which /analysis already depends on. Live stats
work by TAILING k6's --out csv=<file> output while it's still being written
(k6 flushes rows incrementally), not by waiting for the process to finish.

Usage:
    python demo/server.py
    (then open http://localhost:8888 in a browser)

Reads LLAMA_SERVER_URL and SHIELD_URL from the repo's .env (same file every
other component reads) -- update .env before starting this, not this script.
"""

import csv
import io
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
LOADGEN_DIR = REPO_ROOT / "loadgen"
RESULTS_DIR = REPO_ROOT / "results"
DEMO_PORT = 8888
POLL_INTERVAL_S = 1.0

PROFILES = {
    "sustained": {
        "label": "Sustained Flood (50 req/s)",
        "script": LOADGEN_DIR / "profiles" / "sustained.js",
    },
    "profile-d": {
        "label": "Slow / High-Cost (Profile D)",
        "script": LOADGEN_DIR / "profiles" / "profile-d.js",
    },
    "spike": {
        "label": "Sudden Spike",
        "script": LOADGEN_DIR / "profiles" / "spike.js",
    },
}

STATE_LOCK = threading.Lock()
STATE = {
    "running": False,
    "target": None,
    "profile": None,
    "started_at": None,
    "live": None,
    "result": None,
    "error": None,
}


def load_env_file(path: Path) -> dict:
    """Minimal .env parser -- avoids adding python-dotenv as a dependency."""
    env = {}
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip()
    return env


def find_k6() -> str:
    found = shutil.which("k6")
    if found:
        return found
    windows_default = Path(r"C:\Program Files\k6\k6.exe")
    if windows_default.exists():
        return str(windows_default)
    raise RuntimeError(
        "k6 executable not found on PATH or at the default Windows install "
        "location. Install it (winget install k6) or add it to PATH."
    )


class CsvTailer:
    """
    Incrementally reads NEW lines appended to a growing CSV file (k6's
    --out csv=<file> writes rows as the run progresses, not all at once at
    the end). Keeps only http_req_duration rows -- same filter
    loadgen/normalize_csv.py uses -- since that's the one row-per-request
    metric. Re-reading only new bytes each poll (not the whole file) keeps
    this cheap even once the file grows into the megabytes on a long flood.
    """

    def __init__(self, path: Path):
        self.path = path
        self._offset = 0
        self._buffer = ""
        self._header = None
        self.rows = []  # list of dicts: timestamp, status, metric_value

    def poll(self):
        if not self.path.exists():
            return
        with open(self.path, "r", newline="", encoding="utf-8", errors="replace") as f:
            f.seek(self._offset)
            new_data = f.read()
            self._offset = f.tell()

        if not new_data:
            return
        self._buffer += new_data
        lines = self._buffer.split("\n")
        self._buffer = lines[-1]  # last (possibly incomplete) line, keep for next poll
        for line in lines[:-1]:
            if not line.strip():
                continue
            parsed = next(csv.reader(io.StringIO(line)), None)
            if parsed is None:
                continue
            if self._header is None:
                self._header = parsed
                continue
            row = dict(zip(self._header, parsed))
            if row.get("metric_name") == "http_req_duration":
                self.rows.append(row)

    def code_counts(self) -> dict:
        counts = {}
        for row in self.rows:
            code = row.get("status") or "0"
            counts[code] = counts.get(code, 0) + 1
        return counts

    @property
    def total(self) -> int:
        return len(self.rows)

    @property
    def success(self) -> int:
        return sum(1 for r in self.rows if r.get("status") == "200")


def run_attack(target_url: str, profile_key: str, rate: int = None):
    """
    Runs in a background thread. Launches attack + probe concurrently against
    target_url, polls both raw CSVs every POLL_INTERVAL_S while they run to
    update STATE["live"] for the frontend's live stats/charts, then -- once
    both finish -- normalizes the CSVs with the same pipeline every real test
    session uses and computes the final summary.
    """
    try:
        k6_bin = find_k6()
        profile = PROFILES[profile_key]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        RESULTS_DIR.mkdir(exist_ok=True)

        raw_attack = RESULTS_DIR / f"raw_demo_{profile_key}_attack_{timestamp}.csv"
        raw_probe = RESULTS_DIR / f"raw_demo_{profile_key}_probe_{timestamp}.csv"

        probe_env = {**os.environ, "LLAMA_SERVER_URL": target_url, "PROBE_DURATION": "2m"}
        attack_env = {**os.environ, "LLAMA_SERVER_URL": target_url}
        if rate and profile_key == "sustained":
            # sustained.js reads SUSTAINED_RATE (env-overridable, added so rate
            # sweeps don't require editing the script each time).
            attack_env["SUSTAINED_RATE"] = str(rate)

        probe_proc = subprocess.Popen(
            [k6_bin, "run", "--out", f"csv={raw_probe}", str(LOADGEN_DIR / "profiles" / "probe.js")],
            cwd=REPO_ROOT, env=probe_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        attack_proc = subprocess.Popen(
            [k6_bin, "run", "--out", f"csv={raw_attack}", str(profile["script"])],
            cwd=REPO_ROOT, env=attack_env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

        attack_tailer = CsvTailer(raw_attack)
        probe_tailer = CsvTailer(raw_probe)
        start_time = time.time()
        last_poll = {"t": start_time, "attack_total": 0, "probe_total": 0}

        while attack_proc.poll() is None or probe_proc.poll() is None:
            time.sleep(POLL_INTERVAL_S)
            attack_tailer.poll()
            probe_tailer.poll()

            now = time.time()
            dt = max(now - last_poll["t"], 0.001)
            attack_rate = (attack_tailer.total - last_poll["attack_total"]) / dt
            last_poll = {"t": now, "attack_total": attack_tailer.total, "probe_total": probe_tailer.total}

            probe_total = probe_tailer.total
            probe_success = probe_tailer.success
            live = {
                "elapsed_seconds": round(now - start_time, 1),
                "attack_total": attack_tailer.total,
                "attack_rate_per_sec": round(attack_rate, 1),
                "attack_codes": attack_tailer.code_counts(),
                "probe_total": probe_total,
                "probe_success": probe_success,
                "probe_survival_pct": round(100 * probe_success / probe_total, 1) if probe_total else None,
                "probe_codes": probe_tailer.code_counts(),
            }
            with STATE_LOCK:
                if not STATE["running"]:
                    break  # a stop/reset happened; abandon this run's updates
                STATE["live"] = live

        # Make sure both have fully exited (should already be true from the loop condition).
        attack_proc.wait()
        probe_proc.wait()

        # Final pass: reuse the exact same normalize_csv.py pipeline every real
        # test session uses, rather than trusting the incremental tailer's view
        # (which could miss a few trailing rows flushed right at process exit).
        sys.path.insert(0, str(LOADGEN_DIR))
        import normalize_csv  # noqa: E402

        norm_attack = RESULTS_DIR / f"run_demo_{profile_key}_attack_{timestamp}.csv"
        norm_probe = RESULTS_DIR / f"run_demo_{profile_key}_probe_{timestamp}.csv"
        normalize_csv.normalize(str(raw_attack), str(norm_attack), run_order=1)
        normalize_csv.normalize(str(raw_probe), str(norm_probe), run_order=1)

        probe_df = pd.read_csv(norm_probe)
        attack_df = pd.read_csv(norm_attack)

        total_probe = len(probe_df)
        success_probe = int((probe_df["response_code"] == 200).sum())
        survival_pct = round(100 * success_probe / total_probe, 1) if total_probe else 0.0
        code_counts = {str(int(k)): int(v) for k, v in probe_df["response_code"].value_counts().to_dict().items()}
        successful_latencies = probe_df.loc[probe_df["response_code"] == 200, "latency_ms"]
        median_latency = round(float(successful_latencies.median()), 0) if len(successful_latencies) else None

        result = {
            "target": target_url,
            "profile": f"Sustained Flood ({rate} req/s)" if (rate and profile_key == "sustained") else profile["label"],
            "probe_total": total_probe,
            "probe_success": success_probe,
            "survival_pct": survival_pct,
            "probe_response_codes": code_counts,
            "probe_median_latency_ms": median_latency,
            "attack_total": len(attack_df),
            "attack_error_pct": round(100 * (attack_df["response_code"] != 200).mean(), 1) if len(attack_df) else None,
        }

        with STATE_LOCK:
            STATE["running"] = False
            STATE["result"] = result
            STATE["error"] = None

    except Exception as e:  # noqa: BLE001
        with STATE_LOCK:
            STATE["running"] = False
            STATE["error"] = str(e)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep stdout quiet

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            html_path = Path(__file__).parent / "index.html"
            body = html_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/status":
            with STATE_LOCK:
                elapsed = None
                if STATE["running"] and STATE["started_at"]:
                    elapsed = round(time.time() - STATE["started_at"], 1)
                self._send_json(
                    {
                        "running": STATE["running"],
                        "target": STATE["target"],
                        "profile": STATE["profile"],
                        "elapsed_seconds": elapsed,
                        "live": STATE["live"],
                        "result": STATE["result"],
                        "error": STATE["error"],
                    }
                )
        elif self.path == "/api/config":
            env = load_env_file(REPO_ROOT / ".env")
            self._send_json(
                {
                    "llama_server_url": env.get("LLAMA_SERVER_URL", ""),
                    "shield_url": env.get("SHIELD_URL", ""),
                    "profiles": {k: v["label"] for k, v in PROFILES.items()},
                }
            )
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/start-attack":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            mode = body.get("mode", "shield")  # "shield" or "direct"
            profile_key = body.get("profile", "sustained")
            rate = body.get("rate")  # requests/sec override, sustained.js only; None = script default (50)

            with STATE_LOCK:
                if STATE["running"]:
                    self._send_json({"status": "already_running"}, status=409)
                    return

                env = load_env_file(REPO_ROOT / ".env")
                target_url = env.get("SHIELD_URL") if mode == "shield" else env.get("LLAMA_SERVER_URL")
                if not target_url:
                    self._send_json(
                        {"status": "error", "message": f"{'SHIELD_URL' if mode == 'shield' else 'LLAMA_SERVER_URL'} not set in .env"},
                        status=400,
                    )
                    return
                if profile_key not in PROFILES:
                    self._send_json({"status": "error", "message": f"unknown profile {profile_key}"}, status=400)
                    return
                if rate is not None:
                    try:
                        rate = int(rate)
                        if rate <= 0 or rate > 1000:
                            raise ValueError
                    except (TypeError, ValueError):
                        self._send_json({"status": "error", "message": "rate must be an integer between 1 and 1000"}, status=400)
                        return

                label = PROFILES[profile_key]["label"]
                if rate is not None and profile_key == "sustained":
                    label = f"Sustained Flood ({rate} req/s)"

                STATE["running"] = True
                STATE["target"] = target_url
                STATE["profile"] = label
                STATE["started_at"] = time.time()
                STATE["live"] = None
                STATE["result"] = None
                STATE["error"] = None

            thread = threading.Thread(target=run_attack, args=(target_url, profile_key, rate), daemon=True)
            thread.start()
            self._send_json({"status": "started", "target": target_url, "profile": label})
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", DEMO_PORT), Handler)
    print(f"Demo control panel running at http://localhost:{DEMO_PORT}")
    print("Reading LLAMA_SERVER_URL / SHIELD_URL from .env at repo root.")
    server.serve_forever()
