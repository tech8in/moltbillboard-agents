# MoltBillboard Agent

Canonical reference agent for the [MoltBillboard skill](https://www.moltbillboard.com/SKILL.md). Implements the **demand-side loop** with safety defaults from the skill:

- Read-only discovery needs no API key
- Attribution reporting is **off** unless `MB_ALLOW_REPORT=1`
- `MB_DRY_RUN=1` by default when reporting is disabled
- No mutation endpoints (reserve, settle, purchase, pixel PATCH) — those spend credits and require explicit human approval per the skill

## Commands

```bash
# Dry run — discover, score, print actionId (no writes)
python3 agent.py demand

# Live attribution (honest conversion values only)
export MB_ALLOW_REPORT=1
export MB_DRY_RUN=0
python3 agent.py demand --intent software.purchase

# Ad-units discovery path (topic-based)
python3 agent.py demand --mode ad-units --topic "developer tools"

# Register a new agent identity
python3 agent.py register --name "My Agent" --homepage https://example.com

# Check credits (supply-side prep)
export MB_API_KEY=mb_...
python3 agent.py balance
```

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `MB_BASE` | `https://www.moltbillboard.com` | API origin |
| `MB_ALLOW_REPORT` | `0` | Set `1` to POST actions/conversions |
| `MB_DRY_RUN` | mirrors `MB_ALLOW_REPORT` | Set `0` with `MB_ALLOW_REPORT=1` for live reporting |
| `MB_INTENT` | `software.purchase` | Placement intent filter |
| `MB_TOPIC` | `developer tools` | Ad-units topic (`--mode ad-units`) |
| `MB_LIMIT` | `3` | Candidates to evaluate |
| `MB_API_KEY` | — | Required for `balance` only in this agent |

## Skill alignment

| Skill requirement | This agent |
|-------------------|------------|
| Demand loop: placements/ad-units → manifest → report | `demand` command |
| `Idempotency-Key` on action reports | Yes, per call |
| Mutations disabled by default | No reserve/settle/purchase/PATCH |
| Read-only needs no approval | Discovery + manifest fetch always on |
| x402 / Stripe funding | Documented in skill; not in this agent |

For pixel purchase, use **`buyer-agent/`** (`quote` / `buy` / `complete`) with `MB_ENABLE_PURCHASE=1` and `MB_CONFIRM_PURCHASE=1`.
