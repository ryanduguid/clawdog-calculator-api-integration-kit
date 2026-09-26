#!/usr/bin/env python3
"""
ClawDog Calculator-Constellation REST API - Python quickstart.

A complete discover-then-invoke walkthrough using only the Python standard library.
No third-party dependencies. Runs against the live production API by default;
override with the CLAWDOG_CALC_API_URL environment variable to point at a different
deployment (for example, a local mock during CI Gate 1).

Usage:
    python3 quickstart.py

Environment variables:
    CLAWDOG_CALC_API_URL    Base URL (default: production Cloud Run URL).
    CLAWDOG_CALC_TIMEOUT    Per-request timeout in seconds (default: 30).
    CLAWDOG_CALC_RETRIES    Max retries on 5xx (default: 3).
"""

import http.client
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request

from probe_contract import CALCULATOR, PERIOD, decode_json, validate_calculation, validate_discovery

DEFAULT_BASE_URL = (
    "https://fbt-calculator-api-8340695160.australia-southeast1.run.app"
)
BASE_URL = os.environ.get("CLAWDOG_CALC_API_URL", DEFAULT_BASE_URL)
TIMEOUT = 30.0
MAX_RETRIES = 3


def http_get(path: str) -> object:
    """GET against the calc-api with retry-with-jitter on 5xx."""
    url = f"{BASE_URL}{path}"
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"Accept": "application/json"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return decode_json(resp.read())
        except urllib.error.HTTPError as e:
            if 500 <= e.code < 600 and attempt < MAX_RETRIES:
                delay = (2**attempt) * 0.5 + random.uniform(0, 0.5)
                print(
                    f"  ⚠ GET {path} → HTTP {e.code}; retry {attempt + 1}/{MAX_RETRIES} in {delay:.2f}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
                e.close()
                last_err = e
                continue
            raise
    raise last_err  # type: ignore[misc]


def http_post(path: str, body: dict) -> object:
    """POST against the calc-api with retry-with-jitter on 5xx."""
    url = f"{BASE_URL}{path}"
    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return decode_json(resp.read())
        except urllib.error.HTTPError as e:
            if 500 <= e.code < 600 and attempt < MAX_RETRIES:
                delay = (2**attempt) * 0.5 + random.uniform(0, 0.5)
                print(
                    f"  ⚠ POST {path} → HTTP {e.code}; retry {attempt + 1}/{MAX_RETRIES} in {delay:.2f}s",
                    file=sys.stderr,
                )
                time.sleep(delay)
                e.close()
                last_err = e
                continue
            raise
    raise last_err  # type: ignore[misc]


def run() -> int:
    print(f"Base URL: {BASE_URL}\n")

    # ---- Step 1: Discover ----
    print("=== Step 1 - GET /v1/calculators ===")
    calcs = http_get("/v1/calculators")
    validate_discovery(calcs)
    print(f"Discovered {len(calcs)} calculators.\n")
    for c in calcs[:5]:
        print(f"  • {c.get('calc_uri', '(none)')}")
        print(f"      label:      {c.get('label', '(none)')}")
        print(f"      method:     {c.get('method', '(none)')}")
        print(f"      periods:    {c.get('supported_periods', '(none)')}")
        print(f"      input ref:  {c.get('input_schema_ref', '(none)')}")
    if len(calcs) > 5:
        print(f"  … and {len(calcs) - 5} more.\n")
    else:
        print()

    # ---- Step 2: Invoke FBT Car-Operating-Cost ----
    calc_uri = CALCULATOR
    # Period URNs are domain-prefixed: urn:sbrm:period:<domain>:<period_id>.
    # For FBT, the domain is "fbt"; the FY2026 period URN is therefore:
    period_uri = PERIOD
    print(
        f"=== Step 2 - POST /v1/calculators/{calc_uri}/{period_uri} ==="
    )
    # A canonical fixture for FBT Car-Operating-Cost. Real inputs vary by
    # vehicle, fuel type, business-use percentage; this is a minimum-viable
    # call to demonstrate the wire shape. See CONTRACT.md § 2.2 and the
    # OpenAPI schema FBTCarOperatingCostInput for the full field set.
    #
    # Note the camelCase JSON field names + that businessUsePercentage is
    # expressed on a 0–100 scale (not 0–1).
    fixture = {
        "businessUsePercentage": 65,
        "formOfFinance": "owned",
        "fuelRepairsServicing": 8000.00,
        "registrationInsurance": 2000.00,
        "employeeContribution": 0.00,
        "daysHeldInFBTYear": 365,
        # Note: acquisitionCost (chained-DV walk path) and openingDepreciatedValue
        # (legacy single-year primitive) are mutually exclusive. We choose the
        # chained-DV walk path. See FBTCarOperatingCostInput schema for detail.
        "acquisitionCost": 45000.00,
        "acquisitionDate": "2024-04-01",
    }
    print(f"Request body: {json.dumps(fixture, indent=2)}\n")

    result = http_post(f"/v1/calculators/{calc_uri}/{period_uri}", fixture)
    validate_calculation(result)
    print("Response:")
    print(json.dumps(result, indent=2))
    print(f"\n  Taxable value: {result['taxable_value']}")
    print(f"  Advisory: {result['advisory']['disclaimer']}")

    print("\n=== Done ===")
    return 0


def main() -> int:
    global TIMEOUT, MAX_RETRIES
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")
    try:
        TIMEOUT = float(os.environ.get("CLAWDOG_CALC_TIMEOUT", "30"))
        MAX_RETRIES = int(os.environ.get("CLAWDOG_CALC_RETRIES", "3"))
        if not math.isfinite(TIMEOUT) or TIMEOUT <= 0 or MAX_RETRIES < 0:
            raise ValueError("Timeout must be positive and finite; retries must be non-negative")
        return run()
    except urllib.error.HTTPError as error:
        print(f"Request failed: HTTP {error.code}", file=sys.stderr)
        try:
            print(json.dumps(decode_json(error.read()), indent=2), file=sys.stderr)
        except (OSError, ValueError, http.client.HTTPException):
            pass
        finally:
            error.close()
    except (OSError, ValueError, http.client.HTTPException) as error:
        print(f"Quickstart failed: {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
