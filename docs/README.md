# Documentation

This directory contains:

- **ARCHITECTURE.md** — System architecture, data flow, threat model
- **EVALUATION_PROTOCOL.md** — Test procedure, load profiles, acceptance criteria
- **SESSION_LOG.md** — Per-session metadata (date, machines, workstreams, results)
- **FINAL_REPORT.md** — Summary of findings, recommendations, lessons learned
- **CHARTS/** — Generated graphs and visualizations from analysis scripts

## Adding Documentation

During the hackathon, keep notes on:

1. **Architecture changes** — if shield policy or queuing strategy changes, update ARCHITECTURE.md
2. **Test runs** — after each k6/Locust run, update SESSION_LOG.md with metadata (date, host, generator, what was tested, key findings)
3. **Insights** — if you spot a trend or issue, add a note to FINAL_REPORT.md (under "Findings" section)

All documentation should assume readers are familiar with the codebase and focus on the *why* and *results*, not the *what* (code is the what).

## Session Log Format

When you run a test, add a row to SESSION_LOG.md:

```markdown
| 2026-09-08 | laptop-a (service) | laptop-b (loadgen) | baseline k6 profile | p95 latency 856ms, 98.5% success |
```

Columns: Date, Server Host/Role, Load Generator Host/Role, Test Type, Key Results.

