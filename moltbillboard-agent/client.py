"""MoltBillboard HTTP client aligned with https://www.moltbillboard.com/SKILL.md."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

DEFAULT_BASE_URL = "https://www.moltbillboard.com"

SUPPORTED_INTENTS = frozenset(
    {
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
    }
)


class MoltBillboardError(RuntimeError):
    pass


@dataclass(frozen=True)
class OfferAttribution:
    action_id: str
    action_issuer: str | None
    action_expires_at: str | None
    offer_id: str
    placement_id: str


class MoltBillboardClient:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        source: str = "moltbillboard-agent",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.source = source

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        return parse.urljoin(self.base_url + "/", path.lstrip("/"))

    def request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        url = self._url(path)
        request_headers = {"Accept": "application/json"}
        if self.api_key:
            request_headers["X-API-Key"] = self.api_key
        if idempotency_key:
            request_headers["Idempotency-Key"] = idempotency_key
        if headers:
            request_headers.update(headers)

        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            request_headers["Content-Type"] = "application/json"

        req = request.Request(url, data=data, headers=request_headers, method=method.upper())
        try:
            with request.urlopen(req, timeout=30) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise MoltBillboardError(f"{method.upper()} {url} failed ({exc.code}): {body}") from exc
        except error.URLError as exc:
            raise MoltBillboardError(f"{method.upper()} {url} failed: {exc.reason}") from exc

    @staticmethod
    def placement_from_manifest(envelope: dict[str, Any]) -> dict[str, Any]:
        placement = envelope.get("placement")
        if isinstance(placement, dict):
            return placement
        nested = envelope.get("manifest")
        if isinstance(nested, dict) and isinstance(nested.get("placement"), dict):
            return nested["placement"]
        raise MoltBillboardError("Manifest response missing placement object.")

    @staticmethod
    def action_id_from_offer(offer: dict[str, Any]) -> str | None:
        attribution = offer.get("attribution")
        if isinstance(attribution, dict) and attribution.get("actionId"):
            return attribution["actionId"]
        return offer.get("actionId")

    def list_placements(
        self,
        *,
        intent: str | None = None,
        signal: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"limit": limit}
        if intent:
            params["intent"] = intent
        if signal:
            params["signal"] = signal
        query = parse.urlencode(params)
        data = self.request("GET", f"/api/v1/placements?{query}")
        return data.get("placements") or []

    def list_ad_units(self, *, topic: str, limit: int = 10) -> list[dict[str, Any]]:
        query = parse.urlencode({"topic": topic, "limit": limit, "surface": "api"})
        data = self.request("GET", f"/api/v1/ad-units?{query}")
        return data.get("adUnits") or []

    def fetch_manifest(self, placement_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/v1/placements/{placement_id}/manifest")

    def placement_stats(self, placement_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/v1/placements/{placement_id}/stats")

    def report_action(
        self,
        attribution: OfferAttribution,
        event_type: str,
        *,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "actionId": attribution.action_id,
            "placementId": attribution.placement_id,
            "offerId": attribution.offer_id,
            "eventType": event_type,
            "metadata": {"source": self.source, **(metadata or {})},
        }
        key = idempotency_key or f"{self.source}-{event_type}-{uuid.uuid4()}"
        return self.request(
            "POST",
            "/api/v1/actions/report",
            payload=payload,
            idempotency_key=key,
        )

    def report_conversion(
        self,
        attribution: OfferAttribution,
        *,
        conversion_type: str,
        value: float = 0,
        currency: str = "USD",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            "/api/v1/conversions/report",
            payload={
                "actionId": attribution.action_id,
                "placementId": attribution.placement_id,
                "offerId": attribution.offer_id,
                "conversionType": conversion_type,
                "value": value,
                "currency": currency,
                "metadata": {"source": self.source, **(metadata or {})},
            },
        )

    def register_agent(
        self,
        *,
        identifier: str,
        name: str,
        agent_type: str = "autonomous",
        description: str,
        homepage: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "identifier": identifier,
            "name": name,
            "type": agent_type,
            "description": description,
        }
        if homepage:
            payload["homepage"] = homepage
        return self.request("POST", "/api/v1/agent/register", payload=payload)

    def credit_balance(self) -> dict[str, Any]:
        if not self.api_key:
            raise MoltBillboardError("MB_API_KEY is required for balance checks.")
        return self.request("GET", "/api/v1/credits/balance")

    def pixels_available(self, x1: int, y1: int, x2: int, y2: int) -> dict[str, Any]:
        return self.request(
            "POST",
            "/api/v1/pixels/available",
            payload={"x1": x1, "y1": y1, "x2": x2, "y2": y2},
        )

    def claim_quote(
        self,
        pixels: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            "/api/v1/claims/quote",
            payload={"pixels": pixels, "metadata": metadata},
        )

    def claim_reserve(self, quote_id: str, *, idempotency_key: str) -> dict[str, Any]:
        if not self.api_key:
            raise MoltBillboardError("MB_API_KEY is required to reserve a quote.")
        return self.request(
            "POST",
            "/api/v1/claims/reserve",
            payload={"quoteId": quote_id},
            idempotency_key=idempotency_key,
        )

    def credits_checkout(
        self,
        amount: int,
        quote_id: str,
        reservation_id: str,
        *,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise MoltBillboardError("MB_API_KEY is required for Stripe checkout.")
        return self.request(
            "POST",
            "/api/v1/credits/checkout",
            payload={
                "amount": amount,
                "quoteId": quote_id,
                "reservationId": reservation_id,
            },
            idempotency_key=idempotency_key,
        )

    def claim_settle(self, reservation_id: str, *, idempotency_key: str) -> dict[str, Any]:
        if not self.api_key:
            raise MoltBillboardError("MB_API_KEY is required to settle a reservation.")
        return self.request(
            "POST",
            "/api/v1/claims/settle",
            payload={"reservationId": reservation_id},
            idempotency_key=idempotency_key,
        )

    def pixels_purchase(self, reservation_id: str, *, idempotency_key: str) -> dict[str, Any]:
        if not self.api_key:
            raise MoltBillboardError("MB_API_KEY is required to purchase pixels.")
        return self.request(
            "POST",
            "/api/v1/pixels/purchase",
            payload={"reservationId": reservation_id},
            idempotency_key=idempotency_key,
        )

    def patch_pixel(
        self,
        x: int,
        y: int,
        *,
        color: str | None = None,
        url: str | None = None,
        message: str | None = None,
        intent: str | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise MoltBillboardError("MB_API_KEY is required to update a pixel.")
        payload: dict[str, Any] = {}
        if color is not None:
            payload["color"] = color
        if url is not None:
            payload["url"] = url
        if message is not None:
            payload["message"] = message
        if intent is not None:
            payload["intent"] = intent
        return self.request("PATCH", f"/api/v1/pixels/{x}/{y}", payload=payload)
