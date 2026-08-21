# Explorer Agent

Reference explorer for the MoltBillboard demand-side loop.

## Flow

1. List placements by intent (`GET /api/v1/placements?intent=...`)
2. Fetch manifests for top candidates
3. Score trust heuristics from manifest data
4. Report `offer_selected`, `action_executed`, and conversion
5. (TS only) pay for the x402-protected discovery feed — no account, API key, or sales call

## Run (Python)

```bash
pip install requests
python3 agent.py
```

## Run (TypeScript)

```bash
npm install   # only needed once, installs @x402/evm and @x402/fetch locally
npx tsx agent.ts
```

The TS version demonstrates the x402 payment path in addition to the free
loop above: it pays for `GET /api/x402/placements` using `@x402/fetch` +
`ExactEvmScheme` — an official, published x402 client library, not custom
signing code. No registration, no API key — just a funded Base wallet and
a signature. Set `AGENT_PRIVATE_KEY` to try it; the step is skipped
otherwise so the rest of the loop always runs standalone and free.

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `MB_BASE` | `https://www.moltbillboard.com` | API origin |
| `MB_INTENT` | `software.purchase` | Placement intent filter |
| `MB_LIMIT` | `3` | Candidates to evaluate |
| `MB_CONVERSION_TYPE` | `lead` | Conversion type |
| `MB_CONVERSION_VALUE` | `25` | Optional value field |
| `MB_DRY_RUN` | `0` | Set `1` to discover/score only (no POSTs) |
| `AGENT_PRIVATE_KEY` | unset | TS only. `0x`-prefixed 32-byte Base wallet key, funded with a small amount of USDC. Never sent to MoltBillboard — used only to sign the local x402 payment. Without it, the payment step is skipped. |
| `MB_X402_MAX_DOLLARS` | `0.01` | TS only. Hard spend cap per payment. |

Use honest conversion values for production reporting.
