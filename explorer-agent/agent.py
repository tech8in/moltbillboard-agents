#!/usr/bin/env python3

import json
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
from urllib import error, parse, request


INTENTS = [
    "travel.booking.flight",
    "travel.booking.hotel",
    "food.delivery",
    "transport.ride_hailing",
    "software.purchase",
    "subscription.register",
    "freelance.hiring",
    "commerce.product_purchase",
    "finance.loan_application",
    "finance.insurance_quote",
]
DEFAULT_BASE_URL = "https://www.moltbillboard.com"
DEFAULT_INTENT = "software.purchase"
DEFAULT_LIMIT = 3


@dataclass
class Candidate:
    placement_id: str
    manifest: Dict[str, Any]
    offer: Dict[str, Any]
    score: int
    reasons: List[str]


def env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def parse_float(name: str, default: float) -> float:
    raw = env(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {name}: {raw}") from exc


def api_request(
    base_url: str,
    method: str,
    path_or_url: str,
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Any:
    url = path_or_url if path_or_url.startswith(("http://", "https://")) else parse.urljoin(base_url, path_or_url)
    data = None
    request_headers = {"Accept": "application/json"}

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    if headers:
        request_headers.update(headers)

    req = request.Request(url, data=data, headers=request_headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return None
            return json.loads(raw)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method.upper()} {url} failed with {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"{method.upper()} {url} failed: {exc.reason}") from exc


def discover_placements(base_url: str, requested_intent: Optional[str], limit: int) -> Dict[str, Any]:
    intents: Iterable[str] = [requested_intent] if requested_intent else INTENTS

    for intent in intents:
        query = parse.urlencode({"intent": intent, "limit": limit})
        data = api_request(base_url, "GET", f"/api/v1/placements?{query}")
        placements = data.get("placements", [])
        if placements:
            return {"intent": intent, "placements": placements}

    raise RuntimeError("No live placements found for the requested discovery intents.")


def score_manifest_offer(manifest: Dict[str, Any], requested_intent: str) -> Candidate:
    placement = manifest["placement"]
    trust = placement.get("trust") or {}
    offers = placement.get("offers") or []
    placement_id = placement["id"]
    if not offers:
        raise RuntimeError(f"Placement {placement_id} did not expose any offers.")
    scored_offers: List[tuple[int, Dict[str, Any], List[str]]] = []
    for offer in offers:
        score = 0
        reasons: List[str] = []
        agent_hints = offer.get("agentHints") if isinstance(offer.get("agentHints"), dict) else {}

        if offer.get("primaryIntent") == requested_intent:
            score += 30
            reasons.append("offer matches requested intent")

        if offer.get("isPrimary"):
            score += 8
            reasons.append("offer is marked primary")

        if agent_hints.get("requiresAuth") is False:
            score += 4
            reasons.append("offer does not require auth")

        if agent_hints.get("expectedLatency") == "sync":
            score += 3
            reasons.append("offer is marked sync")

        if agent_hints.get("priceAvailable") is True:
            score += 2
            reasons.append("offer advertises price availability")

        scored_offers.append((score, offer, reasons))

    offer_score, best_offer, offer_reasons = max(
        scored_offers,
        key=lambda scored_offer: (scored_offer[0], scored_offer[1].get("offerId", "")),
    )

    score = offer_score
    reasons = list(offer_reasons)

    if trust.get("domainVerified"):
        score += 25
        reasons.append("placement passes homepage-to-destination domain verification")

    if trust.get("publisherVerified"):
        score += 15
        reasons.append("manifest is platform-signed")

    if trust.get("ownerTrustTier") == "trusted_internal":
        score += 15
        reasons.append("owner trust tier is trusted_internal")
    elif trust.get("ownerTrustTier") == "community_verified":
        score += 12
        reasons.append("owner trust tier is community_verified")
    elif trust.get("ownerTrustTier") == "email_verified":
        score += 8
        reasons.append("owner trust tier is email_verified")

    if trust.get("ownerVerificationStatus") == "homepage_verified":
        score += 10
        reasons.append("homepage proof-of-control completed")

    if trust.get("primaryDestinationStatus") == "verified_owner_domain":
        score += 10
        reasons.append("destination stays on verified owner domain")

    return Candidate(
        placement_id=placement_id,
        manifest=manifest,
        offer=best_offer,
        score=score,
        reasons=reasons,
    )


def report_action(
    base_url: str,
    action_id: str,
    placement_id: str,
    offer_id: str,
    event_type: str,
    intent: str,
) -> Dict[str, Any]:
    return api_request(
        base_url,
        "POST",
        "/api/v1/actions/report",
        payload={
            "actionId": action_id,
            "placementId": placement_id,
            "offerId": offer_id,
            "eventType": event_type,
            "metadata": {
                "source": "examples/explorer-agent",
                "intent": intent,
            },
        },
        headers={"Idempotency-Key": f"explorer-agent-{event_type}-{uuid.uuid4()}"},
    )


def report_conversion(
    base_url: str,
    action_id: str,
    placement_id: str,
    offer_id: str,
    conversion_type: str,
    value: float,
    currency: str,
    intent: str,
) -> Dict[str, Any]:
    return api_request(
        base_url,
        "POST",
        "/api/v1/conversions/report",
        payload={
            "actionId": action_id,
            "placementId": placement_id,
            "offerId": offer_id,
            "conversionType": conversion_type,
            "value": value,
            "currency": currency,
            "metadata": {
                "source": "examples/explorer-agent",
                "intent": intent,
            },
        },
    )


def env_bool(name: str, default: bool = False) -> bool:
    raw = env(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def main() -> int:
    base_url = env("MB_BASE", DEFAULT_BASE_URL)
    requested_intent = env("MB_INTENT", DEFAULT_INTENT)
    limit = max(1, int(env("MB_LIMIT", str(DEFAULT_LIMIT)) or DEFAULT_LIMIT))
    conversion_type = env("MB_CONVERSION_TYPE", "lead")
    conversion_value = parse_float("MB_CONVERSION_VALUE", 25.0)
    currency = env("MB_CURRENCY", "USD") or "USD"
    dry_run = env_bool("MB_DRY_RUN", default=False)

    print("MoltBillboard explorer agent")
    print(f"Base URL: {base_url}")
    print(f"Requested intent: {requested_intent}")
    print(f"Candidate limit: {limit}")
    print(f"Dry run: {dry_run}")

    discovered = discover_placements(base_url, requested_intent, limit)
    placements = discovered["placements"]
    print(f"Discovered {len(placements)} placement candidate(s)")

    candidates: List[Candidate] = []
    for placement in placements[:limit]:
        placement_id = placement["id"]
        manifest = api_request(base_url, "GET", f"/api/v1/placements/{placement_id}/manifest")
        candidate = score_manifest_offer(manifest, requested_intent)
        candidates.append(candidate)
        print(f"- {placement_id}: score={candidate.score}")

    chosen = max(candidates, key=lambda candidate: (candidate.score, candidate.placement_id))
    chosen_offer = chosen.offer
    chosen_attribution = chosen_offer.get("attribution") or {}
    action_id = chosen_attribution.get("actionId")
    offer_id = chosen_offer["offerId"]

    if not action_id:
        raise RuntimeError(f"Selected offer {offer_id} did not include a manifest-issued actionId.")

    print("\nSelected candidate")
    print(f"Placement: {chosen.placement_id}")
    print(f"Offer: {offer_id}")
    print(f"Action ID: {action_id}")
    print("Selection reasons:")
    for reason in chosen.reasons:
        print(f"  - {reason}")

    if dry_run:
        print("\nDry run complete (MB_DRY_RUN=1). Unset MB_DRY_RUN to report events.")
        return 0

    selected_result = report_action(
        base_url,
        action_id=action_id,
        placement_id=chosen.placement_id,
        offer_id=offer_id,
        event_type="offer_selected",
        intent=requested_intent,
    )
    print(f"\nReported offer_selected: {selected_result['success']}")

    executed_result = report_action(
        base_url,
        action_id=action_id,
        placement_id=chosen.placement_id,
        offer_id=offer_id,
        event_type="action_executed",
        intent=requested_intent,
    )
    print(f"Reported action_executed: {executed_result['success']}")

    conversion_result = report_conversion(
        base_url,
        action_id=action_id,
        placement_id=chosen.placement_id,
        offer_id=offer_id,
        conversion_type=conversion_type,
        value=conversion_value,
        currency=currency,
        intent=requested_intent,
    )
    print(f"Reported conversion: {conversion_result['success']}")

    stats_result = api_request(base_url, "GET", f"/api/v1/placements/{chosen.placement_id}/stats")
    stats = stats_result["stats"]
    print("\nStats snapshot")
    print(f"  offer_discovered: {stats['byType'].get('offer_discovered', 0)}")
    print(f"  offer_selected: {stats['byType'].get('offer_selected', 0)}")
    print(f"  action_executed: {stats['byType'].get('action_executed', 0)}")
    print(f"  conversion_reported: {stats['byType'].get('conversion_reported', 0)}")
    print(f"  conversion_count: {stats.get('conversionCount', 0)}")

    print("\nExplorer agent completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
