// Shared summary formatter for all k6 load profiles.
//
// Non-negotiable (see CLAUDE.md): every run must report dropped_iterations next to
// latency, report p50/p95/p99 + Max, and must NEVER report standard deviation of
// latency (misleading for this kind of skewed, queue-driven data).
//
// dropped_iterations is what open-loop arrival-rate executors record when k6 could
// not start an iteration at its scheduled arrival time because all preAllocatedVUs/
// maxVUs were busy — i.e. the load generator itself detected the target had fallen
// behind. That is a first-class result, not an error to hide.

export function summaryReport(data, scenarioName) {
    const m = data.metrics;

    const httpDuration = m.http_req_duration ? m.http_req_duration.values : {};
    const dropped = m.dropped_iterations ? m.dropped_iterations.values.count : 0;
    const iterations = m.iterations ? m.iterations.values.count : 0;
    const failed = m.http_req_failed ? m.http_req_failed.values.rate : null;

    const result = {
        scenario: scenarioName,
        timestamp: new Date().toISOString(),
        iterations_completed: iterations,
        dropped_iterations: dropped,
        dropped_iteration_rate: iterations + dropped > 0 ? dropped / (iterations + dropped) : 0,
        http_req_failed_rate: failed,
        latency_ms: {
            p50: httpDuration['med'] ?? httpDuration['p(50)'] ?? null,
            p95: httpDuration['p(95)'] ?? null,
            p99: httpDuration['p(99)'] ?? null,
            max: httpDuration['max'] ?? null,
            // Deliberately no 'stddev' key here — see file header.
        },
    };

    const text = [
        `\n=== ${scenarioName} summary ===`,
        `Iterations completed: ${result.iterations_completed}`,
        `Dropped iterations:   ${result.dropped_iterations} (${(result.dropped_iteration_rate * 100).toFixed(1)}%)  <-- report this next to every latency number`,
        `HTTP error rate:      ${result.http_req_failed_rate !== null ? (result.http_req_failed_rate * 100).toFixed(1) + '%' : 'n/a'}`,
        `Latency p50/p95/p99/max (ms): ${result.latency_ms.p50 ?? 'n/a'} / ${result.latency_ms.p95 ?? 'n/a'} / ${result.latency_ms.p99 ?? 'n/a'} / ${result.latency_ms.max ?? 'n/a'}`,
        '',
    ].join('\n');

    // Paths are relative to k6's working directory. README instructs running k6 from
    // the repo root (`k6 run loadgen/profiles/baseline.js`), so this lands in /results.
    return {
        stdout: text,
        [`results/k6_${scenarioName}_${Date.now()}.json`]: JSON.stringify(result, null, 2),
    };
}
