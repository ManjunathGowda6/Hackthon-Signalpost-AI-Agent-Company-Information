"""Roles client: fetches and normalizes leadership data from Brreg."""
from __future__ import annotations

from typing import Any, Optional
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class RolesClient:
    """Extracts board, CEO, auditor from Brreg roller endpoint."""

    def __init__(self, brreg_client):
        self.brreg = brreg_client

    async def get_leadership(self, org_number: str) -> list[dict[str, Any]]:
        resp = await self.brreg.get_roles(org_number)
        if not resp.ok:
            return []
        return self.normalize_roles(resp.data, org_number)

    @staticmethod
    def normalize_roles(body: Any, org_number: str) -> list[dict[str, Any]]:
        if not isinstance(body, dict):
            return []
        src = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}/roller"
        now = utc_now()
        normalized: list[dict[str, Any]] = []

        for rg in body.get("rollegrupper", []):
            group_desc = rg.get("type", {}).get("beskrivelse", "Ukjent")
            for r_item in rg.get("roller", []):
                r_type = r_item.get("type", {}).get("beskrivelse") or group_desc
                p = r_item.get("person")
                e = r_item.get("enhet")
                name = ""
                birth_year: Optional[int] = None

                if p:
                    n = p.get("navn", {})
                    if isinstance(n, dict):
                        parts = [n.get("fornavn"), n.get("mellomnavn"), n.get("etternavn")]
                        name = " ".join(x for x in parts if x)
                    elif isinstance(n, str):
                        name = n
                    dob = p.get("fodselsdato")
                    if dob and len(dob) >= 4 and dob[:4].isdigit():
                        birth_year = int(dob[:4])
                elif e:
                    name = e.get("navn", "")

                if name:
                    normalized.append({
                        "role": r_type,
                        "name": name,
                        "birth_year": birth_year,
                        "source": src,
                        "retrieved_at": now,
                    })
        return normalized
