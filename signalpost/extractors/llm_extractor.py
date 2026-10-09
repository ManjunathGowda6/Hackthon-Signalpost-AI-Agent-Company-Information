"""LLM-based extraction (Claude) - last resort only."""
class LlmExtractor:
    """RULES: Only after deterministic extraction. Never decides identity. Never invents fields."""
    async def extract(self, text, context): return {}
