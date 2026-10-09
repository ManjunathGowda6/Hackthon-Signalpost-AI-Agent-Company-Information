# Signalpost Data Schema

## Company Envelope
Every company produces exactly ONE envelope with 7 required sections:
1. Legal identity and public brand
2. Latest annual accounts and available history
3. Leadership and registered workplaces
4. Verified official website and company-owned profiles
5. Hiring and dated public activity
6. Claim-level evidence and availability state
7. Refresh metadata and material changes

## Availability States
- `available` - Data found and verified
- `not_available` - Searched but not found
- `blocked` - Source exists but access denied
- `not_applicable` - Field doesn't apply
- `ambiguous` - Multiple candidates, can't confirm
- `failed` - Technical failure
