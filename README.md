# Signalpost -- AI Agent for Norwegian Company Intelligence

> **Hackathon Entry**: Builderr.ai Signalpost Competition
> **Author**: ManjunathGowda6 (manjunathd236@gmail.com)
> **Commit**: `5f0dceb`

## What It Does

Give Signalpost a Norwegian organisation number. It searches permitted public sources and returns a structured company profile with:

- **Legal identity** -- name, form, address, industry codes (NACE), registration status
- **Annual accounts** -- revenue, profit, assets, equity, debt, employees + 5-year history
- **Leadership & workplaces** -- CEO, board members, auditors, branch locations
- **Website & profiles** -- official website, social media links
- **Evidence** -- source URLs, content hashes, retrieval timestamps for every claim
- **Refresh metadata** -- change detection, versioning
- **AI synthesis** -- LLM-generated or rule-based summary, observations, confidence

Every fact is evidence-backed with source URLs and timestamps. No data is ever fabricated.

## Results (Latest Run)

| Metric | Value |
|--------|-------|
| Total profiles | **1,000** |
| Available | **1,000 (100%)** |
| With financial data | 567 (56%) |
| With leadership roles | 342 (34%) |
| Total evidence-backed claims | 11,598 |
| Claims with source URL | 11,598 (100%) |
| Run time | 41.0 seconds |
| Requests used | 2,000 / 2,000 |
| API cost | $0.00 |

## Quick Start -- One Command To Run

```bash
# Setup
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate    # Linux/Mac
pip install -e .

# Run on 1,000 companies (the submission batch)
signalpost run -i data/company_1000.jsonl -o out/results.json

# Or quick smoke test (10 companies)
signalpost smoke-test
```

### Generate Your Own Company List

```bash
python scripts/generate_1000.py 1100 data/company_universe.jsonl
```

## Architecture

```
Input (JSONL with org numbers)
    |
    v
+-----[ Orchestrator (Phased Budget Allocation) ]-----+
|                                                       |
|  Phase 1: Entity fetch for ALL companies              |
|           -> Legal identity, NACE codes, address      |
|                                                       |
|  Phase 2a: Financials for AS/ASA companies            |
|            -> Revenue, profit, assets, 5yr history    |
|                                                       |
|  Phase 2b: Roles for remaining budget                 |
|            -> CEO, board, auditors                    |
|                                                       |
|  Phase 3: Assemble envelopes + synthesis              |
|                                                       |
+-------------------------------------------------------+
    |
    v
Output (JSON array of CompanyEnvelopes)
```

### Budget Strategy

With 2,000 requests and 1,000 companies:
- Phase 1 uses 1,000 requests (1 per entity)
- Phase 2a prioritizes accounting-obliged companies (AS/ASA) for financials
- Phase 2b uses remaining budget for leadership roles
- Result: every company gets legal identity + best possible enrichment

## Data Sources

| Source | URL | Auth | Content |
|--------|-----|------|---------|
| Enhetsregisteret | data.brreg.no/enhetsregisteret/api | None | Entity, address, NACE |
| Roller | .../enheter/{orgnr}/roller | None | Board, CEO, auditor |
| Regnskapsregisteret | data.brreg.no/regnskapsregisteret | None | Annual accounts |
| Company websites | Via entity hjemmeside field | None | Website URL |

## Model / API Details

- **LLM**: Anthropic Claude 3.5 Haiku (`claude-3-5-haiku-20241022`)
- **Purpose**: Company profile synthesis and summarization (optional)
- **Cost**: ~$0.001-0.005 per company (input: $1/M tokens, output: $5/M tokens)
- **Fallback**: Pipeline works fully without LLM using rule-based synthesis
- **To enable**: Set `ANTHROPIC_API_KEY` in `.env` file

## Budget Limits (Competition)

| Resource | Limit |
|----------|-------|
| Time | 45 minutes |
| Outbound requests | 2,000 |
| API cost | $10.00 USD |

## Expected Run Costs

| Companies | Requests | LLM Cost | Time |
|-----------|----------|----------|------|
| 10 | ~30 | $0.00 | 10s |
| 100 | ~200 | ~$0.10 | 20s |
| 1,000 | 2,000 | ~$1.00 | 41s |

Without Claude API key, LLM cost is $0.00 (uses rule-based synthesis).

## Output Schema

Each company envelope contains 7 required sections:

1. `legal_identity` -- Name, form, address, NACE codes, registration status
2. `annual_accounts` -- Revenue, profit, assets, equity, debt, employees, 5yr history
3. `leadership_workplaces` -- CEO, board members, auditors, branch offices
4. `website_profiles` -- Official website, social media links
5. `hiring_activity` -- Public hiring signals (not_applicable for registry-only)
6. `evidence` -- Source URLs, claim counts, content verification
7. `refresh_metadata` -- Version tracking, change detection timestamps

### Availability States

- `available` -- Data found and verified
- `not_available` -- Data not found in public sources
- `not_applicable` -- Section not relevant for this company type
- `failed` -- Technical error during data collection

## Project Structure

```
signalpost/
  cli.py                 # Click CLI: run, smoke-test, refresh
  config.py              # Settings, budget limits, API URLs
  orchestrator.py        # Phased pipeline with smart budget allocation
  identity/
    brreg_client.py      # Async Brreg API client with SHA-256 hashing
    roles_client.py      # Leadership/board extraction and normalization
    subunits_client.py   # Workplace/branch extraction
  collectors/
    base.py              # Abstract collector interface
    registry_collector.py # Tier 1: Official registry
    website_collector.py  # Tier 2: Website crawling (trafilatura)
  extractors/
    financial_extractor.py # Regnskapsregisteret parser with obligation assessment
  synthesis/
    claude_client.py     # Anthropic API with token-based cost tracking
    summarizer.py        # LLM + rule-based fallback synthesis
  models/
    envelope.py          # Pydantic schema for all 7 sections
  utils/
    request_budget.py    # Thread-safe request counter
    cost_tracker.py      # Thread-safe cost tracker
scripts/
  generate_1000.py       # Generate company input list from Brreg search
  run_batch.py           # Alternative batch runner
tests/
  fixtures/
    sample_companies.json # 10 sample org numbers for testing
data/
  company_1000.jsonl     # 1,000 company org numbers (production input)
  company_universe.jsonl # 1,100 company org numbers (full universe)
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check signalpost/

# Type check
mypy signalpost/
```

## License

MIT
