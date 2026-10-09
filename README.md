# Signalpost - AI Agent for Norwegian Company Intelligence

> **Hackathon Entry**: Builderr.ai Signalpost Competition
> **Author**: ManjunathGowda6 (manjunathd236@gmail.com)

## What It Does

Give Signalpost a Norwegian organisation number. It searches permitted public sources and returns a structured company profile with:

- **Legal identity** (name, form, address, industry codes, registration status)
- **Annual accounts** (revenue, profit, assets, equity, debt, employees + 5yr history)
- **Leadership & workplaces** (CEO, board members, auditors, branch locations)
- **Website & profiles** (official website content, social media links)
- **Evidence** (source URLs, content hashes, retrieval timestamps for every claim)
- **Refresh metadata** (change detection, versioning)
- **AI synthesis** (LLM-generated summary, key observations, confidence assessment)

Every fact is evidence-backed with source URLs and timestamps. No data is ever fabricated.

## Quick Start

### One Command To Run

```bash
# Install
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -e .

# Run on 1000+ companies
signalpost run -i data/company_universe.jsonl -o out/results.json

# Or quick smoke test (10 companies)
signalpost smoke-test
```

### Generate 1000+ Company Input

```bash
python scripts/generate_1000.py 1100 data/company_universe.jsonl
```

## Architecture

```
Input (JSONL)
    |
    v
+--[ Orchestrator ]--+
|                     |
|  1. Brreg Entity    |  <-- data.brreg.no/enhetsregisteret
|  2. Roles/Board     |  <-- /enheter/{orgnr}/roller
|  3. Subunits        |  <-- /underenheter?overordnetEnhet=
|  4. Financials      |  <-- data.brreg.no/regnskapsregisteret
|  5. Website Crawl   |  <-- trafilatura + extruct
|  6. LLM Synthesis   |  <-- Claude 3.5 Haiku (optional)
|                     |
+---------------------+
    |
    v
Output (JSON array of CompanyEnvelopes)
```

## Data Sources

| Source | Type | Auth | Rate Limit |
|--------|------|------|------------|
| Brreg Enhetsregisteret | REST API | None | Fair use |
| Brreg Roller | REST API | None | Fair use |
| Brreg Underenheter | REST API | None | Fair use |
| Regnskapsregisteret | REST API | None | Fair use |
| Company websites | HTTP crawl | None | robots.txt |

## Budget Limits

| Resource | Limit |
|----------|-------|
| Time | 45 minutes |
| Outbound requests | 2,000 |
| API cost | $10.00 USD |
| LLM model | Claude 3.5 Haiku |

## Model / API Details

- **LLM**: Anthropic Claude 3.5 Haiku (`claude-3-5-haiku-20241022`)
- **Purpose**: Company profile synthesis and summarization only
- **Cost**: ~$0.001-0.005 per company (input: $1/M tokens, output: $5/M tokens)
- **Optional**: Pipeline works fully without LLM (rule-based fallback synthesis)

## Expected Run Costs

| Companies | Requests | LLM Cost | Total Time |
|-----------|----------|----------|------------|
| 100 | ~400 | ~$0.10 | ~30s |
| 1,000 | ~4,000* | ~$1.00 | ~5min |
| 1,100 | ~4,400* | ~$1.10 | ~6min |

*With budget cap at 2,000 requests, some companies may skip website crawling.

## Output Schema

Each company profile contains 7 sections as specified:

1. `legal_identity` - Name, form, address, NACE codes, status
2. `annual_accounts` - Revenue, profit, assets with source/date
3. `leadership_workplaces` - Roles, board, branch offices
4. `website_profiles` - Website content, social links
5. `hiring_activity` - Public hiring signals
6. `evidence` - Source tracking, content hashes
7. `refresh_metadata` - Versioning, change detection

## Project Structure

```
signalpost/
  cli.py              # Click-based CLI
  config.py            # Settings & budget limits
  orchestrator.py      # Full pipeline orchestrator
  identity/
    brreg_client.py    # Async Brreg API client
    roles_client.py    # Leadership/board extraction
    subunits_client.py # Workplace extraction
  collectors/
    registry_collector.py   # Tier 1: Official registry
    website_collector.py    # Tier 2: Website crawling
  extractors/
    financial_extractor.py  # Regnskapsregisteret parser
  synthesis/
    claude_client.py   # Anthropic API wrapper
    summarizer.py      # Profile synthesis
  models/
    envelope.py        # Pydantic envelope schema
  utils/
    request_budget.py  # Request counter
    cost_tracker.py    # Cost tracker
scripts/
  generate_1000.py     # Generate company input list
  run_batch.py         # Batch runner
tests/
  fixtures/sample_companies.json
```

## License

MIT
