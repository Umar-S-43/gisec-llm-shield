import http from 'k6/http';
import { check } from 'k6';
import { summaryReport } from './lib/summary.js';

// Profile D — Slow/low-rate, high-cost. THE key differentiator profile (see CLAUDE.md).
//
// Only a handful of requests per second, but each one requests the maximum input AND
// output tokens llama-server will accept. A plain request-counting rate limiter sees
// "3 requests/sec" and shrugs — well under any sane per-request limit. But each request
// here ties up a slot for the full generation of a huge response, so the SERVER still
// gets starved just as badly as under Profile C's flood. This is the scenario that
// proves cost-aware admission control (Shield's token budget) beats naive rate limiting:
// the Shield should reject/shed these on estimated cost even though the REQUEST RATE
// looks harmless.
const SERVER_URL = __ENV.LLAMA_SERVER_URL || 'http://localhost:8080';

// Keep these aligned with whatever -c (context size) service/start.sh actually pins,
// so "maximum" here is a real maximum and not an arbitrary number.
const MAX_PROMPT_WORDS = Number(__ENV.PROFILE_D_PROMPT_WORDS || 1200); // ~1600 tokens
const MAX_OUTPUT_TOKENS = Number(__ENV.PROFILE_D_OUTPUT_TOKENS || 512);

const HUGE_PROMPT = 'Please provide an exhaustive, detailed analysis. '.repeat(
    Math.ceil(MAX_PROMPT_WORDS / 7)
);

// preAllocatedVUs sizing formula (kickoff doc, not a guess):
//   preAllocatedVUs = ceil(median_iteration_duration_seconds * rate) + buffer_for_variance
// This profile's whole point is huge prompt + huge output per request, so
// median_iteration_duration is expected to be LONG even though rate is LOW — that's
// exactly why a request-counting limiter misses it. MEDIAN_ITERATION_S is an ESTIMATE
// until Day 1's session measures the real value — override via PROFILE_D_MEDIAN_ITERATION_S.
const RATE = 3; // deliberately LOW rate — this is the point

// Security test, not a normal mode: simulates an attacker with a verified/
// legitimate credential (purchased, phished, compromised) sending X-Priority:
// legitimate on Profile D traffic. This is a MORE severe test than sustained.js's
// version of the same flag: spoofing here also switches the attacker onto the
// legitimate_bucket (2000 capacity / 200 refill-per-sec) instead of the default
// bucket (500 / 50) — a much larger budget for the same expensive request shape.
// Off by default; set ATTACK_SPOOF_LEGITIMATE=1 (or =true) to enable. Same env
// var name as sustained.js's flag (not profile-d-specific) so the demo panel's
// single checkbox controls it regardless of which profile is selected.
const SPOOF_LEGITIMATE =
    __ENV.ATTACK_SPOOF_LEGITIMATE === '1' ||
    (__ENV.ATTACK_SPOOF_LEGITIMATE || '').toLowerCase() === 'true';

const MEDIAN_ITERATION_S = Number(__ENV.PROFILE_D_MEDIAN_ITERATION_S || 20);
const BUFFER_FOR_VARIANCE = 10;
const PRE_ALLOCATED_VUS = Math.ceil(MEDIAN_ITERATION_S * RATE) + BUFFER_FOR_VARIANCE;

// Test duration, env-overridable — same ATTACK_DURATION var as sustained.js, see
// that file's comment. Longer durations proportionally raise total token cost
// sent (rate is fixed at 3/s), which is expected and part of the point.
const DURATION = __ENV.ATTACK_DURATION || '2m';

export const options = {
    scenarios: {
        profile_d_slow_expensive: {
            executor: 'constant-arrival-rate',
            rate: RATE,
            timeUnit: '1s',
            duration: DURATION,
            preAllocatedVUs: PRE_ALLOCATED_VUS,
            maxVUs: PRE_ALLOCATED_VUS * 2,
        },
    },
};

export default function () {
    const payload = JSON.stringify({
        prompt: HUGE_PROMPT,
        n_predict: MAX_OUTPUT_TOKENS,
    });

    const headers = {
        'Content-Type': 'application/json',
        // No X-Priority header by default: this is the attack profile, just shaped
        // to look "low volume" to a request-counter. When SPOOF_LEGITIMATE is on,
        // this line IS the attack — claiming a tier (and its bigger token bucket)
        // this traffic has no real right to.
    };
    if (SPOOF_LEGITIMATE) {
        headers['X-Priority'] = 'legitimate';
    }

    const params = {
        headers,
        tags: {
            request_type: 'completion',
            // Reflects what was ACTUALLY sent, not the script's identity — see
            // sustained.js's identical comment for why that's the right choice.
            priority: SPOOF_LEGITIMATE ? 'legitimate' : 'attack',
        },
        timeout: '120s',
    };

    const res = http.post(`${SERVER_URL}/completion`, payload, params);

    check(res, {
        'got any response': (r) => r.status > 0,
    });
}

export function handleSummary(data) {
    return summaryReport(data, 'profile_d_slow_expensive');
}
