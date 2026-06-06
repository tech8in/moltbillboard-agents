#!/usr/bin/env python3
"""
MoltBillboard Buyer Agent — reservation-backed pixel purchase.

Implements SKILL.md supply-side flow:
  quote → reserve → (fund credits) → settle OR pixels/purchase

Safety (required for any spend):
  MB_ENABLE_PURCHASE=1   — master switch for reserve/settle/checkout/purchase
  MB_CONFIRM_PURCHASE=1  — second explicit ack (prevents accidental runs)
  MB_MAX_SPEND           — max USD credits to spend this session (default 5)

Funding modes (MB_FUNDING):
  auto     — settle if balance covers reservation; else Stripe checkout URL
  credits  — settle only; fail if balance insufficient
  stripe   — always create checkout URL after reserve (human pays)

x402 (autonomous USDC) is not implemented in Python here; fund credits via
https://www.moltbillboard.com/SKILL.md x402 example, then run with MB_FUNDING=credits.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# Reuse shared client from moltbillboard-agent/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "moltbillboard-agent"))
from client import DEFAULT_BASE_URL, MoltBillboardClient, MoltBillboardError, SUPPORTED_INTENTS

DEFAULT_INTENT = "software.purchase"
DEFAULT_COLOR = "#667eea"


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def env_bool(name: str) -> bool:
    raw = env(name)
    return raw is not None and raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_float(name: str, default: float) -> float:
    raw = env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise MoltBillboardError(f"Invalid {name}: {raw}") from exc


def require_purchase_gates() -> None:
    if not env_bool("MB_ENABLE_PURCHASE"):
        raise MoltBillboardError(
            "Pixel purchase disabled. Set MB_ENABLE_PURCHASE=1 to allow reserve/settle/checkout."
        )
    if not env_bool("MB_CONFIRM_PURCHASE"):
        raise MoltBillboardError(
            "Set MB_CONFIRM_PURCHASE=1 after reviewing quote cost (explicit operator approval)."
        )


def session_spend_limit() -> float:
    return parse_float("MB_MAX_SPEND", 5.0)


def assert_within_spend_limit(cost: float) -> None:
    limit = session_spend_limit()
    if cost > limit:
        raise MoltBillboardError(
            f"Reservation cost ${cost:.2f} exceeds MB_MAX_SPEND=${limit:.2f}. "
            "Raise MB_MAX_SPEND only if you accept the spend."
        )


def balance_amount(balance_response: dict[str, Any]) -> float:
    for key in ("balance", "credits", "available", "remainingBalance"):
        value = balance_response.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return float(balance_response.get("amount", 0) or 0)


def find_available_pixel(client: MoltBillboardClient, region: tuple[int, int, int, int]) -> tuple[int, int]:
    x1, y1, x2, y2 = region
    data = client.pixels_available(x1, y1, x2, y2)
    pixels = data.get("pixels") or []
    if not pixels:
        raise MoltBillboardError(f"No available pixels in region {region}.")
    first = pixels[0]
    return int(first["x"]), int(first["y"])


def build_pixels(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.x is not None and args.y is not None:
        pixels = [{"x": args.x, "y": args.y, "color": args.color}]
        if args.x2 is not None and args.y2 is not None:
            x_lo, x_hi = sorted((args.x, args.x2))
            y_lo, y_hi = sorted((args.y, args.y2))
            pixels = [
                {"x": x, "y": y, "color": args.color}
                for x in range(x_lo, x_hi + 1)
                for y in range(y_lo, y_hi + 1)
            ]
        return pixels
    region = (args.region_x1, args.region_y1, args.region_x2, args.region_y2)
    x, y = find_available_pixel(
        MoltBillboardClient(base_url=args.base_url, api_key=env("MB_API_KEY")),
        region,
    )
    print(f"Auto-selected available pixel: ({x}, {y}) in region {region}")
    return [{"x": x, "y": y, "color": args.color}]


def run_quote(args: argparse.Namespace) -> int:
    client = MoltBillboardClient(base_url=args.base_url, source="buyer-agent")
    pixels = build_pixels(args)
    if args.intent not in SUPPORTED_INTENTS:
        raise MoltBillboardError(f"Unsupported intent {args.intent!r}. See SKILL.md for v1 intents.")

    metadata = {
        "url": args.url,
        "message": args.message,
        "intent": args.intent,
    }
    quote = client.claim_quote(pixels, metadata)
    summary = quote.get("summary") or {}
    total = summary.get("availableTotal") or summary.get("listPrice")
    conflicts = quote.get("conflicts") or []

    print("Quote preview (no spend)")
    print(f"  quoteId:         {quote.get('quoteId')}")
    print(f"  pixel count:     {summary.get('availableCount', len(pixels))}")
    print(f"  availableTotal:  ${total}")
    print(f"  expiresAt:       {quote.get('expiresAt')}")
    if conflicts:
        print(f"  conflicts:       {len(conflicts)}")
        for conflict in conflicts[:5]:
            print(f"    - {conflict}")
    print("\nTo purchase:")
    print("  export MB_API_KEY=mb_...")
    print("  export MB_ENABLE_PURCHASE=1 MB_CONFIRM_PURCHASE=1")
    print(f"  python3 agent.py buy --quote-id {quote.get('quoteId')} ...")
    print("  # or re-run buy with same coordinates (will quote again)")
    return 0


def run_buy(args: argparse.Namespace) -> int:
    require_purchase_gates()

    api_key = env("MB_API_KEY")
    if not api_key:
        raise MoltBillboardError("MB_API_KEY is required. Register at moltbillboard.com or use agent.py register.")

    client = MoltBillboardClient(base_url=args.base_url, api_key=api_key, source="buyer-agent")
    idem_prefix = env("MB_IDEMPOTENCY_PREFIX", "buyer-agent") or "buyer-agent"

    total_cost: float | None = None
    if args.quote_id:
        quote_id = args.quote_id
        print(f"Using existing quoteId: {quote_id}")
        total_cost = getattr(args, "expected_cost", None)
        if total_cost is not None:
            assert_within_spend_limit(total_cost)
        else:
            print("Warning: MB_EXPECTED_COST not set; spend limit checked after reserve.")
    else:
        if args.intent not in SUPPORTED_INTENTS:
            raise MoltBillboardError(f"Unsupported intent {args.intent!r}.")
        pixels = build_pixels(args)
        metadata = {"url": args.url, "message": args.message, "intent": args.intent}
        quote = client.claim_quote(pixels, metadata)
        quote_id = quote["quoteId"]
        summary = quote.get("summary") or {}
        total_cost = float(summary.get("availableTotal") or summary.get("listPrice") or 0)
        conflicts = quote.get("conflicts") or []
        if conflicts:
            raise MoltBillboardError(f"Quote has {len(conflicts)} conflict(s); pick different pixels.")

        print("Quote")
        print(f"  quoteId:        {quote_id}")
        print(f"  availableTotal: ${total_cost:.2f}")
        assert_within_spend_limit(total_cost)

    reserve_key = f"{idem_prefix}-reserve-{quote_id}"
    reservation = client.claim_reserve(quote_id, idempotency_key=reserve_key)
    reservation_id = reservation["reservationId"]
    total_cost = float(reservation.get("totalCost") or total_cost or 0)
    assert_within_spend_limit(total_cost)

    print("\nReserved")
    print(f"  reservationId: {reservation_id}")
    print(f"  totalCost:     ${total_cost:.2f}")
    print(f"  expiresAt:     {reservation.get('expiresAt')}")

    funding = (env("MB_FUNDING", "auto") or "auto").lower()
    balance = client.credit_balance()
    available = balance_amount(balance)
    print(f"\nCredit balance: ${available:.2f}")

    if funding in {"auto", "credits"} and available >= total_cost:
        settle_key = f"{idem_prefix}-settle-{reservation_id}"
        result = client.claim_settle(reservation_id, idempotency_key=settle_key)
        print("\nSettled with credits")
        print(f"  count:             {result.get('count')}")
        print(f"  cost:              {result.get('cost')}")
        print(f"  remainingBalance:  {result.get('remainingBalance')}")
        if args.patch_after:
            patch_owned_pixels(client, args)
        print("\nPurchase complete.")
        return 0

    if funding == "credits":
        raise MoltBillboardError(
            f"Insufficient credits (${available:.2f} < ${total_cost:.2f}). "
            "Fund via Stripe (MB_FUNDING=stripe) or x402, then retry."
        )

    # Stripe checkout path
    amount = max(1, int(total_cost) + (1 if total_cost % 1 else 0))
    if env("MB_CHECKOUT_AMOUNT"):
        amount = int(env("MB_CHECKOUT_AMOUNT") or amount)
    checkout_key = f"{idem_prefix}-checkout-{reservation_id}"
    checkout = client.credits_checkout(
        amount,
        quote_id,
        reservation_id,
        idempotency_key=checkout_key,
    )
    checkout_url = checkout.get("checkoutUrl") or checkout.get("checkout_url")
    print("\nStripe checkout required (human must pay)")
    print(f"  amount:      ${amount}")
    print(f"  checkoutUrl: {checkout_url}")
    print("\nAfter payment completes, run:")
    print(f"  export MB_ENABLE_PURCHASE=1 MB_CONFIRM_PURCHASE=1")
    print(f"  python3 agent.py complete --reservation-id {reservation_id}")

    if env_bool("MB_WAIT_FOR_STRIPE"):
        input("\nPress Enter after completing Stripe checkout...")
        return run_complete(
            argparse.Namespace(
                base_url=args.base_url,
                reservation_id=reservation_id,
                patch_after=args.patch_after,
                x=args.x,
                y=args.y,
                color=args.color,
                url=args.url,
                message=args.message,
                intent=args.intent,
            )
        )

    return 0


def run_complete(args: argparse.Namespace) -> int:
    require_purchase_gates()
    api_key = env("MB_API_KEY")
    if not api_key:
        raise MoltBillboardError("MB_API_KEY is required.")

    client = MoltBillboardClient(base_url=args.base_url, api_key=api_key, source="buyer-agent")
    idem_prefix = env("MB_IDEMPOTENCY_PREFIX", "buyer-agent") or "buyer-agent"
    reservation_id = args.reservation_id
    purchase_key = f"{idem_prefix}-purchase-{reservation_id}"

    result = client.pixels_purchase(reservation_id, idempotency_key=purchase_key)
    print("Purchased pixels (Stripe-funded)")
    print(f"  count:             {result.get('count')}")
    print(f"  cost:              {result.get('cost')}")
    print(f"  remainingBalance:  {result.get('remainingBalance')}")

    if args.patch_after:
        patch_owned_pixels(client, args)
    print("\nPurchase complete.")
    return 0


def patch_owned_pixels(client: MoltBillboardClient, args: argparse.Namespace) -> None:
    if args.x is None or args.y is None:
        return
    if not env_bool("MB_ENABLE_PATCH"):
        print("Skipping pixel PATCH (set MB_ENABLE_PATCH=1 to update after purchase).")
        return
    client.patch_pixel(
        args.x,
        args.y,
        color=args.color,
        url=args.url,
        message=args.message,
        intent=args.intent,
    )
    print(f"Patched pixel ({args.x}, {args.y})")


def run_register(args: argparse.Namespace) -> int:
    client = MoltBillboardClient(base_url=args.base_url, source="buyer-agent")
    identifier = args.identifier or f"buyer-{uuid.uuid4().hex[:10]}"
    result = client.register_agent(
        identifier=identifier,
        name=args.name,
        description=args.description,
        homepage=args.homepage,
    )
    api_key = result.get("apiKey") or result.get("api_key")
    print("Registered buyer agent")
    print(f"  identifier: {identifier}")
    print(f"  apiKey:     {(api_key or '')[:24]}…")
    print(f"  profile:    {result.get('profileUrl', '—')}")
    print("\nexport MB_API_KEY='...'  # save the full key from the API response")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MoltBillboard buyer agent (pixel purchase).")
    parser.add_argument("--base-url", default=env("MB_BASE", DEFAULT_BASE_URL))

    sub = parser.add_subparsers(dest="command", required=True)

    quote = sub.add_parser("quote", help="Price preview only (no API key, no spend)")
    quote.add_argument("--x", type=int)
    quote.add_argument("--y", type=int)
    quote.add_argument("--x2", type=int)
    quote.add_argument("--y2", type=int)
    quote.add_argument("--region-x1", type=int, default=int(env("MB_REGION_X1", "900") or 900))
    quote.add_argument("--region-y1", type=int, default=int(env("MB_REGION_Y1", "900") or 900))
    quote.add_argument("--region-x2", type=int, default=int(env("MB_REGION_X2", "999") or 999))
    quote.add_argument("--region-y2", type=int, default=int(env("MB_REGION_Y2", "999") or 999))
    quote.add_argument("--color", default=env("MB_COLOR", DEFAULT_COLOR))
    quote.add_argument("--url", default=env("MB_URL", "https://example.com"))
    quote.add_argument("--message", default=env("MB_MESSAGE", "Hello from buyer-agent"))
    quote.add_argument("--intent", default=env("MB_INTENT", DEFAULT_INTENT))
    quote.set_defaults(func=run_quote)

    buy = sub.add_parser("buy", help="Quote → reserve → fund → settle/purchase")
    buy.add_argument("--quote-id", default=env("MB_QUOTE_ID"))
    buy.add_argument("--x", type=int, default=int(env("MB_X")) if env("MB_X") else None)
    buy.add_argument("--y", type=int, default=int(env("MB_Y")) if env("MB_Y") else None)
    buy.add_argument("--x2", type=int)
    buy.add_argument("--y2", type=int)
    buy.add_argument("--region-x1", type=int, default=int(env("MB_REGION_X1", "900") or 900))
    buy.add_argument("--region-y1", type=int, default=int(env("MB_REGION_Y1", "900") or 900))
    buy.add_argument("--region-x2", type=int, default=int(env("MB_REGION_X2", "999") or 999))
    buy.add_argument("--region-y2", type=int, default=int(env("MB_REGION_Y2", "999") or 999))
    buy.add_argument("--color", default=env("MB_COLOR", DEFAULT_COLOR))
    buy.add_argument("--url", default=env("MB_URL", "https://example.com"))
    buy.add_argument("--message", default=env("MB_MESSAGE", "Hello from buyer-agent"))
    buy.add_argument("--intent", default=env("MB_INTENT", DEFAULT_INTENT))
    buy.add_argument("--patch-after", action="store_true", default=env_bool("MB_PATCH_AFTER"))
    buy.set_defaults(
        func=run_buy,
        expected_cost=float(env("MB_EXPECTED_COST")) if env("MB_EXPECTED_COST") else None,
    )

    complete = sub.add_parser("complete", help="Finish purchase after Stripe checkout")
    complete.add_argument("--reservation-id", required=True, default=env("MB_RESERVATION_ID"))
    complete.add_argument("--x", type=int, default=int(env("MB_X")) if env("MB_X") else None)
    complete.add_argument("--y", type=int, default=int(env("MB_Y")) if env("MB_Y") else None)
    complete.add_argument("--color", default=env("MB_COLOR", DEFAULT_COLOR))
    complete.add_argument("--url", default=env("MB_URL", "https://example.com"))
    complete.add_argument("--message", default=env("MB_MESSAGE", "Hello from buyer-agent"))
    complete.add_argument("--intent", default=env("MB_INTENT", DEFAULT_INTENT))
    complete.add_argument("--patch-after", action="store_true", default=env_bool("MB_PATCH_AFTER"))
    complete.set_defaults(func=run_complete)

    reg = sub.add_parser("register", help="Create agent + API key")
    reg.add_argument("--identifier")
    reg.add_argument("--name", default="MoltBillboard Buyer Agent")
    reg.add_argument("--description", default="Autonomous pixel buyer from moltbillboard-agents")
    reg.add_argument("--homepage")
    reg.set_defaults(func=run_register)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except MoltBillboardError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
