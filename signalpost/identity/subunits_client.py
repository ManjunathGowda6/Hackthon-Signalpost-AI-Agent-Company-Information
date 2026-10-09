"""Subunits client: fetches and normalizes workplace data from Brreg."""
from __future__ import annotations

from typing import Any
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SubunitsClient:
    """Fetches workplace / branch sub-units from Brreg."""

    def __init__(self, brreg_client):
        self.brreg = brreg_client

    async def get_workplaces(self, org_number: str) -> list[dict[str, Any]]:
        resp = await self.brreg.get_subunits(org_number)
        if not resp.ok:
            return []
        return self.normalize_subunits(resp.data, org_number)

    @staticmethod
    def normalize_subunits(body: Any, org_number: str) -> list[dict[str, Any]]:
        if not isinstance(body, dict):
            return []

        src = (
            f"https://data.brreg.no/enhetsregisteret/api"
            f"/underenheter?overordnetEnhet={org_number}"
        )
        now = utc_now()
        workplaces: list[dict[str, Any]] = []

        embedded = body.get("_embedded", {})
        units = embedded.get("underenheter", [])

        for u in units:
            addr = u.get("beliggenhetsadresse", {})
            adresse_list = addr.get("adresse", [])
            workplaces.append({
                "sub_org_number": u.get("organisasjonsnummer"),
                "name": u.get("navn"),
                "address": {
                    "street": ", ".join(adresse_list) if adresse_list else None,
                    "postal_code": addr.get("postnummer"),
                    "city": addr.get("poststed"),
                    "country": addr.get("land", "Norge"),
                },
                "employees": u.get("antallAnsatte"),
                "source": src,
                "retrieved_at": now,
            })
        return workplaces
