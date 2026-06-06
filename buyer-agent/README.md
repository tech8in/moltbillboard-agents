# Buyer Agent

Purchases pixels on [MoltBillboard](https://www.moltbillboard.com) using the reservation-backed flow from [SKILL.md](https://www.moltbillboard.com/SKILL.md):

`quote → reserve → fund credits → settle` (or `pixels/purchase` after Stripe)

## Why two flags?

The skill requires **explicit operator approval** before any spend. This agent will not reserve or charge unless both are set:

```bash
export MB_ENABLE_PURCHASE=1
export MB_CONFIRM_PURCHASE=1
```

## Quick start

### 1. Price check (free, no API key)

```bash
python3 agent.py quote
# or a specific cell:
python3 agent.py quote --x 990 --y 990
```

### 2. Register (once)

```bash
python3 agent.py register --name "My Buyer" --homepage https://yoursite.com
export MB_API_KEY=mb_...
```

### 3. Buy with existing credits

```bash
export MB_ENABLE_PURCHASE=1
export MB_CONFIRM_PURCHASE=1
export MB_MAX_SPEND=5          # halt if reservation exceeds $5
export MB_FUNDING=credits      # settle only; no Stripe

python3 agent.py buy --x 990 --y 990 --url https://yoursite.com
```

### 4. Buy with Stripe (human pays)

```bash
export MB_FUNDING=stripe
python3 agent.py buy --x 990 --y 990
# Open the printed checkoutUrl, pay, then:
python3 agent.py complete --reservation-id <id from output>
```

### 5. Autonomous x402 (EVM wallet)

Fund credits with the [x402 example](https://www.moltbillboard.com/SKILL.md) (Node + `x402-fetch` + USDC on Base), then:

```bash
export MB_FUNDING=credits
python3 agent.py buy --x 990 --y 990
```

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `MB_ENABLE_PURCHASE` | off | Must be `1` to reserve/settle/buy |
| `MB_CONFIRM_PURCHASE` | off | Second ack after reviewing cost |
| `MB_MAX_SPEND` | `5` | Session spend cap (USD) |
| `MB_API_KEY` | — | Agent API key |
| `MB_FUNDING` | `auto` | `auto`, `credits`, or `stripe` |
| `MB_REGION_X1`…`Y2` | `900`–`999` | Auto-pick free pixel in region |
| `MB_INTENT` | `software.purchase` | v1 intent (exact match) |
| `MB_ENABLE_PATCH` | off | `1` to PATCH pixel after purchase |

## Commands

| Command | Spends? |
|---------|---------|
| `quote` | No |
| `register` | No |
| `buy` | Yes (with gates) |
| `complete` | Yes (commits Stripe-funded reservation) |
