import http from 'k6/http';
import { check } from 'k6';
import { summaryReport } from './lib/summary.js';

// Profile C — Sustained flood: high, constant arrival rate for a long period,
// no priority header (simulated attack traffic). Open-loop.
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

export const options = {
    scenarios: {
        profile_c_sustained: {
            executor: 'constant-arrival-rate',
            rate: 50,
            timeUnit: '1s',
            duration: '2m',
            preAllocatedVUs: 100,
            maxVUs: 300,
        },
    },
    // No pass/fail thresholds here on purpose: this profile is EXPECTED to fail
    // requests under an unprotected server. It exists to characterize how badly
    // things degrade, not to assert an SLA.
};

export default function () {
    const payload = JSON.stringify({
        prompt: 'Lorem ipsum dolor sit amet',
        n_predict: 200,
    });

    const params = {
        headers: {
            'Content-Type': 'application/json',
            // Deliberately NO X-Priority header: this is simulated attack traffic.
        },
        timeout: '60s',
    };

    const res = http.post(`${SERVER_URL}/completion`, payload, params);

    check(res, {
        'got any response': (r) => r.status > 0,
    });
}

export function handleSummary(data) {
    return summaryReport(data, 'profile_c_sustained');
}
