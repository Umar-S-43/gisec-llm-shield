"""
Generates the figures embedded in docs/FINAL_REPORT.tex, as PDF (vector,
best for pdflatex embedding). Every number here matches a number already
reported and verified elsewhere in docs/SESSION_LOG.md and
docs/FINAL_REPORT.tex -- this script does not compute anything new, it only
visualizes results already established.

Usage:
    python docs/generate_figures.py
Output:
    docs/figures/*.pdf
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

FIG_DIR = Path(__file__).parent / "figures"
FIG_DIR.mkdir(exist_ok=True)

# Colorblind-safe, print-safe palette (Okabe-Ito).
BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"
RED = "#D55E00"
GRAY = "#666666"

plt.rcParams.update({
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
})


def fig1_defense_evolution():
    """Legitimate survival across the defense-evolution timeline (Section: Results)."""
    labels = ["No Attack\n(baseline)", "Attack,\nno Shield", "Attack, Shield\n(buggy)", "Attack, Shield\n(fixed)"]
    values = [100.0, 2.2, 17.3, 60.0]
    # Wilson 90% CIs; baseline has no attack so no meaningful CI reported (n=31, 100%)
    ci_lower = [100.0, 0.5, 10.4, 49.4]
    ci_upper = [100.0, 9.4, 27.5, 69.8]
    err_lower = [v - l for v, l in zip(values, ci_lower)]
    err_upper = [u - v for v, u in zip(values, ci_upper)]

    fig, ax = plt.subplots(figsize=(6.5, 4))
    colors = [GRAY, RED, ORANGE, GREEN]
    bars = ax.bar(labels, values, color=colors, width=0.6)
    ax.errorbar(labels, values, yerr=[err_lower, err_upper], fmt="none", ecolor="black", capsize=5, linewidth=1.2)
    for bar, v in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 3, f"{v:.1f}%", ha="center", fontsize=10, fontweight="bold")

    ax.set_ylabel("Legitimate probe survival rate (%)")
    ax.set_ylim(0, 110)
    ax.set_title("Legitimate Survival Across the Defense-Evolution Timeline", fontsize=12)
    fig.text(0.5, 0.955, "Same attack profile (sustained.js, 50 req/s); error bars = 90% Wilson CI",
              ha="center", fontsize=8.5, color=GRAY)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(FIG_DIR / "fig1_defense_evolution.pdf")
    plt.close(fig)


def fig2_fraction_sweep():
    """Slot-reservation fraction sweep: rate-independence at 0.5, and the 1.0 jump."""
    rates = ["3", "10", "50", "150"]
    fraction_05 = [54.1, 50.8, 58.3, 50.8]

    fig, ax = plt.subplots(figsize=(6.5, 4))
    x = np.arange(len(rates))
    bars = ax.bar(x, fraction_05, color=BLUE, width=0.5, label="Fraction = 0.5 (default)")
    for xi, v in zip(x, fraction_05):
        ax.text(xi, v + 2, f"{v:.1f}%", ha="center", fontsize=10)

    # fraction=1.0 shown as a horizontal reference line (only measured at 3 req/s)
    ax.axhline(96.7, color=GREEN, linestyle="--", linewidth=2, label="Fraction = 1.0 (measured at 3 req/s)")
    ax.text(len(rates) - 0.5, 98.5, "96.7%", color=GREEN, fontsize=10, fontweight="bold", ha="right")

    ax.set_xticks(x)
    ax.set_xticklabels([f"{r} req/s" for r in rates])
    ax.set_ylabel("Legitimate probe survival rate (%)")
    ax.set_ylim(0, 110)
    ax.set_title("Slot-Reservation Fraction Sweep", fontsize=12)
    fig.text(0.5, 0.955, "Survival is rate-independent at a fixed fraction; raising it recovers far more",
              ha="center", fontsize=8.5, color=GRAY)
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(FIG_DIR / "fig2_fraction_sweep.pdf")
    plt.close(fig)


def fig3_spoofing_and_mitigation():
    """Identity spoofing vulnerability and per-identity-cap mitigation."""
    labels = [
        "Profile D\n(unspoofed)",
        "Profile D, spoofed\n(same machine, no cap)",
        "Sustained flood, spoofed,\n+cap, same IP",
        "Sustained flood, spoofed,\n+cap, separate IP",
        "Profile D, spoofed,\n+cap, separate IP (2 min)",
        "Profile D, spoofed,\n+cap, separate IP (5 min)",
    ]
    values = [98.4, 9.8, 1.6, 49.2, 35.0, 49.0]
    colors = [GREEN, RED, RED, GREEN, ORANGE, GREEN]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(range(len(labels)), values, color=colors, width=0.6)
    for i, v in enumerate(values):
        ax.text(i, v + 2, f"{v:.1f}%", ha="center", fontsize=9, fontweight="bold")

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=9, rotation=20, ha="right")
    ax.set_ylabel("Legitimate probe survival rate (%)")
    ax.set_ylim(0, 112)
    ax.set_title("Identity Spoofing: Vulnerability and Per-Identity-Cap Mitigation", fontsize=12)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "fig3_spoofing_mitigation.pdf")
    plt.close(fig)


def fig4_economics():
    """Economic framing formulas, log-scale (values span cents to hundreds of dollars)."""
    labels = ["GPU-hour cost\n/ request", "Cost per\n1,000 tokens", "Denial-of-wallet\nexposure / hour"]
    values = [0.001188, 0.01197, 252.29]

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar(labels, values, color=[BLUE, BLUE, RED], width=0.5)
    ax.set_yscale("log")
    for bar, v in zip(bars, values):
        label = f"${v:.6f}" if v < 1 else f"${v:.2f}"
        ax.text(bar.get_x() + bar.get_width() / 2, v * 1.3, label, ha="center", fontsize=10, fontweight="bold")

    ax.set_ylabel("USD (log scale)")
    ax.set_title("Economic Framing: Cost and Denial-of-Wallet Exposure", fontsize=12)
    fig.text(0.5, 0.955, "GPU-hour figures are a labeled cost substitution, see report text",
              ha="center", fontsize=8.5, color=GRAY)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(FIG_DIR / "fig4_economics.pdf")
    plt.close(fig)


if __name__ == "__main__":
    fig1_defense_evolution()
    fig2_fraction_sweep()
    fig3_spoofing_and_mitigation()
    fig4_economics()
    print(f"Generated 4 figures in {FIG_DIR}/")
    for f in sorted(FIG_DIR.glob("*.pdf")):
        print(f"  {f.name}")
