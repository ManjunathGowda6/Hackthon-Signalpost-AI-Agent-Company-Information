"""Change/unknown explainer."""
class Explainer:
    def __init__(self, claude): self.claude = claude
    async def explain_changes(self, changes):
        if not changes: return "No material changes."
        return f"{len(changes)} changes detected."
    async def explain_unknowns(self, unknowns):
        if not unknowns: return "All information found."
        return "Missing: " + ", ".join(unknowns)
