# Signalpost Crawlers

## Connectors
| Connector | Tier | Auth | Rate Limit |
|:---|:---:|:---|:---|
| Brreg Entity API | 1 | None | Respectful |
| Brreg Roles API | 1 | None | Respectful |
| Brreg Subunits API | 1 | None | Respectful |
| Regnskapsregisteret | 1 | None | Respectful |
| Company Website | 2 | None | robots.txt |

## Budget Rules
- Max 2,000 outbound requests per batch
- Max  API cost per batch
- Max 45 minutes per batch

## Fallback Rules
1. If Brreg API fails -> retry with backoff (3 attempts)
2. If website unreachable -> mark as `blocked`
3. If budget exhausted -> stop collecting, return what we have
