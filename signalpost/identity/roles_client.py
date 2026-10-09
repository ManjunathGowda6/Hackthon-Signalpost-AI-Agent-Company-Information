"""Roles client for management/board data."""
from signalpost.identity.brreg_client import BrregClient
from signalpost.models.leadership import PersonRole

class RolesClient:
    def __init__(self, brreg): self.brreg = brreg

    async def get_leadership(self, org_number):
        data = await self.brreg.get_roles(org_number)
        if not data: return []
        src = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}/roller"
        persons = []
        for rg in data.get("rollegrupper",[]):
            rtype = rg.get("type",{}).get("beskrivelse","Unknown")
            for role in rg.get("roller",[]):
                p = role.get("person",{}) or role.get("enhet",{})
                parts = [p.get("fornavn",""), p.get("mellomnavn",""), p.get("etternavn","")]
                name = " ".join(x for x in parts if x)
                if name: persons.append(PersonRole(role_type=rtype, person_name=name, source=src))
        return persons
