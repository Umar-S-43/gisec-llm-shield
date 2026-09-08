import http from 'k6/http';
import { check } from 'k6';
import { summaryReport } from './lib/summary.js';

// Profile B — Spike: sudden ramp-up in arrival rate (open-loop).
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

export const options = {
    scenarios: {
        profile_b_spike: {
            executor: 'ramping-arrival-rate',
            startRate: 5,
            timeUnit: '1s',
            preAllocatedVUs: 50,
            maxVUs: 150,
            stages: [
                { target: 5, duration: '10s' },   // baseline
                { target: 40, duration: '10s' },  // sudden ramp
                { target: 40, duration: '30s' },  // hold at peak
                { target: 0, duration: '10s' },   // ramp down
            ],
        },
    },
    thresholds: {
        http_req_duration: ['p(95)<2000'],
    },
};

export default function () {
    const payload = JSON.stringify({
        prompt: 'Explain quantum computing briefly',
        n_predict: 100,
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
        'got a response (200/429/503)': (r) => [200, 429, 503].includes(r.status),
    });
}

export function handleSummary(data) {
    return summaryReport(data, 'profile_b_spike');
}
