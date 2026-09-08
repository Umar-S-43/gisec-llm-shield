import http from 'k6/http';
import { check, sleep } from 'k6';

// Sustained attack profile: high-volume load without priority headers
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

export const options = {
    stages: [
        { duration: '10s', target: 50 },   // Ramp up to 50 req/sec (high load)
        { duration: '2m', target: 50 },    // Sustain for 2 minutes
        { duration: '10s', target: 0 },    // Ramp down
    ],
    thresholds: {
        http_req_duration: ['p(95)<5000'],
        http_req_failed: ['rate<0.5'],  // Expect high error rate under attack
    },
};

export default function() {
    const payload = JSON.stringify({
        prompt: 'Lorem ipsum dolor sit amet',
        n_predict: 200,
    });

    const params = {
        headers: {
            'Content-Type': 'application/json',
            // NO X-Priority header: this is simulated attack traffic
        },
        timeout: '60s',
    };

    const res = http.post(`${SERVER_URL}/completion`, payload, params);

    check(res, {
        'got a response': (r) => r.status > 0,
        'error rate measured': (r) => true,  // Log all responses for analysis
    });

    sleep(0.2);
}
