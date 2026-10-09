"""Anthropic Claude client with token-based cost tracking."""
import structlog
from signalpost.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS
from signalpost.utils.cost_tracker import CostTracker

logger = structlog.get_logger()

# Claude 3.5 Haiku pricing (USD per 1M tokens)
INPUT_COST_PER_1M = 1.00
OUTPUT_COST_PER_1M = 5.00


class ClaudeClient:
    """Wrapper around Anthropic's Messages API with cost tracking."""

    def __init__(self, cost_tracker=None):
        self.cost_tracker = cost_tracker or CostTracker()
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not ANTHROPIC_API_KEY:
                return None
            import anthropic
            self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        return self._client

    async def generate(self, system_prompt: str, user_prompt: str,
                       max_tokens: int = CLAUDE_MAX_TOKENS) -> str | None:
        if not ANTHROPIC_API_KEY:
            logger.debug("claude_skipped_no_key")
            return None

        # Estimate cost before calling (rough: 1 token ≈ 4 chars)
        est_input_tokens = (len(system_prompt) + len(user_prompt)) / 4
        est_cost = (est_input_tokens / 1_000_000) * INPUT_COST_PER_1M + \
                   (max_tokens / 1_000_000) * OUTPUT_COST_PER_1M

        if not self.cost_tracker.can_afford(est_cost):
            logger.warning("claude_cost_budget_exhausted")
            return None

        try:
            client = self._get_client()
            if client is None:
                return None

            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # Track actual cost
            usage = resp.usage
            actual_cost = (
                (usage.input_tokens / 1_000_000) * INPUT_COST_PER_1M +
                (usage.output_tokens / 1_000_000) * OUTPUT_COST_PER_1M
            )
            self.cost_tracker.add_cost(actual_cost, "claude_api")
            logger.debug("claude_call",
                         input_tokens=usage.input_tokens,
                         output_tokens=usage.output_tokens,
                         cost_usd=round(actual_cost, 6))

            return resp.content[0].text

        except Exception as e:
            logger.error("claude_error", error=str(e))
            return None
