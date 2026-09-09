"""
Convert k6's built-in raw CSV output into the per-request CSV schema that
/analysis reads (see analysis/README.md "Input Format: Per-Request CSV").

Why this script exists: k6 (open-source, no custom Go build) cannot write an
arbitrary file from inside VU code, and per-VU in-memory arrays can't be combined
across VUs at the end of a run. The only built-in way to get every raw request
sample (not just the aggregate summary) is k6's own real-time output writer:

    k6 run --out csv=results/raw_<profile>_<timestamp>.csv loadgen/profiles/<profile>.js

That raw file has one row per METRIC SAMPLE (http_req_duration, http_reqs,
http_req_waiting, ...), so this script filters it down to one row per completed
HTTP request (the http_req_duration sample) and reshapes it into the schema
analyze.py / drift_check.py already read:

    timestamp,request_type,response_code,latency_ms,error_message,priority,server_url,run_order

`request_type` and `priority` come from the k6 script tagging each request with
`params.tags = { request_type: ..., priority: ... }` (see loadgen/profiles/*.js).
Verified against real k6 output (v2.2.0): custom tags do NOT get their own CSV
columns — they're packed into a single `extra_tags` column as a URL query string,
e.g. `request_type=completion&priority=legitimate`. This script parses that back
out; if some other k6 version instead gives each tag its own column, that's used
in preference (see parse_extra_tags/normalize below).

`run_order` is NOT per-request; it is the position of this whole run/round in the
session's chronological sequence (round 1, round 2, ...), passed in via --run-order.
CLAUDE.md calls for this because laptops thermal-throttle under sustained load, so
drift across runs needs to be visible in the data, not just inferred from filenames.

Usage:
    python loadgen/normalize_csv.py results/raw_baseline_20260908.csv \\
        results/run_20260908_baseline.csv --run-order 1
"""

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl


def k6_timestamp_to_iso(raw_timestamp):
    """k6's csv output writes unix seconds (sometimes with a fractional part)."""
    try:
        return datetime.fromtimestamp(float(raw_timestamp), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return ""


def parse_extra_tags(raw_value):
    """
    k6's csv output packs custom tags (anything set via params.tags in the script)
    into one 'extra_tags' column as a URL query string rather than giving each tag
    its own column — verified against real k6 v2.2.0 output, e.g.:
    'request_type=completion&priority=legitimate'. Parse that back into a dict.
    """
    if not raw_value:
        return {}
    return dict(parse_qsl(raw_value))


def normalize(raw_csv_path, out_csv_path, run_order):
    if not Path(raw_csv_path).exists():
        print(f"Error: raw k6 CSV not found: {raw_csv_path}")
        sys.exit(1)

    rows_written = 0
    with open(raw_csv_path, newline="") as raw_f, open(out_csv_path, "w", newline="") as out_f:
        reader = csv.DictReader(raw_f)
        writer = csv.writer(out_f)
        writer.writerow(
            [
                "timestamp",
                "request_type",
                "response_code",
                "latency_ms",
                "error_message",
                "priority",
                "server_url",
                "run_order",
            ]
        )

        for row in reader:
            # http_req_duration fires exactly once per completed HTTP request, which
            # is what makes it the right row to key one-CSV-row-per-request off of.
            if row.get("metric_name") != "http_req_duration":
                continue

            tags = parse_extra_tags(row.get("extra_tags", ""))
            # Prefer a dedicated column if some k6 version/config provides one;
            # otherwise fall back to the extra_tags blob (the common case).
            request_type = row.get("request_type") or tags.get("request_type", "")
            priority = row.get("priority") or tags.get("priority", "")

            writer.writerow(
                [
                    k6_timestamp_to_iso(row.get("timestamp")),
                    request_type,
                    row.get("status", ""),
                    row.get("metric_value", ""),
                    row.get("error", ""),
                    priority,
                    row.get("url", ""),
                    run_order,
                ]
            )
            rows_written += 1

    print(f"Wrote {rows_written} per-request rows to {out_csv_path} (run_order={run_order})")
    if rows_written == 0:
        print(
            "Warning: 0 rows written. Did the k6 run use --out csv=<raw file>, "
            "and did it complete at least one request?"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("raw_csv", help="k6's raw --out csv=<file> output")
    parser.add_argument("out_csv", help="Destination path for the analysis-ready CSV")
    parser.add_argument(
        "--run-order",
        type=int,
        required=True,
        help="Position of this run in the session's chronological sequence (1, 2, 3, ...)",
    )
    args = parser.parse_args()

    normalize(args.raw_csv, args.out_csv, args.run_order)
