# Python quickstart

Runnable example for the ClawDog Calculator-Constellation REST API.

## Requirements

- Python 3.11+.
- No third-party dependencies (stdlib only).

## Run

```bash
python3 quickstart.py
```

This will:

1. `GET /v1/calculators` and print the first 5 calculator URNs with their metadata.
2. `POST /v1/calculators/urn:sbrm:calculator:fbt:car-operating-cost/urn:sbrm:period:fbt:fy2026` with a canonical fixture for the FBT Car Operating-Cost method.
3. Print the full response payload (taxable value, statutory algebra trace, manifest of rate-table sources consumed, advisory block).

Expected runtime: ~1–4 seconds against a warm production container; up to ~6 seconds on a cold start. The default timeout is 30 seconds per request, with up to 3 retries on 5xx.

The command returns 0 only after discovery advertises the selected calculator and period and the calculation contains a two-decimal `taxable_value` string and a non-blank advisory disclaimer. It allows additional calculators and response fields. Failures return 1 and do not print `=== Done ===`. This smoke test does not independently verify the tax amount.

## Customising

| Environment variable | Default | Purpose |
|---|---|---|
| `CLAWDOG_CALC_API_URL` | `https://fbt-calculator-api-8340695160.australia-southeast1.run.app` | Base URL. Override to point at a mock (CI Gate 1) or a different deployment. |
| `CLAWDOG_CALC_TIMEOUT` | `30` | Per-request timeout in seconds. |
| `CLAWDOG_CALC_RETRIES` | `3` | Max retries on 5xx with exponential backoff + jitter. |

## What the example demonstrates

- **URN-based identification.** Calculators are addressed by URN, periods by domain-prefixed URN. The example shows the exact URL-shape.
- **Domain-prefixed periods.** `urn:sbrm:period:fbt:fy2026`, not `urn:sbrm:period:fy2026`. Consume the period URN from the discovery response; do not hard-code your local guess.
- **camelCase request bodies.** `businessUsePercentage`, not `business_use_percentage`. The OpenAPI schema declares the field names; the kit example honours them verbatim.
- **0–100 percentage scale.** `businessUsePercentage: 65` means 65%, not 6500%. Verify against the OpenAPI schema's `description` field.
- **Mutually-exclusive inputs.** `acquisitionCost` (chained-DV walk path) and `openingDepreciatedValue` (legacy single-year primitive) are mutually exclusive — supply one, not both. The substrate returns a structured 502 with `error: calculation_failed` if you violate the constraint.
- **Retry-with-jitter on 5xx.** Three retries with exponential backoff starting at 500 ms with up to 500 ms of random jitter.
- **Graceful failure mode.** If the substrate returns a 4xx (your request is malformed) or 502 (resolver gap, e.g. mutually-exclusive input violation), the example prints any available structured detail and exits with status 1. Transport errors, invalid JSON and unusable results also fail.

## Next steps

After running this example successfully:

- Read [`../../docs/CONTRACT.md`](../../docs/CONTRACT.md) for selected URNs and per-route contracts.
- Read [`../../docs/OPERATIONAL.md`](../../docs/OPERATIONAL.md) for production retry and backpressure shape.
- See [`../dotnet/`](../dotnet/) for the C# .NET equivalent.
- Regenerate a strongly-typed client from the OpenAPI snapshot per [`../../openapi/README.md`](../../openapi/README.md).
