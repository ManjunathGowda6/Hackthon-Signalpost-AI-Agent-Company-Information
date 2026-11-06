"""Google Gemini client with cost tracking — drop-in alongside ClaudeClient."""
import json
import structlog
from signalpost.config import GEMINI_API_KEY, GEMINI_MODEL
from signalpost.utils.cost_tracker import CostTracker

logger = structlog.get_logger()

# Gemini 2.5 Flash pricing (USD per 1M tokens) — conservative estimates
INPUT_COST_PER_1M = 0.15
OUTPUT_COST_PER_1M = 0.60


class GeminiClient:
    """Wrapper around the Google Gemini REST API with cost tracking."""

    def __init__(self, cost_tracker=None):
        self.cost_tracker = cost_tracker or CostTracker()
        self._api_key = GEMINI_API_KEY

    async def generate(self, system_prompt: str, user_prompt: str,
                       max_tokens: int = 1024) -> str | None:
        """Call Gemini via REST (no SDK dependency required)."""
        if not self._api_key:
            logger.debug("gemini_skipped_no_key")
            return None

        # Cost guard
        est_input_tokens = (len(system_prompt) + len(user_prompt)) / 4
        est_cost = ((est_input_tokens / 1_000_000) * INPUT_COST_PER_1M +
                    (max_tokens / 1_000_000) * OUTPUT_COST_PER_1M)
        if not self.cost_tracker.can_afford(est_cost):
            logger.warning("gemini_cost_budget_exhausted")
            return None

        try:
            import httpx

            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{GEMINI_MODEL}:generateContent?key={self._api_key}"
            )
            payload = {
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": 0.2,
                },
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, json=payload)

            if resp.status_code != 200:
                logger.error("gemini_http_error", status=resp.status_code,
                             body=resp.text[:300])
                return None

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                logger.warning("gemini_no_candidates")
                return None

            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")

            # Track cost from usage metadata
            usage = data.get("usageMetadata", {})
            in_tok = usage.get("promptTokenCount", int(est_input_tokens))
            out_tok = usage.get("candidatesTokenCount", len(text) // 4)
            actual_cost = ((in_tok / 1_000_000) * INPUT_COST_PER_1M +
                           (out_tok / 1_000_000) * OUTPUT_COST_PER_1M)
            self.cost_tracker.add_cost(actual_cost, "gemini_api")
            logger.debug("gemini_call", model=GEMINI_MODEL,
                         input_tokens=in_tok, output_tokens=out_tok,
                         cost_usd=round(actual_cost, 6))
            return text

        except Exception as e:
            logger.error("gemini_error", error=str(e))
            return None
