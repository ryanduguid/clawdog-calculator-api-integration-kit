# Architecture

> Design context for partner developers. Read this before writing integration code; it explains the *shape* of what you're integrating against without diving into wire details (that's [CONTRACT.md](CONTRACT.md)) or production concerns (that's [OPERATIONAL.md](OPERATIONAL.md)).

## 1. The Calculator Constellation pattern

The ClawDog Calculator Constellation is not one omnibus calculator. It is a **constellation of small, deterministic, statute-bound reasoners**, each of which:

- Computes one specific tax-law artefact (e.g. *the taxable value of an Australian FBT Car-Parking benefit under the 12-Week Register method per FBTAA s.39GB*).
- Is identified by a **URN** of the form `urn:sbrm:calculator:<domain>:<method-slug>` (e.g. `urn:sbrm:calculator:fbt:car-parking-register-12wk`).
- Has a well-defined **input schema** declared in the OpenAPI spec (e.g. `FBTCarParkingRegister12WkInput`).
- Is bound to a specific **statute-of-record citation** (e.g. `FBTAA s.39GB`).
- Returns calculator-specific JSON. The generic invocation response is untyped in the pinned schema; see [CONTRACT.md](CONTRACT.md) for the fields checked by the example.

### Why a constellation rather than one omnibus calculator

Three reasons, in increasing load-bearing-ness:

1. **Reproducibility.** A single Prolog rule with one statute citation is easy to audit. An omnibus calculator that branches across 20 methods internally is not.
2. **Versioning.** When the Australian Taxation Office updates the statutory rate for one method (e.g. car-parking statutory rate per s.39FA), only that calculator's `supported_periods` extends. Other calculators need not change.
3. **Partner composition.** You probably need only some calculators. The constellation lets you bind to the 3 or 5 you actually use, with the dependency surface narrowing to exactly those input schemas.

### URN choice

We use URNs (not numeric IDs, not free-text slugs) because a URN is **simultaneously human-readable and machine-stable**. The URN `urn:sbrm:calculator:fbt:car-operating-cost` carries the full namespace (`sbrm`), the domain (`calculator:fbt`), and the method (`car-operating-cost`) in a string that is safe to embed in URLs, log lines, and database columns without escaping. SBRM is the LodgeiT vocabulary for tax/accounting concepts; the calculator URN namespace is one of several within it.

### Period URN

Each invocation pairs a calculator URN with a domain-prefixed period URN: `urn:sbrm:period:<domain>:<period_id>`. For example, the FBT example uses `urn:sbrm:period:fbt:fy2026`, while depreciation uses its own domain. A domainless period such as `urn:sbrm:period:fy2026` is not interchangeable.

Read the selected calculator's `supported_periods` from `GET /v1/calculators`. The examples verify that their FY2026 period is advertised before invoking it; they do not assume an earlier period is available.

## 2. Dual-surface exposure (REST + MCP)

Calculator capabilities are exposed through REST routes and MCP tools. Discover the required capability and inspect its schema for the chosen surface:

### REST

The primary surface for partner integrations. Selected paths:

| Path | Purpose |
|---|---|
| `GET /v1/calculators` | Discover the URN list + per-URN metadata. |
| `POST /v1/calculators/{calc_uri}/{period_uri}` | **Invoke** a specific calculator for a specific period. |
| `POST /v1/calculators/depreciation/audit/{period_uri}` | Specialised invoke for the depreciation-audit calculator (multi-asset input shape). |
| `GET /v1/rates/{period_uri}` | List the statutory rate-table for a period (FBT rate, gross-up factors, indexed thresholds, etc.). |
| `GET /v1/rates/{period_uri}/{rate_id}` | Fetch one specific rate value. |
| `POST /mcp` | The MCP surface (see below). |
| `GET /healthz`, `GET /livez` | Internal health probes (documented in OpenAPI but not currently routed at the Cloud Run frontend; do not rely on these for liveness — use `GET /v1/calculators` if you need a 200-or-not signal). |

### MCP (Model Context Protocol)

JSON-RPC 2.0 at `POST /mcp` exposes calculator tools. Use `tools/list` to discover their current names and input schemas.

Method coverage:

- `tools/list` — equivalent to `GET /v1/calculators` but returns full JSON Schema per tool.
- `tools/call` — equivalent to `POST /v1/calculators/{calc_uri}/{period_uri}` with the URN encoded into the tool name.

**Pick REST if** you're writing a traditional HTTP-client integration (web backend, mobile app, Excel add-in's taskpane HTML, a batch script).

**Pick MCP if** your integration target is an LLM agent (Claude Desktop, an OpenAI custom GPT with a remote MCP server, an Office add-in MCP host, a downstream agentic UI).

REST and MCP have different transport envelopes. The kit checks REST calculation output and MCP tool discovery; it does not establish result equivalence between them.

## 3. Topology + boundaries

Understanding where the kit ends and your code begins, and where the calc-api ends and the FBT-engine begins, prevents whole categories of bugs.

### The outsource boundary inside the substrate

The calc-api (which this kit talks to) is itself a thin Egress over a deeper Prolog engine. There is one engine per domain (the FBT engine, the depreciation engine, etc.); each engine speaks a private wire protocol. The calc-api wraps those engines into the public REST + MCP surface you see.

**Partner consequence:** you do not, and should not, integrate directly with the engines. The calc-api is the **only stable public surface**. The engine wire is private and unversioned and will change shape without notice.

### The partner-developer boundary

The kit and the partner application are both **Egress Interfaces** — each owns its own state, its own CI, and its own deploy contract. Specifically:

| Concern | Kit (this repo) | Your integration |
|---|---|---|
| OpenAPI snapshot freshness | Yes (`openapi/`) | No (consume the kit's pin or pin your own) |
| Example code correctness | Yes (`examples/`) | No (your code, your CI) |
| Live-substrate availability | We probe it (CI Gate 2) | You probe it (your own production checks) |
| LodgeiT statute-of-record citations | Yes (`docs/CONTRACT.md`) | No (consume our citations) |
| Your customer's deployment, auth, audit logs, data privacy | No | Yes (you own this entirely) |

This kit explicitly does NOT prescribe:

- How you structure your code.
- Which dependency-injection container you use.
- Which test framework you use.
- Where you deploy.
- How you authenticate your end-users.
- How you log API responses (especially around customer-data residency).

We define the contract; you implement the integration. We don't reach across the boundary.

### Why we don't ship a wrapper SDK

The kit supplies examples rather than a wrapper SDK. Generated clients from your preferred OpenAPI toolchain (NSwag for .NET, Kiota, openapi-python-client) can provide typed bindings where the snapshot declares concrete schemas. The generic calculation response remains untyped. See [`openapi/README.md`](../openapi/README.md) for the regeneration commands.

If the constellation grows to a size where a wrapper SDK starts to make sense, we'll ship per-language SDKs as separate repos, each with its own versioning track. We're not there yet.

## 4. Repository classification

This kit is an **Egress Interface** in the LodgeiT topology vocabulary — state flows out from upstream sources (the live API, the architectural canon, the worked examples) into the kit, but the kit is not the canonical source for any of those — it's a publication.

What that means for you:

- The kit's CI fires *here* (this repo). It does not depend on any upstream CI gates.
- If you find a bug in the kit's docs or examples, you fix it here.
- If you find a bug in the substrate (the calc-api itself, the engine's calculation, the statute-of-record citation), you file via the `service-issue` template and we route it to the calc-api repo for fix. The kit does not carry substrate fixes.

## 5. Versioning model

The kit and the upstream API version independently:

- **Kit semver** (`v0.1.0` at this scaffold) — strict semver. Bumps when the scaffolding changes shape: docs reorganised, examples added/removed, CI gates added, issue templates changed.
- **Pinned API version** (`info.version: 0.1.0a0` in the snapshot) — what the upstream API declared at the moment of pin. We bump this when we refresh the snapshot. Major refreshes (where the contract shape changes in a way that breaks our examples) trigger a kit major-version bump.

**For partner integrations:** pin the kit version in your dependency manifest. When the kit bumps to a new version, read the CHANGELOG, regenerate your client from the new snapshot, run your CI, and ship.

## 6. Where to next

- [CONTRACT.md](CONTRACT.md) — the wire shape per route.
- [OPERATIONAL.md](OPERATIONAL.md) — running in production.
- [`../examples/`](../examples/) — runnable code.
- [`../openapi/README.md`](../openapi/README.md) — client-regeneration discipline.
