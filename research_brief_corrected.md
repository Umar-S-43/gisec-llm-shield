## Research Brief: Defending an LLM Inference Service Against Availability Stress

## CPU-only / llama.cpp execution plan — corrected version

Compiled 2026-09-08 · Corrected 2026-09-08

Source-grounded evidence base for a four-day defensive hackathon prototype for GISEC. Every factual claim below links to a page fetched in this session. Values that could not be confirmed from a fetched page are marked n.a. Statements labelled (inference) are engineering

recommendations, not source-attested fact.

Correction note (added on review): two spots in the original draft still referenced the abandoned GPU/vLLM stack after the CPU/llama.cpp pivot — the Shield diagram’s polling target, and the citation line beneath it. Both are fixed in this version. No

other factual or architectural content was changed.

## Executive summary: what to build

## Decision Recommendation Anchor evidence

llama-server from llama.cpp with --

Target service (CPU- only, adopted)

metrics, small

quantized model, few slots and threads vLLM: requires avx512f on x86, has

vLLM CPU installation

Not used on laptops no pre-built CPU

wheels, and must be built from source k6 arrival-rate executors (open model) + dropped_iterations Locust LoadTestShape for scripted spike/flood/slow phases vllm bench serve flag semantics reused in your own client: request rate, burstiness, fixed input/output lengths, probe requests Token-cost-aware admission control (charge estimated

Load generator (primary)

Load generator (secondary)

Workload-design reference (not installed)

vLLM benchmark CLI

Envoy AI Gateway usage-based rate

Defense #1

input+output tokens, limiting, VTC paper not requests)

Queue/KV-cache-

llama.cpp server README

k6 arrival-rate VU allocation

Locust custom load shapes


aware load shedding GKE Inference

Defense #2

with fast 429 rejection Priority-tiered fair queuing with anti- starvation aging Open-loop arrival, warmup discard, repeated seeded runs, percentiles + Max, bootstrap CIs, goodput OWASP LLM10:2025 Unbounded Consumption /

Gateway, Google SRE “Handling Overload”

vLLM RFC #6077, vLLM RFC #16969

Defense #3

Gil Tene, “How NOT to Measure Latency”, PT4Cloud

Evaluation core

OWASP LLM10:2025, GCP

Business framing

“Denial of Wallet” + accelerator- real GPU-hour and optimized pricing per-token prices

This section supersedes the GPU assumptions elsewhere in the document. The defense design, the pattern catalogue, and the statistical protocol are unchanged; only the target service, the overload knobs, and the observability signals change.

## CPU-only, low-budget execution plan

## Why the constraint helps

Capacity is what makes overload expensive to demonstrate, and a CPU-only laptop has very little of it. Reaching the saturated, queue- building regime therefore takes single-digit requests per second rather than hundreds, which shortens every run, makes five repeated runs per arm affordable, and keeps the whole project at zero infrastructure cost. The scientific claims do not depend on absolute throughput: the argument is that a request-count limiter and a token- cost limiter behave differently under identical offered load, and that

comparison is scale-free.

## Target service: llama.cpp

llama-server is the right choice because it is a single binary, runs well on CPU, and already exposes the admission signals the shield needs. Documented features include continuous batching (-cb, enabled by default), parallel server slots (-np, default -1 for auto), context size (-c,

default 0 meaning loaded from the model), generation threads (-t), and separate prompt-processing threads (-tb) (llama.cpp server README). vLLM should be dropped rather than adapted. Its CPU backend requires the avx512f CPU flag on x86, states that there are currently no pre-built CPU wheels, and must be built from source, with macOS Apple silicon support marked experimental and also source-built (vLLM CPU installation). That is a realistic day of build work for a team with limited infrastructure background, and it buys nothing the

project needs.

## Replacement overload knobs

Instead of shrinking GPU KV-cache blocks, constrain the CPU service directly and state the values in the report:

- np low (for example 2 to 4) so the number of concurrent slots is


- small and queueing begins early.

- t pinned to a small fixed thread count so capacity is stable and reproducible across runs, rather than varying with whatever else the laptop is doing.

- c set explicitly rather than left at the model default, so context limits are a stated experimental parameter.

- A small quantized instruct model, so model load time and memory pressure do not dominate the experiment.

## Replacement observability signals

Enable the Prometheus endpoint with --metrics, which is only available when the server is started with that flag (llama.cpp server README). The signals that map onto the shield’s logic:

| Need | CPU-only signal | Note |
| --- | --- | --- |
|   |   | Gauge, number |
|   |   | of requests |
| In-flight work | llamacpp:requests_processing | processing |
|   |   | (llama.cpp |
|   |   | server |
|   |   | README) |
|   |   | Gauge, number |
| Queue |   | of requests |
| pressure | llamacpp:requests_deferred | deferred |
| (shed trigger) |   | (llama.cpp |
|   |   | server |
|   |   | README) |
|   |   | Responds 503 |
| Capacity |   | when no slot is |
| exhaustion, | GET /slots?fail_on_no_slot=1 | available |
| binary |   | (llama.cpp |
|   |   | server |
|   |   | README) |
|   |   | Reports per-slot |
|   |   | processing |
| Slot |   | state, processed |
| occupancy | GET /slots | tokens, context |
| detail |   | size, speed |
|   |   | (llama.cpp |
|   |   | server |
|   |   | README) |
|   |   | Separate |
|   |   | average prompt |
|   |   | and generation |
| Two-phase | llamacpp:prompt_tokens_seconds vs | throughput |
| evidence | llamacpp:predicted_tokens_seconds | gauges |
|   |   | (llama.cpp |
|   |   | server |
|   |   | README) |
|   |   | Average busy |
|   |   | slots per |
| Batching | llamacpp:n_busy_slots_per_decode | llama_decode() |
| efficiency |   | call (llama.cpp |
|   |   | server |
|   |   | README) |
|   |   | Counters for |
|   |   | prompt and |
| Token | llamacpp:prompt_tokens_total, | generation |
| accounting | llamacpp:tokens_predicted_total | tokens |
|   |   | (llama.cpp |
|   |   | server |
|   |   | README) |


One honest limitation to state in the report rather than hide: the llama.cpp metrics page does not list a metric named for KV-cache usage or occupancy, so cache-utilization-based shedding is not directly available; per-slot state must be read from /slots instead (llama.cpp server README). Deferred-request count plus slot exhaustion is the defensible CPU substitute for the KV-cache signal that production gateways use (GKE Inference Gateway).

## The measurement trap specific to laptops

On a single laptop the load generator competes with the inference server for the same cores, which silently caps offered load and corrupts every latency number. Two mitigations, both cheap:

- 1. Run the generator on a different laptop over the local network and treat the server machine as dedicated. With four team members this is free.

- 2. If a single machine is unavoidable, pin server threads to a fixed core set, cap generator resource use, and report dropped_iterations every run, since k6 emits that metric for each iteration it cannot start and the documentation notes it can indicate degrading system performance (k6 arrival-rate VU allocation).

## Thermal variance changes the run order, not the statistics

Laptops throttle under sustained load, so running all defense-off trials before all defense-on trials would confound the comparison with heat. Interleave the arms (off, on, off, on) within each profile, randomize profile order, insert a fixed cooldown between runs, and record run index and order so any drift is visible in the data. No fetched source in this session prescribes a thermal protocol for laptop benchmarking, so this is stated as protocol design rather than cited practice, and it is defensible on the same repeated-run logic that motivates multiple executions in the first place (PT4Cloud). (inference)

## Budget

The prototype needs no paid infrastructure: llama.cpp, k6, Locust, and Prometheus are free, and the models are small quantized open weights. The sensible use of the 30 dollar ceiling is a single optional confirmation run on a rented GPU at the very end, purely to show the same defense works on accelerator hardware. Verified hourly on- demand comparators for that one run: NVIDIA L4 on g2-standard-4 at 0.706832276 dollars per hour in us-central1 (GCP accelerator- optimized pricing), or Tesla V100 at 0.79 dollars and A10 at 1.29 dollars per GPU-hour (Lambda pricing). A two-hour session is a few dollars, and EC2-style per-second billing with a 60-second minimum means short sessions are not rounded up punitively (AWS EC2 On- Demand pricing). Treat this as optional: the CPU results are the deliverable, and the GPU run is a robustness footnote.

## What does not change

The token-cost reserve and reconcile logic, the fast rejection path, the priority tier with aging, the four load profiles, the legitimate probe cohort, open-model arrival, percentiles with Max, Wilson intervals for proportions, and the paired seeded design all carry over unmodified. The cost asymmetry that motivates the whole design is a property of the workload, not the hardware: output tokens are priced 5 to 6 times input tokens on managed APIs (OpenAI API pricing), and a request- count limiter is blind to that multiplier on a laptop exactly as it is on an H100.


All patterns below are described as load profiles to generate against your own controlled instance. No third-party targeting guidance is included, and none is needed: the mechanisms are documented properties of open-source serving stacks.

## The two-phase bottleneck (the physics that makes LLM serving different)

The authoritative statement of why LLM inference has a split resource profile comes from the Sarathi-Serve paper (arXiv, v1 4 Mar 2024, v3 17 Jun 2024): “Prefill iterations have high latency but saturate GPU compute due to parallel processing of the input prompt,” whereas “decode iterations have low latency but also low compute utilization because a decode iteration processes only a single token per request.” Consequently “batching multiple requests leads to an interleaving of prefill and decode iterations which makes it challenging to achieve both high throughput and low latency” (Sarathi-Serve, arXiv:2403.02310).

This single fact is the backbone of the whole prototype: a request’s cost is not 1; it is roughly (input tokens for prefill) + (output tokens × per-step decode cost), and the two components stress different resources.

## AI/LLM-inference-specific traffic patterns that cause availability stress

## Pattern catalogue

|   | Resource bottleneck | Safe, |
| --- | --- | --- |
| Pattern | (source-attested) | measurable |
|   |   | test parameter |
|   | Prefill “saturate[s] |   |
|   | GPU compute due to |   |
|   | parallel processing of |   |
|   | the input prompt”; |   |
|   | long prompts under | --random-input- |
|   | FCFS cause head-of- | len (vLLM |
|   | line blocking. vLLM | bench) or |
|   | RFC #16969 (22 Apr | Sarathi-Serve, prompt token |
| Long input / | 2025) states FCFS | vLLM RFC count in your |
| prefill pressure | “often leads to head-of- | #16969, vLLM own client; ratio |
|   | line blocking issues, | bench CLI of long-prompt |
|   | causing GPU memory | to short-prompt |
|   | resources to be | requests |
|   | underutilized, |   |
|   | especially as prompt |   |
|   | lengths increase due to |   |
|   | multi-turn |   |
|   | interactions.” |   |
|   | Output length is the |   |
|   | dominant per-request |   |
|   | occupancy driver: a |   |
|   | request holds a KV- |   |
|   | cache slot for its entire |   |
|   | decode. The DoS- |   |
|   | poisoning paper shows |   |
|   | output length is |   |
|   | directly attackable: |   |
|   | natural instructions | --random-output- |
|   | are “bounded by the | len plus -- |

Evidence

Sarathi-Serve,

#16969, vLLM


maximum length of the ignore-eos

Denial-of-Service

Long output / LLM’s supervised

decode pressure

(forces the full

Poisoning Attacks

finetuning (SFT) data,” generation

against LLMs,

while a poisoned

length so

arXiv:2410.10760

model emits “up to the occupancy is

(14 Oct 2024),

maximum inference length (16K tokens, compared to 0.5K before poisoning),” producing “endless outputs without generating an [EOS] token” and “high latency [that] make[s] LLM services inaccessible to other users or tasks.” vLLM: “Due to the autoregressive nature of transformer architecture, there are times when KV cache space is insufficient to handle all batched requests. In such cases, vLLM can

deterministic and reproducible)

vLLM bench CLI

Concurrency

level (--max- concurrency),

preempt requests to plus server-side

free up KV cache space for other

max_num_seqs and --num-gpu-

vLLM Optimization and

Concurrent

requests. Preempted blocks-override

sequence / KV- requests are cache pressure recomputed when

sufficient KV cache space becomes

(documented as “Used for testing preemption”) to

Tuning, vLLM

engine args

available.” Levers that shrink cache

control this:

and reach the contention regime cheaply

max_num_seqs

(“Decreasing it reduces the number of concurrent requests in a batch and requires less KV cache space”),

gpu_memory_utilization, max_num_batched_tokens.

Same total RPS delivered in bursts drives queueing and preemption harder than smooth arrival. vLLM’s benchmark tool models this with a Gamma distribution whose shape parameter is burstiness: 0.1 ≈ highly bursty (“suitable for stress testing”), 1.0 = “natural Poisson traffic,” 5.0 ≈ “uniform traffic.” OWASP LLM10:2025 explicitly names “Attackers can

--burstiness

(0.1–0.5 for stress, 1.0 for realism) with a

finite --request-

vLLM benchmark

Burstiness

rate; note it “takes effect only when --

CLI

request-rate is

not infinite”

overload the LLM with


numerous inputs of varying lengths, exploiting processing inefficiencies,” “Resource-Intensive Queries” that “drain system resources, leading to prolonged processing times,” and “Continuous Input Overflow” where inputs exceeding the

Low RPS (e.g. 0.2–2 req/s) with maximal input+output token budget per request; report tokens/second offered, not requests/second, as the load axis

Slow / low- rate,

OWASP LLM10:2025 (28

heterogeneous- context window “lead

Apr 2025), Sponge Examples

to excessive computational resource use.” Sponge examples (arXiv:2006.03463, 5 Jun 2020) established the generic class: “inputs designed to maximise energy consumption and latency,” measured “increasing energy consumption by a factor of 10 to 200” across CPUs, GPUs and an ASIC simulator.

cost

## Why the slow/low-rate pattern is the judge-winning one

OWASP’s own recommended mitigation for LLM10 is request-count based: “Apply rate limiting and user quotas to restrict the number of requests a single source entity can make in a given time period” (OWASP LLM10:2025). The same page separately acknowledges the variable-length-input and resource-intensive-query vectors. A low- RPS, maximum-token workload therefore passes a request-count limit while consuming the bulk of the accelerator: which is precisely the gap your prototype closes. (inference: the juxtaposition of these two OWASP statements is the cleanest one-slide justification for cost- aware admission control.)

## Defenses beyond fixed per-request rate limiting

## Comparison table

Simplest corr

## Defense Value Complexity (4- day team) Failure modes

Directly prices the real bottleneck. VTC: “most major LLM inference services have request rate limits… this rudimentary notion of fairness

Post-hoc charging lag.

Envoy AI Gateway: “Token usage is

A. Cost-

implementat

Token-bucket per A

where the withdraw

est_cost = in_token

w·max_tokens

before admission (r


aware

notion of fairness

also results in

charged after the response completes”; a 1,000-token hourly limit can still permit a

then reconcile to ac

admission under-utilization of

usage after complet

Low–medium

control (token- estimate budgets)

the resources and poor client experience.” VTC defines fairness “based on a cost function that accounts for the number of input and output tokens processed” (VTC,

Weighted-cost prece

(input_tokens -

1,200-token stream. Also client-supplied identity spoofing (Envoy)

cached_input_tokens

(cached_input_token

\+ output_tokens * 1

(Envoy AI Gateway)

does the reserve tri

(OpenAI rate limits)

arXiv:2401.00588)

On this CPU stack

/metrics for

Sheds before the engine thrashes. GKE Inference Gateway: “The EPP… uses real- time signals from model servers (KV

Rejection is not free. Google SRE: “even in the case where rejecting requests saves significant resources, those requests still consume

llamacpp:requests_d

and

llamacpp:requests_p

(and /slots?

fail_on_no_slot=1

B. Queue / capacity- aware load shedding with fast rejection

queue or slot state

threshold, return 42

cache utilization, Low (metrics some resources… the

Retry-After

queue length,

already

backend can become overloaded even though the vast majority of its CPU is spent just rejecting requests.” Also: wrong

the proxy without to

prefix cache state, exported) and LoRA adapter affinity)”; “Queueing and shedding: manages request flow and prevents traffic overload”

Protects a named legitimate tier under overload. GKE: “GKE Inference Gateway gives preference to workloads with a higher priority value… requests with a Priority less than 0 are considered lower Medium priority and are dropped first.” QLM reports “improve[d] SLO attainment by 40– 90%” and “throughput by 20–400%” via queue ordering (QLM, arXiv:2407.00047) OWASP explicitly asks for it: “Continuously monitor resource usage and implement logging Low if kept to

the engine (llama.cp

README). Header

precedent:

be present on 429 r

caused by a tempor

capacity metric — QPS is a poor proxy

limit and 503 respo

caused by temporar

(Google SRE)

overload” (OpenAI r

limits)

Starvation / priority inversion. vLLM RFC #16969: “it is still necessary to introduce

Two-class WFQ in y

a priority promotion mechanism… If a request has been waiting in the queue for more than a certain threshold, its priority should be increased.” vLLM RFC

proxy: reserve a fixe

fraction of in-flight

tier-A (interactive) k

C. Priority- tiered fair queuing / reservations

remainder shared; a

time aging so tier-B

starve. Do not attem

engine-internal pre

— the maintainers d

#6077: joint-queue sorting and KV- preserving preemption remain unresolved

this as unresolved w

(#6077)

False positives on legitimate heavy users. OpenAI documents a slow_down

Per-key EWMA of

tokens/request and

D. Lightweight statistical anomaly detection

requests/sec with a

error keyed on ramp rate, not just level, with a rule of thumb of no more than 50%

score; flag only, the

to detect and

EWMA/quantile;

the flag into defens

respond to unusual high if ML patterns of

cost multiplier rath

hard block. Report


patterns of

hard block. Report

(optional) resource

growth every 15 minutes past 1M input

on the legitimate co

consumption” (OWASP

explicitly

tokens/min (OpenAI rate limits)

LLM10:2025) Chunked prefill removes prefill- induced decode stalls: Sarathi- Serve reports “2.6x higher serving capacity” Trivial (flags) (Mistral-7B, 1×A100) and “up to 3.7x” (Yi-34B, 2×A100) vs vLLM (arXiv:2403.02310)

E. Server- side stall- free scheduling (config, not code)

On the GPU stack,

GPU-stack only; pre

max_num_batched_tokens

literature context o

set equal to

CPU build, not as yo

max_model_len loses

measured contribut

the chunking benefit (vLLM tuning)

(inference)

## Adaptive client-side throttling: a cheap third mitigation

Google SRE’s “adaptive throttling” is trivially portable to a demo client: each client task keeps, over the last two minutes, requests (“the number of requests attempted by the application layer”) and accepts (“the number of requests accepted by the backend”); under normal conditions “the two values are equal,” and when the backend rejects, clients self-cap so that “requests above the cap fail locally without even reaching the network” (Google SRE, Handling Overload). This is ~20 lines and demonstrably reduces the rejection-

cost failure mode of defense B.

## Graceful degradation

Google SRE gives the ordering to cite on your architecture slide: “redirect when possible, serve degraded results when necessary, and handle resource errors transparently when all else fails,” where degraded responses are “not as accurate as or… contain less data than normal responses, but… are easier to compute” (Google SRE). LLM analogue (inference): under shed pressure, cap max_tokens for low-priority tiers instead of rejecting them outright — a measurable “partial functionality” arm OWASP also asks for.

## Statistically sound evaluation

## Non-negotiable: open-loop (arrival-rate) load generation

Closed-loop generators silently back off when the server slows, which is the coordinated omission error. Gil Tene’s canonical worked example: a system that “easily handles 100 requests/sec… responds to each in 1msec” then stalls for 100 s. Correct characterization is “~50%’ile is 1 msec, ~75%’ile is 50 sec, 99.99%’ile is ~100sec”; a naïve single-threaded logger reports “99.99%’ile is 1 msec!” and an average of 10.9 ms instead of ~25 s — in a real reported result, wrong

“by a factor of 1,000x” (Gil Tene, QCon SF 2012). k6 solves this structurally. Arrival-rate executors “are open-model scenarios… k6 starts iterations according to the target rate as long as VUs are available,” explicitly “opposed to closed-model scenarios, in which VUs wait for one iteration to finish before starting another” (k6

arrival-rate VU allocation).


Critical measurement caveat you must report: k6 does not fully escape omission if you under-allocate VUs. “If the executor has insufficient

VUs: k6 emits a dropped_iterations metric for each iteration that it

cannot run… Dropped iterations can also indicate that system performance is degrading” (k6 arrival-rate VU allocation). Therefore: report dropped_iterations alongside every latency percentile, and size VUs using the documented estimator preAllocatedVUs =

[median_iteration_duration * rate] + constant_for_variance (same

page). Avoid maxVUs inflation mid-test: “Allocating VUs while the test runs can overload the load generator and skew results” (same page).

## Percentiles, Max, and what not to report

From the same authoritative source: “Measure %’iles. Lots of them”; “Always measure Max time. Consider what it means”; “If you haven’t stated percentiles and a Max, you haven’t specified your requirements”; “Measuring throughput without latency behavior is [usually] meaningless”; and bluntly, “Standard Deviation and application latency should never show up on the same page… Don’t use or derive from std. deviation” (Gil Tene). The talk also frames the correct headline metric: “Sustainable Throughput: The throughput achieved while safely maintaining service levels.”

(inference) Translate that into your deliverable: your headline result is sustainable goodput at a stated SLO, e.g. “requests/s completed with TTFT p95 < X and no error,” not raw RPS.

## LLM-specific metric definitions to use verbatim

| Metric | Exact definition | Source |
| --- | --- | --- |
|   | “the time from |   |
|   | sending a request |   |
| TTFT | to receiving its | vLLM bench CLI |
|   | first streamed |   |
|   | output” |   |
|   | “the time between |   |
|   | consecutive |   |
|   | streamed |   |
| ITL | outputs… | same |
|   | aggregate[d]… |   |
|   | across all |   |
|   | successful |   |
|   | requests” |   |
|   | “calculated once |   |
|   | per request, |   |
| TPOT | excluding the first | same |
|   | token, and then |   |
|   | aggregated across |   |
|   | requests” |   |
|   | “time spent |   |
|   | waiting for the |   |
|   | benchmark client’s |   |
| client_queue_time | concurrency limit”: | same |
|   | include it in -- |   |
|   | percentile-metrics |   |
|   | when using --max- |   |
|   | concurrency |   |
|   | “schedule-relative |   |
|   | end-to-end |   |
|   | latency” when a |   |
| e2el_including_client_queue | finite --request- | same |
|   | rate is used; |   |
|   | “omitted for -- |   |


The last two matter for correctness: schedule-relative latency is the coordinated-omission-safe number, because it measures from intended send time, not from when your client got around to sending (vLLM

bench CLI). (inference)

## Repeated runs, warmup, stopping rules

- Repetition is standard practice, not optional: “For better accuracy, a common practice is to run the application-under-test with a test input multiple times to obtain the average or certain percentiles of its performance” (PT4Cloud).

- Stop on distributional stability, not on a fixed count: PT4Cloud runs in intervals and “determines if adding these new n samples significantly changes the performance distribution acquired from previous intervals… it leverages the observation of statistical stability, which states that the frequencies and averages converge… given a large number of samples” (PT4Cloud).

- Report distributions, not just means: “it is important to know the best-case, worst-case and percentiles of the performance in addition to averages”; distinguish “a confidence interval is for a single point of estimation (e.g., mean)” from “a confidence band… for a series of estimations (e.g., distribution)” (PT4Cloud).

- Known hazard with naïve CI-based stopping: PT4Cloud’s own comparison found a CI-on-every-percentile stopping rule “caused the performance testing to stop at variable times, from 2 hours to even 7 weeks… with average accuracy… only 66.2%” (PT4Cloud). Practical implication for a 4-day project: put CIs on p50/p95 and on the survival/error proportions; do not chase CIs on p99.9. (inference)

- Warmup: no fetched source prescribes a warmup duration for LLM serving. Mark as n.a. for citation; justify your own choice operationally by discarding the interval until

llamacpp:requests_processing and

llamacpp:predicted_tokens_seconds reach steady state (llama.cpp

server README). (inference)

## Confidence intervals for rates and proportions (survival, error rate, FP rate)

Legitimate-user survival and error rate are proportions, so use a proportion interval, not a normal-approximation-on-latency. NIST recommends the Wilson interval. NIST states: “One advantage of this procedure is that its worth does not strongly depend upon the value of [p] and/or [n],” and “Another advantage is that the lower limit cannot be negative,” criticising the plain Wald form because “A confidence limit approach that produces a lower limit which is an impossible value for the parameter… is an inferior approach.” For small counts, NIST also gives the exact binomial construction, e.g. 4 defects in 20 samples → 90% interval “(0.071, 0.400)” (NIST/SEMATECH e- Handbook §7.2.4.1). For latency percentiles, use bootstrap percentile intervals over the per-run percentile estimates (resample the run-level p95 values, or resample raw samples within a run). No fetched source in this session prescribes a bootstrap recipe for latency benchmarking specifically: treat the method choice as n.a. for citation and state it as your own

documented protocol. (inference)

## Paired before/after design and “overload achieved”


Pair on the workload, not on wall-clock. Fix the RNG seed, the prompt corpus, the arrival schedule, and the per-request max_tokens, then run defense-off and defense-on arms. Locust’s LoadTestShape.tick() “returns a tuple with the desired user count and spawn rate” and is called “approximately once per second,” and can restrict which user

classes run per stage via (users, spawn_rate, user_classes) — exactly

how to keep an “attacker cohort” and a “legitimate cohort” on one timeline (Locust custom load shapes).

Prove overload was actually reached, otherwise the whole comparison

is vacuous. Server-side evidence on the CPU stack:

llamacpp:requests_processing pinned at the slot count,

llamacpp:requests_deferred rising above zero, falling

llamacpp:predicted_tokens_seconds, and /slots?fail_on_no_slot=1

returning 503 (llama.cpp server README). Client-side evidence: dropped_iterations > 0 and error-rate rise (k6).

- Encode SLOs as machine-checked thresholds so pass/fail is not a judgement call (k6 thresholds).

- False positives on legitimate traffic must be its own reported number: fraction of legitimate-cohort requests rejected or degraded by your defense, with a Wilson interval (NIST). (inference on the framing; the interval method is source-attested.)

- Goodput definition to state explicitly (inference, built on source- attested pieces): goodput = completed requests/s that met the SLO. Distinguish it from throughput; distinguish token-goodput (rate of llamacpp:tokens_predicted_total) from request-goodput (llama.cpp server README). Anchor the concept with Tene’s “Sustainable Throughput.”

## Minimal statistically defensible protocol (copy this into your report)

- 1. Fixed model, fixed server flags, seeded prompt corpus, seeded arrival schedule.

- 2. 4 load profiles × 2 arms (defense off/on) × ≥5 repeated runs; discard warmup interval; record raw per-request samples, not only aggregates.

- 3. Open-model arrival only; report dropped_iterations per run; size preAllocatedVUs by the documented formula.

- 4. Per run compute: TTFT/TPOT/e2e p50/p95/p99 + Max, error rate, legitimate-cohort survival, request- and token-goodput.

- 5. Across runs: bootstrap percentile CI for latency percentiles; Wilson CI for survival/error/FP proportions.

- 6. Report overload-achieved evidence (queue depth, slot exhaustion, deferred-request count) for every run.

- 7. State a pass/fail SLO as a k6 threshold expression so the result is reproducible by a judge with one command.

## Economic framing: only defensible numbers and explicit formulas

## Self-hosted GPU cost basis (dated, region-stated)

Google Cloud’s accelerator-optimized VM pricing page, fetched 2026- 09-08, lists on-demand USD/hour for region Iowa (us-central1):

| Machine type GPU model | On-demand | Source |
| --- | --- | --- |
|   | USD/hour |   |
|   |   | GCP |
|   |   | accelerator- |
| a2-highgpu-1g NVIDIA A100 | $3.673385 | optimized |


|   | pricing |
| --- | --- |
| a2-ultragpu-1g NVIDIA A100 $5.06879789 same a3-highgpu-8g NVIDIA H100 $88.490000119 same a3-megagpu-8g NVIDIA H100 $93.400712807 same a3-ultragpu-8g NVIDIA H200 $84.806908493 same |   |
| g2-standard-4 NVIDIA L4 | $0.706832276 same |
| NVIDIA RTX PRO 6000 g4-standard-6 GPU | $0.64688 same |
| attachment, 1 NVIDIA T4 GPU GPU | $0.35 same |
| attachment, 1 NVIDIA V100 $2.48 GPU | same |

Caveats stated on that page: prices are in USD; the page notes it “does not cover pricing for any disk and images, networking, sole tenancy, Confidential VM service, or GPUs used by the VM instance”; and no “prices as of” date is stated on the page (GCP). Region is explicitly us-central1 in the table above. Prices in other regions: n.a. from this fetch.

Independent GPU-cloud comparator, fetched 2026-09-08, per-GPU- hour on-demand instance prices (region not stated on the page): NVIDIA H100 SXM \$3.99, NVIDIA A100 SXM \$2.79 and \$1.99, NVIDIA A100 PCIe \$1.99, NVIDIA A10 \$1.29, NVIDIA A6000 \$1.09, NVIDIA B200 SXM6 \$6.69, NVIDIA GH200 \$2.29, NVIDIA Tesla V100 \$0.79 (Lambda pricing, page date shown 2025-11-16).

Billing granularity for the AWS comparison: EC2 On-Demand “are charged by the hour or second, with a minimum of 60 seconds,” and partial instance-hours are billed per second for Linux/Ubuntu Pro among others (AWS EC2 On-Demand pricing). Specific AWS GPU instance hourly rates did not render on that page in this fetch: n.a. (do not quote AWS GPU \$/hr without re-verifying against the live region selector).

## Managed-inference token price basis

OpenAI’s pricing page, fetched 2026-09-08, per 1M tokens (Standard tier). No “prices as of” date is stated on the page:

| Model | Context Input / 1M Output / 1M |   |
| --- | --- | --- |
| gpt-6-astra Short | $10.00 | $50.00 |
| gpt-6-astra Long | $20.00 | $75.00 |
| gpt-5.6-sol Short | $4.00 | $20.00 |
| gpt-5.6-terra Short | $2.00 | $12.00 |
| gpt-5.6-luna Short | $0.20 | $1.20 |
| chat-latest n.a. | $5.00 | $30.00 |

(OpenAI API pricing) Regional caveat stated on the same page: “Regional processing endpoints are charged a 10% uplift for models released on or after March 5, 2026, that are eligible for data residency,” and “GPT-5.6 Sol’s promotional pricing is available at least through November 21, 2026.”

The asymmetry is the whole economic story: output tokens cost 5–6× input tokens on every flagship row above (OpenAI API pricing). A request-count rate limit is blind to this multiplier; a token-cost limit is not.


## Formulas to present (no invented numbers)

Use these with your own measured values, filling the price from a dated table above:

- 1. GPU-hour unit cost of a request (self-hosted): using measured end-to-end latency and llamacpp:requests_processing (llama.cpp server README) for the CPU-analogue calculation, and the dated GCP table (GCP) for any GPU-hour comparison.

- 2. Cost per 1k tokens served, self-hosted: with tokens/s from llamacpp:predicted_tokens_seconds (llama.cpp server README). On CPU-only hardware, present this as a per-machine unit cost using your own measured tokens/s and clearly label the price basis you substitute, rather than implying your laptop costs GPU rates.

- 3. Managed-API “Denial of Wallet” exposure per attacker-hour: using the dated OpenAI table (OpenAI API pricing). OWASP names this risk directly: “By initiating a high volume of operations, attackers exploit the cost-per-use model of cloud-based AI services, leading to unsustainable financial burdens on the provider and risking financial ruin” (OWASP LLM10:2025).

- 4. Capacity-cost avoidance of your defense (inference): if your defense raises SLO-conforming goodput by factor N at fixed hardware, the avoided spend is proportional to N per GPU-hour equivalent. Precedent that scheduling changes yield large N: Sarathi-Serve reports “2.6x higher serving capacity” on 1×A100 and “up to 3.7x” on 2×A100 vs vLLM (arXiv:2403.02310); QLM reports throughput improvements of “20–400%” (arXiv:2407.00047). Do not claim those numbers as yours: cite them as literature context and report your own measured N.

Google SRE supplies the framing sentence for why cost accounting must be resource-based, not request-based: “A better solution is to measure capacity directly in available resources,” with their worked per-customer quota example allocated in “CPU seconds per second” out of “10,000 CPUs allocated worldwide” (Google SRE). Your token- budget quota is the LLM analogue of that CPU-seconds quota. (inference)

## Build stack and fastest wiring (verified against current official docs)

## Adopted target service: llama.cpp llama-server

Documented features include “Parallel decoding with multi-user support,” “Continuous batching,” “Monitoring endpoints,” “OpenAI API compatible chat completions, responses, and embeddings routes,” and “Speculative decoding.” Relevant knobs: -c/--ctx-size (default 0, “loaded from model”), -n/--predict (default -1 = infinity), -b/--batch- size (default 2048, logical max batch), -ub/--ubatch-size (default 512, physical max batch), -ctk/-ctv KV cache dtype (default f16, with q8_0/q4_0 etc. available), -fa/--flash-attn (default auto), --prio

process priority (llama.cpp server README). Metric surface, confirmed: llama.cpp does expose a Prometheus endpoint under --metrics, including llamacpp:requests_processing,

llamacpp:requests_deferred, llamacpp:prompt_tokens_seconds, llamacpp:predicted_tokens_seconds, llamacpp:n_busy_slots_per_decode, llamacpp:prompt_tokens_total and llamacpp:tokens_predicted_total,

plus a /slots state endpoint (llama.cpp server README). The one genuine gap versus the GPU stack is that no KV-cache-utilization metric is listed, so occupancy must be derived from /slots. This is the

adopted configuration.


## GPU stack, retained as portability reference only

This subsection documents the accelerator configuration for the optional confirmation run and the future-work section; it is not the build you will ship. vLLM vllm serve (OpenAI-compatible). Verified current engine args (docs page dated 2026-08-24): --gpu-memory-utilization (default 0.92),

--kv-cache-memory-bytes, --block-size, --enable-prefix-caching, --num-

gpu-blocks-override (“Used for testing preemption”), --served-model-

name, and default --model Qwen/Qwen3-0.6B (vLLM engine args). Tuning levers: max_num_seqs, max_num_batched_tokens, gpu_memory_utilization,

plus --enforce-eager (vLLM tuning, 2026-08-20). The exact V1 metric names for that stack, retained for future- work/portability discussion only (docs dated 2026-08-03):

vllm:num_requests_running, vllm:num_requests_waiting, vllm:kv_cache_usage_perc, vllm:request_queue_time_seconds, vllm:time_to_first_token_seconds, vllm:inter_token_latency_seconds, vllm:e2e_request_latency_seconds, vllm:request_prefill_time_seconds, vllm:request_decode_time_seconds, vllm:request_prompt_tokens, vllm:request_generation_tokens, vllm:prompt_tokens_total, vllm:generation_tokens_total, vllm:request_success_total, vllm:prefix_cache_queries, vllm:prefix_cache_hits (vLLM metrics

design). Two traps documented on that page: (1) built-in Python/process metrics “are unavailable when --api-server-count > 1”; (2)

vllm:num_requests_swapped and vllm:cpu_cache_usage_perc are “Legacy

metric[s] related to the obsolete ‘swapped’ preemption mode” — do not build shedding logic on them (vLLM metrics design). These vLLM-stack notes do not apply to the CPU build below; they are

kept only in case a GPU confirmation run happens later.

## Load generation: k6 (primary) and Locust (secondary)

k6: constant-arrival-rate / ramping-arrival-rate (open model),

preAllocatedVUs sized by the documented formula, dropped_iterations recorded, and thresholds for machine-checked SLOs including p(95),

p(99.9) and http_req_failed: ['rate<0.01'] (k6 constant-arrival-rate,

k6 VU allocation, k6 thresholds). k6 metric types available for custom LLM metrics: Counter, Gauge, Rate, Trend, with names limited to “up to 128 symbols” of ASCII letters/numbers/underscores (k6 metrics).

Locust: LoadTestShape with tick() returning (users, spawn_rate) or (users, spawn_rate, user_classes), called ~1×/s, None to stop; separate files composed via locust -f locustfile.py,high_load.py; use_common_options = True if you need run_time/spawn_rate from CLI, read via self.runner.environment.parsed_options; abstract = True for

reusable base shapes (Locust custom load shapes). (inference) Use Locust for the multi-cohort story (legitimate UserA + heavy UserB on one timeline) and k6 for the statistically clean arrival-rate runs. Reference workload semantics (not installed): vllm bench serve flag semantics — --request-rate (default inf; finite values use “either a Poisson process or a Gamma distribution”), --burstiness, --max- concurrency (“Setting a value simulates backpressure”), --random-

input-len, --random-output-len, --ignore-eos, --ramp-up-strategy linear|exponential with --ramp-up-start-rps/--ramp-up-end-rps, and --

probe-request-rate which “sends single-token, text-only probe requests… alongside the main workload. Probes bypass --max- concurrency; their latency is reported separately” (vLLM benchmark CLI, 2026-09-01). Reuse this terminology and design in your own

client even though vLLM itself is not installed.


## Minimal architecture and metric flow

```
┌──────────────── k6 (open-model, arrival-rate) ────────────────┐
│ scenario A: normal (rate=R, burstiness≈1) │
│ scenario B: sudden spike (ramping-arrival-rate) │
│ scenario C: sustained flood (constant-arrival-rate, high R) │
│ scenario D: slow/low-rate heavy-cost (low R, max in+out toks) │
│ scenario P: legitimate PROBE cohort (small, constant rate) │
│ HTTP /v1/chat/completions
│ YOUR SHIELD (FastAPI/Go reverse proxy) │
│ 1. tokenize → est_cost = in + w*max_tokens │
│ 2. per-key token bucket RESERVE (429 if over) │
│ 3. read llama.cpp /metrics + /slots: │
│ llamacpp:requests_deferred, slot state │
│ → shed low-priority fast (429 + Retry-After) │
│ 4. 2-class WFQ + wait-time aging → forward │
│ 5. on completion: reconcile actual token cost │
│ exports: shield_admitted/rejected/queued, │
│ est_vs_actual_cost, per-tier latency │
│ OpenAI-compatible
│ llama-server --metrics (CPU, dedicated host) │
│ knobs: -np (slots), -t / -tb (threads), │
│ -c (context), quantized small model │
│ signals: /metrics + /slots?fail_on_no_slot=1 │
│ /metrics (Prometheus text)
Prometheus ──► Grafana / matplotlib (charts from ACTUAL runs)
server-side: llamacpp:requests_processing,
llamacpp:requests_deferred,
llamacpp:prompt_tokens_seconds,
llamacpp:predicted_tokens_seconds,
llamacpp:n_busy_slots_per_decode,
llamacpp:prompt_tokens_total,
llamacpp:tokens_predicted_total, plus /slots occupancy
client-side: http_req_duration p50/p95/p99/Max, http_req_failed,
dropped_iterations, probe-cohort survival
analysis: per-run CSV of raw samples → bootstrap CI (latency
pct),
Wilson CI (survival / error / false-positive rate)
```

Metric names verified at llama.cpp server README (server-side signals) and k6 metrics / k6 thresholds (client-side); Wilson interval at NIST. vLLM sources (vLLM metrics design, vLLM engine args, vLLM tuning) apply only to the GPU portability-reference build described above, not to this CPU architecture. Architecture composition is an engineering recommendation (inference).

## Explicitly acknowledged gaps in AI- serving availability defenses (2024–2026)

Only gaps that the fetched source actually supports are listed. Each row quotes the source.


“most major LLM inference services have request rate limits… this rudimentary

VTC / Fairness in Serving LLMs, arXiv:2401.00588 (v1 31 Dec 2023, v2 5 Jun 2024)

Request-count notion of fairness also

results in under-utilization of the resources.” Fairness must instead be defined “based on a cost function that accounts for the number of input and output tokens processed.” “Token usage is charged after the response completes… Instead, the

rate limits ignore token cost

G1

Token-cost limiting is

stream completes, its token Envoy AI

inherently post- usage is charged at stream Gateway, Usage-

G2 hoc, so the first end, and later matching

based Rate

over-budget

requests are rejected with Limiting (fetched

request always 429.” Worked example: a 2026-09-08) gets through 1,000-token hourly limit

still permits a 1,200-token stream. “the first-come-first-served (FCFS) scheduling policy

Head-of-line

blocking under often leads to head-of-line vLLM RFC

G3 FCFS grows blocking issues… especially #16969 (22 Apr

with prompt length

as prompt lengths increase 2025) due to multi-turn interactions.” “batching multiple requests leads to an interleaving of

Prefill/decode heterogeneity forces a throughput- latency tradeoff that plain batching cannot resolve KV-cache exhaustion forces preemption, and preempted work is recomputed (wasted) KV-preserving preemption for

Sarathi-Serve, arXiv:2403.02310 (4 Mar 2024; v3 17 Jun 2024)

prefill and decode iterations which makes it challenging to achieve both high throughput and low latency.”

G4

“In such cases, vLLM can preempt requests to free up KV cache space… Preempted requests are recomputed when sufficient KV cache space becomes available.”

vLLM Optimization and Tuning (2026-08- 20)

G5

priority is still “there can still exist

open work; priority inversion between waiting and

priority inversions between the two [queues]… Sorting the two queues jointly is not possible without forcefully preempting our

vLLM RFC #6077 (2 Jul 2024)

G6

running queues requests from the running is unresolved queue.” without forced preemption

A participant “implemented scheduling logic external to vLLM, which is user aware… so each user gets it’s fair-share.” A maintainer agrees “it makes sense to have

No engine- internal cross-

vLLM RFC #6077 (2 Jul 2024)

G7 user fairness;

users route it out-of-band


out-of-band

majority of the prioritization logic outside vLLM.”

Starvation under

“it is still necessary to

length/memory- introduce a priority

promotion mechanism… If a request has been waiting in the queue for more than

aware scheduling

vLLM RFC #16969 (22 Apr 2025)

G8 needs an

explicit aging a certain threshold, its

priority should be

mechanism

that is not built increased.” in Priority-based Default Priority is 0;

shedding is

“Requests are only dropped

About GKE Inference Gateway (fetched 2026-09-08)

opt-in and off due to priority if their

G9 by default in a Priority is explicitly set to a

leading production gateway

value less than 0.” No fairness or starvation semantics documented. Mitigations include “Apply rate limiting and user

The leading security standard’s own mitigation list is request- count-centric

quotas…” while the same OWASP

page names “inputs of varying lengths” and “Resource-Intensive

LLM10:2025 Unbounded Consumption (28

G10

Queries” as attack vectors Apr 2025) without discussing token- cost limiting.

Load-generator shortcoming: closed-loop clients systematically hide overload (coordinated omission) Even open- model

Naïve rate-driven loggers report a 99.99th percentile of 1 ms where the truth is ~100 s — “wrong by a factor of 1,000x.”

Gil Tene, How NOT to Measure Latency, QCon SF 2012

G11

“k6 emits a

dropped_iterations metric k6 Arrival-rate

generators leak for each iteration that it

VU allocation (fetched 2026-09- 08)

G12

omission via dropped iterations Benchmark client concurrency limits contaminate reported latency unless separated Capacity modelled as

cannot run… can also indicate that system performance is degrading.”

With --max-concurrency set, client_queue_time must be added to --percentile- metrics; e2el_including_client_queue

vLLM Benchmark CLI (2026-09-01)

G13

is “omitted for --request-

rate=inf.”

“modeling capacity as ‘queries per second’…

QPS is a poor often makes for a poor

proxy for resource

metric… computing in real time the amount of

Google SRE,

G14 consumption; resources… consumed by Handling

per-request CPU

each individual request” is Overload genuinely hard, “especially

accounting in for servers that don’t

real time is hard

implement a thread-per- request model.” “even in the case where


Fast rejection is not free and can itself cause collapse

G15

Output length is an

G16 attackable,

unbounded variable

rejecting requests saves significant resources… the Google SRE,

backend can become

Handling

overloaded even though the Overload vast majority of its CPU is spent just rejecting requests!” Poisoning “a single poisoned sample” at “less than \$1” raised repeated- output length to “16K

tokens, compared to 0.5K before poisoning,” triggering “endless outputs without generating an

arXiv:2410.10760 (14 Oct 2024)

[EOS] token.”

Worst-case (not Sponge examples increase average-case) “energy consumption by a

resource

factor of 10 to 200”; the

arXiv:2006.03463 (5 Jun 2020)

G17 analysis is the proposed defense shifts

missing defensive posture Statistical gap: naïve confidence- interval

analysis “from an average- case to a worst-case perspective.”

A CI-based stopping rule “caused the performance testing to stop at variable

G18

PT4Cloud

stopping rules times, from 2 hours to even are unreliable 7 weeks… average

for tail percentiles

accuracy… only 66.2%.”

Not claimed: No fetched source in this research stated that vLLM ships built-in per-tenant token-cost admission control or quantified the

gains from KV-cache-aware shedding. Those points remain n.a.

## Differentiators, four-day sequence, and cut list

## Top 3 differentiators most likely to score above the minimum bar

- 1. Cost-aware admission control with a measured estimate-vs- actual error analysis. Reserve in_tokens + w·max_tokens at admission and reconcile after completion, then publish the estimation error distribution. Directly targets G1/G2. (inference)

- 2. The slow/low-rate, high-token-cost profile that defeats a request-count limit, with the baseline shown failing. Run the same profile against (a) a textbook fixed RPS limiter and (b) the cost-aware limiter, on the identical seeded schedule, and show legitimate-probe survival diverge. (inference)

- 3. A statistically honest measurement harness: open-model arrival, dropped_iterations reported, percentiles + Max, bootstrap/Wilson CIs, and explicit overload-achieved evidence.

Runner-up if you have spare capacity: priority-tiered fair queuing with wait-time aging, presented alongside the vLLM maintainers’ own statements that joint-queue sorting and KV-preserving preemption are unsolved (#6077, #16969).


## Four-day implementation sequence (4 strong generalists, limited infra/security background)

## Day Workstream A (service + metrics) Workstream B (shield) Workstream C (load + stats)

llama-server --metrics up

with a small quantized model on a dedicated laptop;

k6 open-model

scrape /metrics and /slots;

Pass-through reverse proxy with per-request logging of in/out tokens and latency; no policy yet

confirm

Day 1

CSV of raw per-

llamacpp:requests_processing

and

llamacpp:requests_deferred

move under load; lower -np and -t until queueing starts at single-digit requests/s Freeze server config (model,

Baseline arm

Defense A: token-bucket reserve + reconcile, per- key, weighted output cost; fast 429 with Retry-After

-np, -t, -c); script one-

Day 2

command server start; fix arm interleaving and cooldown

runs; bootstrap +

Wilson CI scripts

working

Full matrix: 4

Defense B: shedding on

profiles × {off, A,

llamacpp:requests_deferred

A+B, A+B+C} ×5

Day Chart pipeline from real

runs; compute

3 runs (server + client panels) live /metrics and /slots;

goodput, survival,

Defense C: 2-class WFQ + wait-time aging

FP rate on

legitimate cohort

Re-run only the

Fix only the failure modes your data exposes (rejection-cost blowup, starvation of tier-B)

Day 4 Freeze code (am)

changed; finalize

CIs and the k6

thresholds

pass/fail gate

Economics slide

from §4 formulas

Day 4 (frozen) (pm)

(frozen)

demo script with a

live 90-second

overload

harness: 4 profiles

\+ probe cohort;

request samples;

dropped_iterations

captured

recorded (defense

off) ×5 seeded

and slot exhaustion from

arms you

\+ dated prices;

gap slide from §6;

## Explicit cut list (in the order you should cut)

- 1. Cut first: statistical anomaly detection (Defense D). Highest false- positive risk for the least judged credit; keep only if A+B+C are already measured.

- 2. Cut second: the optional rented-GPU confirmation run. It is a robustness footnote, not a judged criterion — the CPU results stand on their own.

- 3. Cut third: the graceful-degradation arm (capping max_tokens instead of rejecting). Cite the SRE ordering as future work instead.

- 4. Cut fourth: Defense C (priority WFQ) down to a static reservation with no aging — but say explicitly, citing vLLM RFC #16969, that aging is required to prevent starvation and is left as future work.

- 5. Cut fifth: run count from 5 → 3, and report CIs with the reduced n rather than dropping CIs.

Do not cut: open-model arrival, dropped_iterations reporting, percentiles + Max, the legitimate-probe cohort, and the paired seeded A/B design. Those five are what make the result defensible at all.


## Never cut / anti-patterns to avoid

- Do not report latency from a closed-loop client (Gil Tene).

- Do not report standard deviation of latency: “Don’t use or derive from std. deviation” (Gil Tene).

- Do not run the load generator on the same laptop as llama-server without saying so; the generator competes for the same cores and caps offered load.

- Do not forget --metrics: the llama.cpp Prometheus endpoint “is available only when the server is started with --metrics” (llama.cpp server README).

- Do not claim a KV-cache-utilization signal on llama.cpp; no such metric is listed, so derive occupancy from /slots and say so (llama.cpp server README).

- Do not run all defense-off trials before all defense-on trials on a thermally throttling laptop; interleave the arms.

- Do not trust a single k6 threshold object with duplicate keys: “Repeating the same JavaScript object key for a metric causes the rest to be silently ignored” (k6 thresholds).

- Do not quote AWS GPU \$/hr from memory; that table did not render in this session (n.a.): use the dated GCP us-central1 table instead (GCP).
