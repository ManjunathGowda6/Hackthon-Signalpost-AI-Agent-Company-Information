# Signalpost — AI Agent for Norwegian Company Intelligence

> Build an autonomous agent that researches Norwegian companies using public sources and returns verified company profiles with evidence-backed facts.

## Quick Start

```bash
# Clone and install
git clone https://github.com/ManjunathGowda6/Hackthon-Signalpost-AI-Agent-Company-Information.git
cd Hackthon-Signalpost-AI-Agent-Company-Information
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac
pip install -e .

# Set your API key
set ANTHROPIC_API_KEY=your_key_here    # Windows
# export ANTHROPIC_API_KEY=your_key    # Linux/Mac

# Run the agent on a batch of companies (ONE COMMAND)
signalpost run --input companies.jsonl --output out/results.json

# Run 100-company smoke test
signalpost smoke-test --output out/smoke_test_report.json
```

## One Command to Run

```bash
signalpost run --input <input_file.jsonl> --output <output_file.json>
```

## Model / API Details

| Component | Provider | Model | Purpose |
|:---|:---|:---|:---|
| Synthesis & Extraction | Anthropic | Claude 3.5 Haiku | Company summaries, gap-filling extraction |
| Company Registry | Brreg | Free API (no key) | Legal identity, roles, subunits, financials |

## Expected Run Costs

| Resource | Per Company | Per 1,000 Batch |
|:---|:---|:---|
| Claude API | ~$0.005 | ~$5.00 |
| Total external APIs | ~$0.008 | ~$8.00 |

**Well under the $10/batch budget.**

## Architecture

See the architecture document for the full system design.

### Data Sources (Source Ladder)

1. **Tier 1 — Official Records:** Brreg Enhetsregisteret, Regnskapsregisteret, Roles API
2. **Tier 2 — Company-Owned:** Verified official website, sitemap, structured data
3. **Tier 3 — Licensed APIs:** Search APIs for candidate discovery
4. **Tier 4 — Public Pages:** Permitted public pages with provenance

### Processing Pipeline

`Organisation Number` -> `Identity Resolution` -> `Data Collection` -> `Evidence Preservation` -> `Extraction & Validation` -> `LLM Synthesis` -> `Company Profile Envelope`

## Project Structure

```
signalpost/               # Main package
  identity/                # Layer 1: Identity Resolution (Brreg client)
  collectors/              # Layer 2: Data Collection (source ladder)
  evidence/                # Layer 3: Evidence Preservation (snapshots)
  extractors/              # Layer 4: Extraction (structured -> LLM)
  models/                  # Pydantic data models
  synthesis/               # Layer 5: Claude LLM synthesis
  refresh/                 # Layer 6: Refresh & diff
  utils/                   # HTTP client, budgets, logging
tests/                     # Test suite
scripts/                   # Utility scripts
```

## Submission Checklist

- [ ] At least 1,000 company profiles
- [x] Repository link: https://github.com/ManjunathGowda6/Hackthon-Signalpost-AI-Agent-Company-Information
- [ ] Exact commit hash: (will be filled at submission)
- [x] One command to run: `signalpost run --input companies.jsonl --output out/results.json`
- [x] Model/API details: Claude 3.5 Haiku + Brreg Free API
- [x] Expected run costs: ~$8/batch

## Git Auto-Sync

Watches for file changes and **instantly** commits & pushes to GitHub:

```bash
pip install watchdog
python git_auto_sync.py             # Instant watch mode (pushes on every change)
python git_auto_sync.py --once      # One-time commit & push
python git_auto_sync.py --status    # Check git status
```

## License

MIT

## Author

**ManjunathGowda6** — manjunathd236@gmail.com