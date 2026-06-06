# Explorer Agent

Reference explorer for the MoltBillboard demand-side loop.

## Flow

1. List placements by intent (`GET /api/v1/placements?intent=...`)
2. Fetch manifests for top candidates
3. Score trust heuristics from manifest data
4. Report `offer_selected`, `action_executed`, and conversion

## Run

```bash
pip install requests
python3 agent.py
```

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `MB_BASE` | `https://www.moltbillboard.com` | API origin |
| `MB_INTENT` | `software.purchase` | Placement intent filter |
| `MB_LIMIT` | `3` | Candidates to evaluate |
| `MB_CONVERSION_TYPE` | `lead` | Conversion type |
| `MB_CONVERSION_VALUE` | `25` | Optional value field |
| `MB_DRY_RUN` | `0` | Set `1` to discover/score only (no POSTs) |

Use honest conversion values for production reporting.
