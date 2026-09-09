import http from 'k6/http';
import { check } from 'k6';
import { summaryReport } from './lib/summary.js';

// Profile C — Sustained flood: high, constant arrival rate for a long period,
// no priority header (simulated attack traffic). Open-loop.
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

// preAllocatedVUs sizing formula (kickoff doc, not a guess):
//   preAllocatedVUs = ceil(median_iteration_duration_seconds * rate) + buffer_for_variance
// MEDIAN_ITERATION_S is an ESTIMATE (n_predict=200, high concurrency) until Day 1's
// session measures the real value — override via SUSTAINED_MEDIAN_ITERATION_S.
const RATE = 50;
const MEDIAN_ITERATION_S = Number(__ENV.SUSTAINED_MEDIAN_ITERATION_S || 5);
const BUFFER_FOR_VARIANCE = 50;
const PRE_ALLOCATED_VUS = Math.ceil(MEDIAN_ITERATION_S * RATE) + BUFFER_FOR_VARIANCE;

export const options = {
    scenarios: {
        profile_c_sustained: {
            executor: 'constant-arrival-rate',
            rate: RATE,
            timeUnit: '1s',
            duration: '2m',
            preAllocatedVUs: PRE_ALLOCATED_VUS,
            maxVUs: PRE_ALLOCATED_VUS * 2,
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
        tags: {
            request_type: 'completion',
            priority: 'attack',
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
