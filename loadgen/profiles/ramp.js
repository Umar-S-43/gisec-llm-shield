import http from 'k6/http';
import { check, sleep } from 'k6';

// Ramp-up profile: gradual load increase to find breaking point
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

export const options = {
    stages: [
        { duration: '3m', target: 30 },    // Linear ramp from 1 to 30 req/sec over 3 minutes
        { duration: '30s', target: 0 },    // Ramp down
    ],
    thresholds: {
        http_req_duration: ['p(95)<3000'],
        http_req_failed: ['rate<0.3'],  // Expect gradual increase in error rate
    },
};

export default function() {
    const payload = JSON.stringify({
        prompt: 'Describe the impact of AI on society',
        n_predict: 80,
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
        'status ok or rate-limited': (r) => r.status === 200 || r.status === 429 || r.status === 503,
    });

    sleep(1);
}
