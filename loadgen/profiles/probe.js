import http from 'k6/http';
import { check } from 'k6';
import { summaryReport } from './lib/summary.js';

// Legitimate probe cohort — a small, constant-rate stream of realistic "real user"
// traffic that MUST run concurrently alongside every attack profile (B, C, D).
//
// Non-negotiable (see CLAUDE.md): every attack run reports whether this cohort
// survived. Run this in a second k6 process at the same time as spike/sustained/
// profile-d, e.g.:
//
//   k6 run loadgen/profiles/sustained.js &
//   k6 run loadgen/profiles/probe.js
//
// Both target the SAME server/shield URL and the SAME time window so the probe's
// success rate directly measures "did the real user survive the attack."
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

// preAllocatedVUs sizing formula (kickoff doc, not a guess):
//   preAllocatedVUs = ceil(median_iteration_duration_seconds * rate) + buffer_for_variance
// Rate here is ~0.5 req/s (1 per 2s). MEDIAN_ITERATION_S is an ESTIMATE (n_predict=30,
// small prompt) until Day 1's session measures the real value — override via
// PROBE_MEDIAN_ITERATION_S once that exists.
const RATE_PER_SECOND = 0.5;
const MEDIAN_ITERATION_S = Number(__ENV.PROBE_MEDIAN_ITERATION_S || 3);
const BUFFER_FOR_VARIANCE = 4;
const PRE_ALLOCATED_VUS = Math.ceil(MEDIAN_ITERATION_S * RATE_PER_SECOND) + BUFFER_FOR_VARIANCE;

export const options = {
    scenarios: {
        legitimate_probe: {
            executor: 'constant-arrival-rate',
            rate: 1,                  // deliberately small and constant
            timeUnit: '2s',           // ~0.5 req/sec
            duration: __ENV.PROBE_DURATION || '2m',
            preAllocatedVUs: PRE_ALLOCATED_VUS,
            maxVUs: PRE_ALLOCATED_VUS * 2,
        },
    },
    thresholds: {
        // This is the assertion that actually matters for the whole project's thesis:
        // the legitimate user should survive even while an attack is running.
        http_req_failed: ['rate<0.05'],
    },
};

export default function () {
    const payload = JSON.stringify({
        prompt: 'What time zone is Dubai in?',
        n_predict: 30,
    });

    const params = {
        headers: {
            'Content-Type': 'application/json',
            'X-Priority': 'legitimate',
        },
        tags: {
            request_type: 'completion',
            priority: 'legitimate',
        },
        // Must stay comfortably ABOVE the Shield's forward timeout (130.0s in
        // shield/main.py's _do_forward) — otherwise k6 gives up on a legitimate
        // request before the Shield could still deliver a real answer, and it
        // misreads as a Shield/server failure (response_code=0) rather than a
        // client-side timeout mismatch. See docs/MANUAL_CONFIG.md.
        timeout: '130s',
    };

    const res = http.post(`${SERVER_URL}/completion`, payload, params);

    check(res, {
        'legitimate request succeeded': (r) => r.status === 200,
    });
}

export function handleSummary(data) {
    return summaryReport(data, 'legitimate_probe');
}
