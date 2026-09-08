import http from 'k6/http';
import { check, sleep } from 'k6';

// Traffic spike profile: sudden surge in load
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

export const options = {
    stages: [
        { duration: '10s', target: 20 },   // Ramp up to 20 req/sec
        { duration: '30s', target: 20 },   // Hold at peak
        { duration: '10s', target: 0 },    // Ramp down
    ],
    thresholds: {
        http_req_duration: ['p(95)<2000'],
        http_req_failed: ['rate<0.2'],
    },
};

export default function() {
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
        'status is 200 or 429/503': (r) => r.status === 200 || r.status === 429 || r.status === 503,
        'response time < 5s': (r) => r.timings.duration < 5000,
    });

    sleep(0.5);
}
