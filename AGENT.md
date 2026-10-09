# Signalpost Agent Policy

## Research Policy
- Every fact must have a source URL and retrieval timestamp
- Never fabricate financial values; use `not_available` for missing data
- Never assign facts to the wrong company; use `ambiguous` when uncertain
- Prefer returning less data over returning wrong data

## Abstention Policy
- Return `not_available` when data is genuinely not found
- Return `blocked` when a source exists but access is denied
- Return `ambiguous` when multiple candidate companies are found
- Return `failed` when a technical error prevents collection
- **NEVER** return zero in place of missing information

## Identity Verification
- Organisation number is the stable key (identity anchor)
- A website/brand is only verified when tied back to the exact legal entity
- Parent/subsidiary/franchise relationships must be labelled, not collapsed
