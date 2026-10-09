"""Generate a list of 1000+ real Norwegian company org numbers.

Uses the Brreg bulk search API to find active companies.
Run this to create the input file for the batch run.
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx


async def fetch_companies(page: int = 0, size: int = 100) -> list[dict]:
    """Fetch a page of companies from Brreg search API."""
    url = (
        f"https://data.brreg.no/enhetsregisteret/api/enheter"
        f"?fraRegistreringsdatoEnhetsregisteret=2020-01-01"
        f"&registrertIMvaregisteret=true"
        f"&konkurs=false"
        f"&size={size}&page={page}"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            print(f"  Page {page}: HTTP {resp.status_code}")
            return []
        data = resp.json()
        embedded = data.get("_embedded", {})
        return embedded.get("enheter", [])


async def main():
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 1100
    output = sys.argv[2] if len(sys.argv) > 2 else "data/company_universe.jsonl"

    print(f"  Fetching {target} Norwegian company org numbers...")
    print(f"  Output: {output}\n")

    all_companies: list[str] = []
    page = 0
    page_size = 100

    while len(all_companies) < target:
        entities = await fetch_companies(page=page, size=page_size)
        if not entities:
            break
        for e in entities:
            nr = e.get("organisasjonsnummer")
            if nr:
                all_companies.append(nr)
        print(f"  Page {page}: +{len(entities)} companies (total: {len(all_companies)})")
        page += 1

        if page > 15:
            break

    # Deduplicate
    all_companies = list(dict.fromkeys(all_companies))[:target]

    # Write JSONL
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for nr in all_companies:
            f.write(json.dumps({"organisasjonsnummer": nr}) + "\n")

    print(f"\n  ✓ Wrote {len(all_companies)} org numbers to {output}")


if __name__ == "__main__":
    asyncio.run(main())
