#!/usr/bin/env bash
# Auto-restarting wrapper around `python shield/main.py`.
#
# Why this exists: on 2026-09-11, the Shield crashed mid-session with
# `OSError: [WinError 64] The specified network name is no longer available` --
# a Windows-level failure in uvicorn's own socket-accept loop, most likely a
# momentary phone-hotspot drop (see CLAUDE.md's own "ephemeral connectivity"
# section -- this project deliberately runs over unstable hotspot networking,
# not a code-level leak). A restart fixed it immediately, but nobody was
# watching the terminal at the time, so the Shield sat dead for a while before
# anyone noticed. This wrapper means a network blip costs a few seconds of
# downtime instead of an unnoticed dead Shield for the rest of a test run.
#
# This is NOT a fix for a crash-causing bug -- if the Shield is crashing
# because of a real exception in our own code, this will just restart it
# into the same bug on a loop. Watch the terminal output; a crash-restart
# loop with the SAME traceback repeating is a real bug, not a network blip.
#
# Usage (from repo root, same as the one-command start in shield/README.md):
#   ./shield/run_resilient.sh
#
# If your machine's `python` doesn't resolve to an interpreter with
# shield/requirements.txt installed (e.g. a too-new default Python with no
# prebuilt wheel for pydantic-core), override which interpreter to use:
#   PYTHON_BIN="py -3.11" ./shield/run_resilient.sh
#
# Stop with Ctrl+C -- the trap below breaks the restart loop instead of
# letting it immediately relaunch after the Ctrl+C kills the child process.

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

PYTHON_BIN="${PYTHON_BIN:-python}"

STOP=0
trap 'STOP=1; echo; echo "[run_resilient] Ctrl+C received, stopping after current process exits..."' INT TERM

restart_count=0
while [ "$STOP" -eq 0 ]; do
    start_ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "[run_resilient] $start_ts starting shield/main.py via '$PYTHON_BIN' (restart #$restart_count)"

    $PYTHON_BIN shield/main.py
    exit_code=$?

    if [ "$STOP" -eq 1 ]; then
        echo "[run_resilient] Stopped by user."
        break
    fi

    end_ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "[run_resilient] $end_ts shield/main.py exited (code $exit_code) -- restarting in 2s"
    restart_count=$((restart_count + 1))
    sleep 2
done
