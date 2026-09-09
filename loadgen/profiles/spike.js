import http from 'k6/http';
import { check } from 'k6';
import { summaryReport } from './lib/summary.js';

// Profile B — Spike: sudden ramp-up in arrival rate (open-loop).
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

// preAllocatedVUs sizing formula (kickoff doc, not a guess):
//   preAllocatedVUs = ceil(median_iteration_duration_seconds * peak_rate) + buffer_for_variance
// Sized off the PEAK rate (40/s) in the ramp, since that's the worst case k6 must cover.
// MEDIAN_ITERATION_S is an ESTIMATE (n_predict=100) until Day 1's session measures the
// real value — override via SPIKE_MEDIAN_ITERATION_S once that exists.
const PEAK_RATE = 40;
const MEDIAN_ITERATION_S = Number(__ENV.SPIKE_MEDIAN_ITERATION_S || 6);
const BUFFER_FOR_VARIANCE = 20;
const PRE_ALLOCATED_VUS = Math.ceil(MEDIAN_ITERATION_S * PEAK_RATE) + BUFFER_FOR_VARIANCE;

export const options = {
    scenarios: {
        profile_b_spike: {
            executor: 'ramping-arrival-rate',
            startRate: 5,
            timeUnit: '1s',
            preAllocatedVUs: PRE_ALLOCATED_VUS,
            maxVUs: PRE_ALLOCATED_VUS * 2,
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
        tags: {
            request_type: 'completion',
            priority: 'legitimate',
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
