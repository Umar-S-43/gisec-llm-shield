# Demo Control Panel

A very basic local web page with an "Attack" button, for live demos — press the button,
watch a real k6 attack run against the real server, see the legitimate-user survival
result once it finishes. Not part of the core CLAUDE.md deliverables (service/shield/
loadgen/analysis); this just wires a browser button to the existing loadgen scripts.

## Run it

```bash
python demo/server.py
```

Then open http://localhost:8888 in a browser. It reads `LLAMA_SERVER_URL` and
`SHIELD_URL` from the repo's `.env` — update `.env` first if those have changed this
session, same as every other component.

## What the button does

1. Launches `loadgen/profiles/probe.js` (the legitimate-user cohort) in the background.
2. Launches your chosen attack profile (`sustained.js`, `profile-d.js`, or `spike.js`)
   against either the server directly ("No Defense") or through the Shield
   ("Through Shield"), matching the toggle.
3. Waits for both (~2 minutes), converts the raw k6 output with
   `loadgen/normalize_csv.py` (same pipeline as every real test session), and shows
   legitimate-user survival %, request counts, median latency, and attack error rate.

Raw and normalized CSVs land in `/results/` with a `demo_` filename prefix, same
`.gitignore` rules as everything else in that folder (only normalized CSVs are small
enough to be worth committing, if you want to keep a demo run for the record).

## Requirements

- k6 installed (`winget install k6` on Windows) and reachable — checks PATH, then
  falls back to `C:\Program Files\k6\k6.exe`.
- `pandas` (already a dependency of `/analysis`).
- No other new dependencies — the server itself is pure Python standard library.

## Notes

- One attack at a time — the button disables itself while a run is in progress and
  the backend rejects a second `/api/start-attack` call with a 409 if you try anyway.
- This is a convenience tool for live demos, not a replacement for the properly
  interleaved, seeded, repeated-run methodology in `loadgen/run_comparison.sh` and
  `docs/EVALUATION_PROTOCOL.md` — don't cite numbers from this panel in the report
  as if they were a controlled comparison run.
