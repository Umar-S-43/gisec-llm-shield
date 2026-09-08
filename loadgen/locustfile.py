"""
Locust scenario for multi-cohort stress testing.
Runs legitimate users and attackers concurrently.

Usage:
    export $(grep LLAMA_SERVER_URL .env | xargs)
    python -m locust -f loadgen/locustfile.py --host=$LLAMA_SERVER_URL
"""

import os
import time
from locust import HttpUser, task, between, events
from datetime import datetime

LLAMA_SERVER_URL = os.getenv("LLAMA_SERVER_URL", "http://localhost:8080")


class LegitimateUser(HttpUser):
    """Low-volume user with priority header."""

    wait_time = between(1, 3)

    @task
    def query_completion(self):
        payload = {
            "prompt": "What is machine learning?",
            "n_predict": 50,
        }
        self.client.post(
            "/completion",
            json=payload,
            headers={
                "X-Priority": "legitimate",
            },
            timeout=60,
        )

    @task
    def query_chat(self):
        payload = {
            "messages": [
                {"role": "user", "content": "Hello, what's the weather?"}
            ],
            "n_predict": 30,
        }
        self.client.post(
            "/v1/chat/completions",
            json=payload,
            headers={
                "X-Priority": "legitimate",
            },
            timeout=60,
        )


class AttackUser(HttpUser):
    """High-volume attacker without priority header."""

    wait_time = between(0.1, 0.5)

    @task
    def spam_completion(self):
        payload = {
            "prompt": "spam query " * 10,
            "n_predict": 100,
        }
        # No X-Priority header: shield should rate-limit
        self.client.post(
            "/completion",
            json=payload,
            timeout=60,
        )


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Log test start."""
    print(f"\n{'='*60}")
    print(f"Locust Test Started: {datetime.now().isoformat()}")
    print(f"Target: {LLAMA_SERVER_URL}")
    print(f"{'='*60}\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Log test stop and results."""
    print(f"\n{'='*60}")
    print(f"Locust Test Stopped: {datetime.now().isoformat()}")
    print(f"Results saved to logs/")
    print(f"{'='*60}\n")
