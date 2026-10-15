"""Emulates an external bedside monitor that pushes signed readings to POST /devices/ingest.

Usage:
    python -m scripts.device_emulator --api http://localhost:8000 --monitor MON-01 --count 5

The per-device secret is derived from DEVICE_MASTER_KEY (read from the environment / .env),
exactly as a provisioning system would do when it configures a real device.
"""

import argparse
import json
import random
import secrets
import time

import httpx

from app.security.crypto import sign_device_payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--monitor", default="MON-01")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    for _ in range(args.count):
        body = json.dumps({
            "heart_rate": random.randint(68, 92), "spo2": random.randint(95, 99), "resp_rate": random.randint(13, 18),
            "systolic": random.randint(112, 132), "diastolic": random.randint(68, 82), "quality": "good",
        }, separators=(",", ":")).encode()
        ts = str(int(time.time()))
        nonce = secrets.token_urlsafe(18)
        headers = {
            "Content-Type": "application/json", "X-Device-Id": args.monitor, "X-Timestamp": ts, "X-Nonce": nonce,
            "X-Signature": sign_device_payload(args.monitor, ts, nonce, body),
        }
        resp = httpx.post(f"{args.api.rstrip('/')}/devices/ingest", content=body, headers=headers, timeout=10)
        print(resp.status_code, resp.json())
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
