"""Signalpost configuration and environment settings."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
PROFILES_DIR = DATA_DIR / "profiles"
CACHE_DIR = DATA_DIR / "cache"
OUTPUT_DIR = PROJECT_ROOT / "out"

# Ensure directories exist
for d in [SNAPSHOTS_DIR, PROFILES_DIR, CACHE_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# API Keys
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Brreg API (no auth needed)
BRREG_BASE_URL = "https://data.brreg.no"
BRREG_ENHETSREGISTERET_URL = f"{BRREG_BASE_URL}/enhetsregisteret/api"
BRREG_REGNSKAPSREGISTERET_URL = f"{BRREG_BASE_URL}/regnskapsregisteret/regnskap"

# Budget Limits
MAX_REQUESTS = 2000
MAX_COST_USD = 10.0
MAX_TIME_SECONDS = 45 * 60  # 45 minutes
MAX_CONCURRENT_WORKERS = 10

# Claude Model
CLAUDE_MODEL = "claude-3-5-haiku-20241022"
CLAUDE_MAX_TOKENS = 1024

# HTTP Settings
HTTP_TIMEOUT = 30  # seconds
HTTP_MAX_RETRIES = 3
HTTP_RETRY_BACKOFF = 1.0  # seconds

# Crawl Settings
USER_AGENT = "Signalpost/1.0 (Company Research Agent; +https://github.com/ManjunathGowda6/Hackthon-Signalpost-AI-Agent-Company-Information)"
RESPECT_ROBOTS_TXT = True
