"""
Chart generation from per-request CSVs.

Usage:
    python analysis/charts.py results/run_*.csv --output docs/charts/
"""

import sys
import glob
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path


def generate_charts(csv_files, output_dir="docs/charts"):
    """Generate timeseries and distribution charts."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    for csv_file in csv_files:
        if not Path(csv_file).exists():
            print(f"Skipping {csv_file} (not found)")
            continue

        print(f"Generating charts from {csv_file}...")
        df = pd.read_csv(csv_file)

        # Latency timeseries (successful requests only)
        successful = df[df['response_code'] == 200]
        if len(successful) > 0:
            fig, ax = plt.subplots(figsize=(12, 6))
            successful.plot(x='timestamp', y='latency_ms', ax=ax, label='Latency (ms)')
            ax.set_title(f"Latency Over Time ({Path(csv_file).stem})")
            ax.set_xlabel("Time")
            ax.set_ylabel("Latency (ms)")
            ax.grid(True, alpha=0.3)
            chart_path = output_path / f"{Path(csv_file).stem}_latency.png"
            plt.savefig(chart_path)
            print(f"  Saved: {chart_path}")
            plt.close()

        # Response code distribution
        fig, ax = plt.subplots(figsize=(8, 6))
        df['response_code'].value_counts().plot(kind='bar', ax=ax)
        ax.set_title(f"Response Code Distribution ({Path(csv_file).stem})")
        ax.set_xlabel("Response Code")
        ax.set_ylabel("Count")
        chart_path = output_path / f"{Path(csv_file).stem}_responses.png"
        plt.savefig(chart_path)
        print(f"  Saved: {chart_path}")
        plt.close()

    print(f"\nCharts saved to {output_dir}/")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("csv_files", nargs="*", help="CSV files or glob pattern")
    parser.add_argument("--output", default="docs/charts", help="Output directory")
    args = parser.parse_args()

    if not args.csv_files:
        print("Usage: python charts.py <csv_files or pattern> --output <dir>")
        sys.exit(1)

    # Expand globs
    all_files = []
    for pattern in args.csv_files:
        all_files.extend(glob.glob(pattern))

    if not all_files:
        print("No CSV files found")
        sys.exit(1)

    generate_charts(all_files, args.output)
