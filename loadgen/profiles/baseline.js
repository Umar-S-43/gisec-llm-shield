import http from 'k6/http';
import { check } from 'k6';
import { summaryReport } from './lib/summary.js';

// Profile A — Normal: steady open-loop arrival rate for baseline behavior.
// Open-loop (constant-arrival-rate): k6 fires requests at a fixed RATE regardless of
// how fast the server answers. This is required (see CLAUDE.md) — a closed-loop
// (VU + sleep) generator silently slows itself down when the server struggles, which
// hides the exact overload we're trying to measure ("coordinated omission").
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

// preAllocatedVUs sizing formula (kickoff doc, not a guess):
//   preAllocatedVUs = ceil(median_iteration_duration_seconds * rate) + buffer_for_variance
// MEDIAN_ITERATION_S is an ESTIMATE (small prompt, n_predict=50, CPU-only decode) until
// Day 1's session produces a real measured median from this profile — override via env
// once that number exists, e.g. BASELINE_MEDIAN_ITERATION_S=3.2.
const RATE = 5; // requests/sec, arrival-based, not VU-based
const MEDIAN_ITERATION_S = Number(__ENV.BASELINE_MEDIAN_ITERATION_S || 4);
const BUFFER_FOR_VARIANCE = 10;
const PRE_ALLOCATED_VUS = Math.ceil(MEDIAN_ITERATION_S * RATE) + BUFFER_FOR_VARIANCE;

export const options = {
    scenarios: {
        profile_a_normal: {
            executor: 'constant-arrival-rate',
            rate: RATE,
            timeUnit: '1s',
            duration: '2m',
            preAllocatedVUs: PRE_ALLOCATED_VUS,
            maxVUs: PRE_ALLOCATED_VUS * 2,
        },
    },
    thresholds: {
        http_req_duration: ['p(95)<1000'],
        http_req_failed: ['rate<0.1'],
    },
};

export default function () {
    const payload = JSON.stringify({
        prompt: 'Hello, what is machine learning?',
        n_predict: 50,
    });

    const params = {
        headers: {
            'Content-Type': 'application/json',
            'X-Priority': 'legitimate',
        },
        // Tags surface as columns in k6's --out csv=<file> raw output, which
        // loadgen/normalize_csv.py reads to build the per-request CSV /analysis expects.
        tags: {
            request_type: 'completion',
            priority: 'legitimate',
        },
        timeout: '60s',
    };

    const res = http.post(`${SERVER_URL}/completion`, payload, params);

    check(res, {
        'status is 200': (r) => r.status === 200,
        'has response text': (r) => r.body && r.body.length > 0,
    });
}

export function handleSummary(data) {
    return summaryReport(data, 'profile_a_normal');
}
