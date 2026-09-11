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
// Rate is env-overridable so different attack-rate scenarios don't require
// editing this file — e.g. SUSTAINED_RATE=10 for a mild-overload run, or
// SUSTAINED_RATE=100 for a stress test. Also read by demo/server.py's rate
// slider, when set.
const RATE = Number(__ENV.SUSTAINED_RATE || 50);

// Security test, not a normal mode: simulates an attacker who has obtained a
// verified/legitimate credential (purchased, phished, or a compromised account)
// and sends X-Priority: legitimate on attack traffic. The Shield's own
// is_priority_request() (shield/main.py) is a bare, unauthenticated HTTP header
// check with no verification behind it — this tests whether that's exploitable.
// Off by default; set ATTACK_SPOOF_LEGITIMATE=1 (or =true) to enable.
const SPOOF_LEGITIMATE =
    __ENV.ATTACK_SPOOF_LEGITIMATE === '1' ||
    (__ENV.ATTACK_SPOOF_LEGITIMATE || '').toLowerCase() === 'true';

const MEDIAN_ITERATION_S = Number(__ENV.SUSTAINED_MEDIAN_ITERATION_S || 5);
const BUFFER_FOR_VARIANCE = 50;
const PRE_ALLOCATED_VUS = Math.ceil(MEDIAN_ITERATION_S * RATE) + BUFFER_FOR_VARIANCE;

// Test duration, env-overridable (k6 duration string, e.g. '2m', '5m') — shared
// var name with profile-d.js so the demo panel's single duration control works
// regardless of which profile is selected. Duration doesn't affect
// preAllocatedVUs sizing (that's driven by rate, not total run length).
const DURATION = __ENV.ATTACK_DURATION || '2m';

export const options = {
    scenarios: {
        profile_c_sustained: {
            executor: 'constant-arrival-rate',
            rate: RATE,
            timeUnit: '1s',
            duration: DURATION,
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

    const headers = {
        'Content-Type': 'application/json',
        // Deliberately NO X-Priority header by default: this is simulated attack
        // traffic. When SPOOF_LEGITIMATE is on, this line is exactly the attack —
        // claiming a tier this traffic has no real right to.
    };
    if (SPOOF_LEGITIMATE) {
        headers['X-Priority'] = 'legitimate';
    }

    const params = {
        headers,
        tags: {
            request_type: 'completion',
            // Reflects what was ACTUALLY sent, not the script's identity — the
            // attack vs. probe distinction still lives at the file level (this
            // script's own raw/normalized CSVs vs. probe.js's), so this tag stays
            // meaningful for the Shield's-eye view even when spoofing is on.
            priority: SPOOF_LEGITIMATE ? 'legitimate' : 'attack',
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
