"""Subunits/workplaces client."""
from signalpost.identity.brreg_client import BrregClient

class SubunitsClient:
    def __init__(self, brreg): self.brreg = brreg

    async def get_workplaces(self, org_number):
        units = await self.brreg.get_subunits(org_number)
        result = []
        for u in units:
            addr = u.get("beliggenhetsadresse",{})
            result.append({"name":u.get("navn"), "org_number":u.get("organisasjonsnummer"),
                "address":{"street":" ".join(addr.get("adresse",[])),"postal_code":addr.get("postnummer"),"city":addr.get("poststed")},
                "employees":u.get("antallAnsatte")})
        return result
