import http from 'k6/http';
import { check, sleep } from 'k6';
import { textSummary } from 'https://jslib.k6.io/summary/0.0.1/index.js';

// Read server URL from environment; default to localhost for testing
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

export const options = {
    stages: [
        { duration: '30s', target: 5 },    // Ramp up to 5 req/sec
        { duration: '2m', target: 5 },     // Stay at 5 req/sec for 2 minutes
        { duration: '30s', target: 0 },    // Ramp down to 0
    ],
    thresholds: {
        http_req_duration: ['p(95)<1000'],  // 95th percentile latency < 1s
        http_req_failed: ['rate<0.1'],      // Error rate < 10%
    },
};

export default function() {
    // Legitimate probe request
    const payload = JSON.stringify({
        prompt: 'Hello, what is machine learning?',
        n_predict: 50,
    });

    const params = {
        headers: {
            'Content-Type': 'application/json',
            'X-Priority': 'legitimate',  // Mark as legitimate traffic
        },
        timeout: '60s',
    };

    const res = http.post(`${SERVER_URL}/completion`, payload, params);

    check(res, {
        'status is 200': (r) => r.status === 200,
        'response time < 2s': (r) => r.timings.duration < 2000,
        'has response text': (r) => r.body && r.body.length > 0,
    });

    sleep(1);  // 1-second think time between requests
}

export function handleSummary(data) {
    // Output summary to stdout in text format
    console.log(textSummary(data, { indent: ' ', enableColors: true }));

    // Optionally write raw metrics as CSV for later analysis
    // (This would be implemented by the analysis scripts)
    return {};
}
