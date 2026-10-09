"""Anthropic Claude client."""
import structlog
from signalpost.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS
from signalpost.utils.cost_tracker import CostTracker
logger = structlog.get_logger()

class ClaudeClient:
    def __init__(self, cost_tracker=None):
        self.cost_tracker = cost_tracker or CostTracker(); self._client = None
    def _get_client(self):
        if self._client is None:
            import anthropic; self._client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        return self._client
    async def generate(self, system_prompt, user_prompt, max_tokens=CLAUDE_MAX_TOKENS):
        if not ANTHROPIC_API_KEY: return None
        cost = 0.005
        if not self.cost_tracker.can_afford(cost): return None
        try:
            client = self._get_client()
            resp = client.messages.create(model=CLAUDE_MODEL, max_tokens=max_tokens,
                                          system=system_prompt, messages=[{"role":"user","content":user_prompt}])
            self.cost_tracker.add_cost(cost, "claude_api")
            return resp.content[0].text
        except Exception as e: logger.error("claude_error", error=str(e)); return None
