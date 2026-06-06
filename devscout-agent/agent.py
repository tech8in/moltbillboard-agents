#!/usr/bin/env python3
"""
DevScout — demand-side reference agent (developer tools / SaaS).

Flow: GET /ad-units → GET manifest → POST actions/report → optional sandbox → conversion.

Defaults to dry run (MB_DRY_RUN=1). Set MB_DRY_RUN=0 to report attribution.
Set MB_ALLOW_LIVE=1 and MB_SANDBOX_HOST_ALLOWLIST for partner sandbox calls only.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from urllib.parse import urlencode, urljoin

import requests

DEFAULT_BASE = "https://www.moltbillboard.com"
TARGET_INTENTS = {"software.purchase", "subscription.register"}


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def divider(title: str) -> None:
    print(f"\n{'─' * 62}\n  {title}\n{'─' * 62}")


def discover_ad_units(base: str, topic: str, limit: int) -> list[dict]:
    params = urlencode({"topic": topic, "limit": limit, "surface": "api"})
    url = urljoin(base, f"/api/v1/ad-units?{params}")
    response = requests.get(url, timeout=15)
    response.raise_for_status()
    return response.json().get("adUnits") or []


def rank_unit(units: list[dict]) -> dict | None:
    def score(unit: dict) -> int:
        s = 0
        if unit.get("primaryIntent") in TARGET_INTENTS:
            s += 20
        if unit.get("actionEndpoint"):
            s += 5
        return s

    if not units:
        return None
    return max(units, key=score)


def pick_offer(manifest: dict) -> tuple[dict, dict]:
    placement = manifest.get("placement") or manifest.get("manifest", {}).get("placement", {})
    offers = placement.get("offers") or []
    if not offers:
        raise RuntimeError("Manifest has no offers")

    def offer_score(offer: dict) -> int:
        s = 0
        if offer.get("primaryIntent") in TARGET_INTENTS:
            s += 30
        if offer.get("isPrimary"):
            s += 8
        return s

    offer = max(offers, key=offer_score)
    action_id = (offer.get("attribution") or {}).get("actionId")
    if not action_id:
        raise RuntimeError("Offer missing actionId from manifest")
    return placement, offer


def main() -> None:
    base = env("MB_BASE", DEFAULT_BASE).rstrip("/")
    topic = env("MB_TOPIC", "developer tools")
    limit = int(env("MB_LIMIT", "5") or "5")
    dry_run = env("MB_DRY_RUN", "1") != "0"
    allow_live = env("MB_ALLOW_LIVE", "0") == "1"
    allowlist = {
        h.strip().lower()
        for h in (env("MB_SANDBOX_HOST_ALLOWLIST") or "").split(",")
        if h.strip()
    }

    divider("DevScout agent")
    print(f"  Base:     {base}")
    print(f"  Topic:    {topic}")
    print(f"  Dry run:  {dry_run}")

    units = discover_ad_units(base, topic, limit)
    if not units:
        sys.exit("No ad units for topic")

    unit = rank_unit(units)
    placement_id = unit["placementId"]
    print(f"  Ad unit:  {unit.get('title') or placement_id}")

    manifest_resp = requests.get(
        urljoin(base, f"/api/v1/placements/{placement_id}/manifest"),
        timeout=15,
    )
    manifest_resp.raise_for_status()
    envelope = manifest_resp.json()
    manifest = envelope.get("manifest") or envelope
    placement, offer = pick_offer(manifest)
    placement_id = placement.get("id") or placement_id
    offer_id = offer["offerId"]
    action_id = offer["attribution"]["actionId"]
    action_endpoint = offer.get("actionEndpoint") or unit.get("actionEndpoint")

    print(f"  Offer:    {offer_id}")
    print(f"  Action:   {action_id}")

    if dry_run:
        print("\n  Dry run complete (MB_DRY_RUN=1). Set MB_DRY_RUN=0 to report events.")
        return

    idem = f"devscout-{uuid.uuid4()}"
    report = requests.post(
        urljoin(base, "/api/v1/actions/report"),
        headers={"Content-Type": "application/json", "Idempotency-Key": idem},
        json={
            "actionId": action_id,
            "placementId": placement_id,
            "offerId": offer_id,
            "eventType": "offer_selected",
        },
        timeout=15,
    )
    report.raise_for_status()
    print(f"  offer_selected: {report.json().get('success')}")

    executed = False
    if allow_live and action_endpoint and allowlist:
        from urllib.parse import urlparse

        host = urlparse(action_endpoint).hostname or ""
        if host.lower() in allowlist:
            merchant = requests.post(
                action_endpoint,
                json={"requester": "devscout-agent", "sandbox_mode": True},
                timeout=20,
            )
            executed = merchant.status_code in (200, 201)
            print(f"  sandbox:  HTTP {merchant.status_code}")

    if executed or env("MB_REPORT_CONVERSION_WITHOUT_LIVE", "0") == "1":
        conv = requests.post(
            urljoin(base, "/api/v1/conversions/report"),
            json={
                "actionId": action_id,
                "placementId": placement_id,
                "offerId": offer_id,
                "conversionType": env("MB_CONVERSION_TYPE", "signup"),
            },
            timeout=15,
        )
        conv.raise_for_status()
        print(f"  conversion: {conv.json().get('success')}")

    print("\n  DevScout completed.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
