#!/usr/bin/env python3
"""
MoltBillboard reference agent — demand-side loop with skill-aligned safety defaults.

Implements the canonical flow from https://www.moltbillboard.com/SKILL.md:
  discover → manifest (offer_discovered) → offer_selected → action_executed → conversion

Read-only discovery works with no API key. Attribution reporting is off unless MB_ALLOW_REPORT=1.
Mutations (reserve, settle, purchase, pixel PATCH) are not implemented here; use Stripe/x402
flows from the skill only after explicit operator approval.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

from client import (
    DEFAULT_BASE_URL,
    MoltBillboardClient,
    MoltBillboardError,
    OfferAttribution,
    SUPPORTED_INTENTS,
)

DEFAULT_INTENT = "software.purchase"
FALLBACK_INTENTS = list(SUPPORTED_INTENTS)


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def env_bool(name: str, default: bool = False) -> bool:
    raw = env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def score_offer(offer: dict[str, Any], requested_intent: str) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    hints = offer.get("agentHints") if isinstance(offer.get("agentHints"), dict) else {}

    if offer.get("primaryIntent") == requested_intent:
        score += 30
        reasons.append("intent match")
    if offer.get("isPrimary"):
        score += 8
        reasons.append("primary offer")
    if hints.get("requiresAuth") is False:
        score += 4
        reasons.append("no auth required")
    if hints.get("expectedLatency") == "sync":
        score += 3
        reasons.append("sync latency")
    if hints.get("priceAvailable") is True:
        score += 2
        reasons.append("price available")
    return score, reasons


def score_placement_trust(placement: dict[str, Any]) -> tuple[int, list[str]]:
    trust = placement.get("trust") or {}
    score = 0
    reasons: list[str] = []

    if trust.get("domainVerified"):
        score += 25
        reasons.append("domain verified")
    if trust.get("publisherVerified"):
        score += 15
        reasons.append("platform-signed manifest")
    tier = trust.get("ownerTrustTier")
    if tier == "trusted_internal":
        score += 15
        reasons.append("trusted_internal owner")
    elif tier == "community_verified":
        score += 12
        reasons.append("community_verified owner")
    elif tier == "email_verified":
        score += 8
        reasons.append("email_verified owner")
    if trust.get("ownerVerificationStatus") == "homepage_verified":
        score += 10
        reasons.append("homepage verified")
    if trust.get("primaryDestinationStatus") == "verified_owner_domain":
        score += 10
        reasons.append("verified destination domain")
    return score, reasons


def pick_best_offer(
    placement: dict[str, Any],
    requested_intent: str,
) -> tuple[dict[str, Any], int, list[str]]:
    offers = placement.get("offers") or []
    if not offers:
        raise MoltBillboardError(f"Placement {placement.get('id')} has no offers.")

    best: tuple[int, dict[str, Any], list[str]] | None = None
    for offer in offers:
        offer_score, offer_reasons = score_offer(offer, requested_intent)
        if best is None or offer_score > best[0]:
            best = (offer_score, offer, offer_reasons)

    assert best is not None
    offer_score, offer, offer_reasons = best
    trust_score, trust_reasons = score_placement_trust(placement)
    total = offer_score + trust_score
    return offer, total, offer_reasons + trust_reasons


def attribution_from(placement: dict[str, Any], offer: dict[str, Any]) -> OfferAttribution:
    action_id = MoltBillboardClient.action_id_from_offer(offer)
    if not action_id:
        raise MoltBillboardError(f"Offer {offer.get('offerId')} missing manifest-issued actionId.")
    attr = offer.get("attribution") if isinstance(offer.get("attribution"), dict) else {}
    return OfferAttribution(
        action_id=action_id,
        action_issuer=attr.get("actionIssuer"),
        action_expires_at=attr.get("actionExpiresAt"),
        offer_id=offer["offerId"],
        placement_id=placement["id"],
    )


def discover_placements(
    client: MoltBillboardClient,
    intent: str,
    limit: int,
) -> list[dict[str, Any]]:
    placements = client.list_placements(intent=intent, limit=limit)
    if placements:
        return placements
    for fallback in FALLBACK_INTENTS:
        if fallback == intent:
            continue
        placements = client.list_placements(intent=fallback, limit=limit)
        if placements:
            print(f"No placements for {intent}; fell back to {fallback}.")
            return placements
    raise MoltBillboardError("No live placements found for any supported intent.")


def discover_via_ad_units(
    client: MoltBillboardClient,
    topic: str,
    limit: int,
) -> str:
    units = client.list_ad_units(topic=topic, limit=limit)
    if not units:
        raise MoltBillboardError(f"No ad units for topic {topic!r}.")
    unit = max(
        units,
        key=lambda u: (
            20 if u.get("primaryIntent") in {"software.purchase", "subscription.register"} else 0,
            5 if u.get("actionEndpoint") else 0,
            u.get("placementId", ""),
        ),
    )
    placement_id = unit.get("placementId")
    if not placement_id:
        raise MoltBillboardError("Ad unit missing placementId.")
    print(f"Selected ad unit: {unit.get('title') or placement_id}")
    return placement_id


def run_demand_loop(args: argparse.Namespace) -> int:
    base = env("MB_BASE", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
    api_key = env("MB_API_KEY")
    allow_report = env_bool("MB_ALLOW_REPORT", default=False)
    dry_run = env_bool("MB_DRY_RUN", default=not allow_report)

    client = MoltBillboardClient(base_url=base, api_key=api_key)

    print("MoltBillboard agent — demand-side loop")
    print(f"  Base:          {base}")
    print(f"  Mode:          {args.mode}")
    print(f"  Intent/topic:  {args.intent or args.topic}")
    print(f"  Dry run:       {dry_run}")
    print(f"  Allow report:  {allow_report}")

    if args.mode == "ad-units":
        placement_id = discover_via_ad_units(client, args.topic, args.limit)
        envelope = client.fetch_manifest(placement_id)
    else:
        placements = discover_placements(client, args.intent, args.limit)
        print(f"  Candidates:    {len(placements)}")
        ranked: list[tuple[int, str, dict[str, Any], dict[str, Any], list[str]]] = []
        for summary in placements[: args.limit]:
            pid = summary["id"]
            envelope = client.fetch_manifest(pid)
            placement = client.placement_from_manifest(envelope)
            offer, score, reasons = pick_best_offer(placement, args.intent)
            ranked.append((score, pid, placement, offer, reasons))
            print(f"  - {pid}: score={score}")

        _, placement_id, placement, offer, reasons = max(
            ranked,
            key=lambda row: (row[0], row[1]),
        )
        envelope = {"placement": placement}
        print("\nSelected placement")
        print(f"  ID:     {placement_id}")
        print(f"  Offer:  {offer['offerId']}")
        print("  Reasons:")
        for reason in reasons:
            print(f"    - {reason}")

    placement = client.placement_from_manifest(envelope)
    offer, _, _ = pick_best_offer(placement, args.intent)
    attr = attribution_from(placement, offer)

    print("\nAttribution handle")
    print(f"  actionId:   {attr.action_id}")
    print(f"  expiresAt:  {attr.action_expires_at or '—'}")
    print(f"  endpoint:   {offer.get('actionEndpoint') or '—'}")

    if dry_run or not allow_report:
        print("\nDry run complete. Set MB_ALLOW_REPORT=1 and MB_DRY_RUN=0 to post events.")
        return 0

    selected = client.report_action(attr, "offer_selected", metadata={"intent": args.intent})
    print(f"\noffer_selected:     {selected.get('success')}")

    executed = client.report_action(attr, "action_executed", metadata={"intent": args.intent})
    print(f"action_executed:    {executed.get('success')}")

    conversion = client.report_conversion(
        attr,
        conversion_type=args.conversion_type,
        value=args.conversion_value,
        currency=args.currency,
        metadata={"intent": args.intent},
    )
    print(f"conversion:         {conversion.get('success')}")

    stats = client.placement_stats(attr.placement_id)
    by_type = stats.get("stats", {}).get("byType", {})
    print("\nStats snapshot")
    print(f"  offer_discovered:    {by_type.get('offer_discovered', 0)}")
    print(f"  offer_selected:      {by_type.get('offer_selected', 0)}")
    print(f"  action_executed:     {by_type.get('action_executed', 0)}")
    print(f"  conversion_reported: {by_type.get('conversion_reported', 0)}")

    print("\nDemand loop completed.")
    return 0


def run_register(args: argparse.Namespace) -> int:
    base = env("MB_BASE", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
    client = MoltBillboardClient(base_url=base)
    identifier = args.identifier or f"agent-{uuid.uuid4().hex[:10]}"
    result = client.register_agent(
        identifier=identifier,
        name=args.name,
        description=args.description,
        homepage=args.homepage,
    )
    api_key = result.get("apiKey") or result.get("api_key")
    print("Registered agent")
    print(f"  identifier:  {identifier}")
    print(f"  apiKey:        {(api_key or '')[:20]}…" if api_key else "  apiKey:        (missing)")
    print(f"  profileUrl:    {result.get('profileUrl', '—')}")
    print(f"  verifyUrl:     {result.get('verifyUrl', '—')}")
    print("\nSave MB_API_KEY before closing this terminal.")
    return 0


def run_balance(_args: argparse.Namespace) -> int:
    base = env("MB_BASE", DEFAULT_BASE_URL) or DEFAULT_BASE_URL
    api_key = env("MB_API_KEY")
    if not api_key:
        print("Set MB_API_KEY to check credit balance.", file=sys.stderr)
        return 1
    client = MoltBillboardClient(base_url=base, api_key=api_key)
    balance = client.credit_balance()
    print(json_dump(balance))
    return 0


def json_dump(data: Any) -> str:
    return json.dumps(data, indent=2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MoltBillboard reference agent (demand-side, read-first).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demand = sub.add_parser("demand", help="Run discovery → manifest → attribution loop")
    demand.add_argument(
        "--mode",
        choices=("placements", "ad-units"),
        default=env("MB_DISCOVERY_MODE", "placements") or "placements",
    )
    demand.add_argument("--intent", default=env("MB_INTENT", DEFAULT_INTENT))
    demand.add_argument("--topic", default=env("MB_TOPIC", "developer tools"))
    demand.add_argument("--limit", type=int, default=int(env("MB_LIMIT", "3") or "3"))
    demand.add_argument("--conversion-type", default=env("MB_CONVERSION_TYPE", "lead"))
    demand.add_argument("--conversion-value", type=float, default=float(env("MB_CONVERSION_VALUE", "0") or "0"))
    demand.add_argument("--currency", default=env("MB_CURRENCY", "USD") or "USD")
    demand.set_defaults(func=run_demand_loop)

    reg = sub.add_parser("register", help="Register a new public agent identity (read-only key issuance)")
    reg.add_argument("--identifier")
    reg.add_argument("--name", default="MoltBillboard Reference Agent")
    reg.add_argument("--description", default="Reference agent from moltbillboard-agents")
    reg.add_argument("--homepage")
    reg.set_defaults(func=run_register)

    bal = sub.add_parser("balance", help="Check credit balance (requires MB_API_KEY)")
    bal.set_defaults(func=run_balance)

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
