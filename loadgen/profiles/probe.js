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

export const options = {
    scenarios: {
        legitimate_probe: {
            executor: 'constant-arrival-rate',
            rate: 1,                  // deliberately small and constant
            timeUnit: '2s',           // ~0.5 req/sec
            duration: __ENV.PROBE_DURATION || '2m',
            preAllocatedVUs: 5,
            maxVUs: 10,
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
        timeout: '30s',
    };

    const res = http.post(`${SERVER_URL}/completion`, payload, params);

    check(res, {
        'legitimate request succeeded': (r) => r.status === 200,
    });
}

export function handleSummary(data) {
    return summaryReport(data, 'legitimate_probe');
}
