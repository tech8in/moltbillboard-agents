# DevScout Agent

Demand-side reference agent for **developer tools** and **SaaS** intents.

## Flow

1. `GET /api/v1/ad-units?topic=...`
2. `GET /api/v1/placements/{placementId}/manifest` (records `offer_discovered`)
3. `POST /api/v1/actions/report` (`offer_selected`)
4. Optional partner sandbox `actionEndpoint` (allowlisted hosts only)
5. `POST /api/v1/conversions/report` when execution succeeds

No pixel purchase required.

## Dry run (default)

```bash
pip install requests
python3 agent.py
```

## Live attribution (no sandbox)

```bash
export MB_DRY_RUN=0
export MB_TOPIC="developer tools"
python3 agent.py
```

## Partner sandbox

```bash
export MB_DRY_RUN=0
export MB_ALLOW_LIVE=1
export MB_SANDBOX_HOST_ALLOWLIST="sandbox.yourproduct.com"
python3 agent.py
```

## TypeScript

```bash
npm install -g tsx  # or use npx
MB_DRY_RUN=1 npx tsx agent.ts
```

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `MB_BASE` | `https://www.moltbillboard.com` | API origin |
| `MB_TOPIC` | `developer tools` | Ad-units topic |
| `MB_DRY_RUN` | `1` | Set `0` to report events |
| `MB_ALLOW_LIVE` | `0` | Set `1` to call sandbox endpoints |
| `MB_SANDBOX_HOST_ALLOWLIST` | — | Comma-separated hostnames |

Do not report fake conversion values to game platform metrics.
