"""Subunits and registered workplaces client."""
from __future__ import annotations

from typing import Any
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SubunitsClient:
    @staticmethod
    def normalize_subunits(body: Any, org_number: str) -> list[dict[str, Any]]:
        units = []
        if isinstance(body, dict):
            units = body.get("_embedded", {}).get("underenheter", [])
        elif isinstance(body, list):
            units = body

        src = f"https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet={org_number}"
        now = utc_now()
        workplaces: list[dict[str, Any]] = []

        for u in units:
            addr = u.get("beliggenhetsadresse") or u.get("postadresse") or {}
            workplaces.append({
                "name": u.get("navn"),
                "org_number": u.get("organisasjonsnummer"),
                "address": {
                    "street": " ".join(addr.get("adresse", [])),
                    "postal_code": addr.get("postnummer"),
                    "city": addr.get("poststed"),
                    "country": addr.get("land", "Norge"),
                },
                "employees": u.get("antallAnsatte"),
                "source": src,
                "retrieved_at": now,
            })
        return workplaces
