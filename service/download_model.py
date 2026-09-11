#!/usr/bin/env python3
"""Download a quantized GGUF model for llama-server.

Usage:
    python service/download_model.py                    # default model (matches start.sh)
    python service/download_model.py --model qwen2.5-1.5b-instruct
    python service/download_model.py --model tinyllama --dir models

Stdlib only (urllib) so it runs on any laptop without pip installs.
Supports resume: re-running continues a partial download instead of starting over.
"""

import argparse
import hashlib
import os
import sys
import urllib.request

# Preset models. The DEFAULT must stay in sync with MODEL_PATH in service/start.sh
# and service/start.ps1 (see docs/MANUAL_CONFIG.md). Prefer a *small* instruct model
# on CPU-only laptops: load time and memory pressure must not dominate the experiment.
PRESETS = {
    "mistral-7b-instruct": {
        "url": "https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.1-GGUF/resolve/main/Mistral-7B-Instruct-v0.1.Q4_K_M.gguf",
        "filename": "Mistral-7B-Instruct-v0.1.Q4_K_M.gguf",
        "size_gb": 4.1,
        "sha256": None,  # fill in after first verified download if you want the check
        "note": "Default. Best quality, slowest on CPU; needs ~8 GB free RAM.",
    },
    "qwen2.5-1.5b-instruct": {
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size_gb": 0.99,
        "sha256": None,
        "note": "Recommended for weak laptops: fast load, still a real instruct model.",
    },
    "llama-3.2-3b-instruct": {
        "url": "https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "size_gb": 1.9,
        "sha256": None,
        "note": "Middle ground between the two above.",
    },
    "tinyllama": {
        "url": "https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "filename": "tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
        "size_gb": 0.67,
        "sha256": None,
        "note": "Smallest; only for very constrained machines. Weak answers, but fine for plumbing tests.",
    },
}

DEFAULT_PRESET = "mistral-7b-instruct"

CHUNK = 1 << 20  # 1 MiB


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def download(url: str, dest: str) -> None:
    """Download url to dest with HTTP Range resume."""
    have = os.path.getsize(dest) if os.path.exists(dest) else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    # HuggingFace resolve links redirect to a CDN; urllib follows redirects by default.
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = resp.headers.get("Content-Range")
        mode = "ab" if have and resp.status == 206 else "wb"
        if mode == "wb":
            have = 0
        print(f"Downloading -> {dest}  (resuming at {human(have)})" if have else f"Downloading -> {dest}")
        with open(dest, mode) as f:
            done = have
            while True:
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                print(f"\r  {human(done)}", end="", flush=True)
        print()


def verify_sha256(dest: str, expected: str) -> bool:
    h = hashlib.sha256()
    with open(dest, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    actual = h.hexdigest()
    ok = actual.lower() == expected.lower()
    print(f"SHA256: {'OK' if ok else 'MISMATCH'} ({actual})")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default=DEFAULT_PRESET, choices=sorted(PRESETS), help="preset to download")
    ap.add_argument("--dir", default="models", help="target directory (default: models/)")
    ap.add_argument("--list", action="store_true", help="list presets and exit")
    args = ap.parse_args()

    if args.list:
        for name, p in PRESETS.items():
            marker = " (default)" if name == DEFAULT_PRESET else ""
            print(f"{name}{marker}: {p['filename']} ~{p['size_gb']} GB — {p['note']}")
        return 0

    p = PRESETS[args.model]
    os.makedirs(args.dir, exist_ok=True)
    dest = os.path.join(args.dir, p["filename"])

    download(p["url"], dest)

    size = os.path.getsize(dest)
    print(f"Done: {dest} ({human(size)})")
    if p["sha256"]:
        if not verify_sha256(dest, p["sha256"]):
            print("ERROR: checksum mismatch — delete the file and re-download.", file=sys.stderr)
            return 1
    elif size < (p["size_gb"] * (1 << 30)) * 0.9:
        print("WARNING: file is much smaller than expected; the download may be truncated.", file=sys.stderr)
        return 1

    if args.model != DEFAULT_PRESET:
        print()
        print(f"NOTE: you downloaded '{args.model}', but start.sh/start.ps1 default to "
              f"'{PRESETS[DEFAULT_PRESET]['filename']}'. Either re-run with the default preset, or set "
              f"MODEL_PATH before starting, e.g.:")
        print(f"  MODEL_PATH={dest}   (bash)")
        print(f"  $env:MODEL_PATH = '{dest}'   (PowerShell)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
