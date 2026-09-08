import http from 'k6/http';
import { check } from 'k6';
import { summaryReport } from './lib/summary.js';

// Profile A — Normal: steady open-loop arrival rate for baseline behavior.
// Open-loop (constant-arrival-rate): k6 fires requests at a fixed RATE regardless of
// how fast the server answers. This is required (see CLAUDE.md) — a closed-loop
// (VU + sleep) generator silently slows itself down when the server struggles, which
// hides the exact overload we're trying to measure ("coordinated omission").
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

export const options = {
    scenarios: {
        profile_a_normal: {
            executor: 'constant-arrival-rate',
            rate: 5,                  // 5 requests/sec, arrival-based, not VU-based
            timeUnit: '1s',
            duration: '2m',
            preAllocatedVUs: 20,
            maxVUs: 50,
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
