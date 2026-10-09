"""Company profile summarizer."""
from signalpost.synthesis.claude_client import ClaudeClient

SYSTEM = "You are a company analyst. Given facts about a Norwegian company, write a concise decision-useful summary. Only use supported facts. State unknowns clearly."

class Summarizer:
    def __init__(self, claude): self.claude = claude
    async def summarize(self, profile_data):
        li = profile_data.get("legal_identity",{})
        parts = []
        if li.get("legal_name"): parts.append("Name: "+str(li["legal_name"].get("value","")))
        if li.get("legal_form"): parts.append("Form: "+str(li["legal_form"].get("value","")))
        text = await self.claude.generate(SYSTEM, "Company data:\n"+chr(10).join(parts)+"\n\nSummarize.")
        unknowns = [s.replace("_"," ").title()+" not available"
                     for s in ["annual_accounts","website_profiles","hiring_activity"]
                     if profile_data.get(s,{}).get("status") in ("not_available","failed",None)]
        return {"company_summary": text or "Summary unavailable.", "key_observations":[], "unknowns":unknowns, "confidence_assessment":""}
