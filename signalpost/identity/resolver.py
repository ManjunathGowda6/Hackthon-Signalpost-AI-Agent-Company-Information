"""Public identity resolver."""
class IdentityResolver:
    async def resolve(self, entity_data):
        website = entity_data.get("hjemmeside","")
        name = entity_data.get("navn","")
        return {"official_website": (website if website.startswith("http") else f"https://{website}") if website else None,
                "public_brand": name.replace(" AS","").replace(" ASA","").strip() if name else None,
                "confidence": 0.7 if website else 0.0, "verification_method": "brreg_registered" if website else None}
