"""Company profile summarizer — produces the synthesis section."""
from __future__ import annotations

import json
from typing import Any

from signalpost.synthesis.claude_client import ClaudeClient


SYSTEM_PROMPT = """You are a concise Norwegian company analyst.
Given structured facts about a company, produce:
1. A 2-4 sentence summary (company_summary) covering what the company does, its legal form, size, and financial health.
2. 2-5 key observations (key_observations) — notable facts, risks, or strengths.
3. A list of unknowns — data we could not obtain.
4. A confidence assessment — how complete and reliable the profile is.

Rules:
- ONLY use facts provided. NEVER fabricate data.
- If financial data is missing, say so explicitly.
- Output valid JSON with keys: company_summary, key_observations, unknowns, confidence_assessment
"""


class Summarizer:
    """Generates the synthesis section of the company envelope."""

    def __init__(self, claude: ClaudeClient):
        self.claude = claude

    async def summarize(self, envelope_data: dict[str, Any]) -> dict[str, Any]:
        """Generate synthesis from collected envelope data."""
        facts = self._build_facts(envelope_data)

        # Try LLM synthesis
        text = await self.claude.generate(
            SYSTEM_PROMPT,
            f"Company facts:\n{facts}\n\nReturn JSON.",
            max_tokens=512,
        )

        if text:
            try:
                # Try to parse JSON from LLM response
                # Handle potential markdown code blocks
                cleaned = text.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.split("\n")
                    cleaned = "\n".join(lines[1:-1])
                parsed = json.loads(cleaned)
                return {
                    "company_summary": parsed.get("company_summary", ""),
                    "key_observations": parsed.get("key_observations", []),
                    "unknowns": parsed.get("unknowns", []),
                    "confidence_assessment": parsed.get("confidence_assessment", ""),
                }
            except (json.JSONDecodeError, KeyError):
                # Use raw text as summary
                return {
                    "company_summary": text[:500],
                    "key_observations": [],
                    "unknowns": self._detect_unknowns(envelope_data),
                    "confidence_assessment": "LLM response was non-JSON; partial synthesis.",
                }

        # Fallback: rule-based synthesis
        return self._rule_based_synthesis(envelope_data)

    def _build_facts(self, data: dict[str, Any]) -> str:
        """Build a structured facts string for the LLM."""
        parts = []
        li = data.get("legal_identity", {})
        if li.get("status") == "available":
            for field in ["legal_name", "legal_form", "registered_address",
                          "registration_date", "registration_status", "activity_description"]:
                claim = li.get(field)
                if claim and isinstance(claim, dict) and claim.get("value"):
                    parts.append(f"{field}: {claim['value']}")
            if li.get("industry_codes"):
                codes = li["industry_codes"]
                desc_list = [f'{c.get("code","?")} ({c.get("description","?")})' for c in codes[:3]]
                parts.append(f"industry_codes: {', '.join(desc_list)}")
            if li.get("is_bankrupt"):
                parts.append("WARNING: Company is bankrupt")
            if li.get("is_in_liquidation"):
                parts.append("WARNING: Company is in liquidation")

        aa = data.get("annual_accounts", {})
        if aa.get("status") == "available":
            for field in ["revenue", "operating_profit", "net_income",
                          "total_assets", "total_equity", "employees"]:
                claim = aa.get(field)
                if claim and isinstance(claim, dict) and claim.get("value") is not None:
                    val = claim["value"]
                    cur = claim.get("currency", "NOK")
                    period = claim.get("period", "")
                    parts.append(f"{field}: {val} {cur} ({period})")
        else:
            parts.append("annual_accounts: not_available")

        lw = data.get("leadership_workplaces", {})
        if lw.get("status") == "available":
            roles = lw.get("roles", [])
            if roles:
                role_strs = [f'{r.get("name","")} ({r.get("role","")})' for r in roles[:5]]
                parts.append(f"leadership: {'; '.join(role_strs)}")
            wps = lw.get("workplaces", [])
            if wps:
                parts.append(f"workplace_count: {len(wps)}")

        wp = data.get("website_profiles", {})
        if wp.get("status") == "available" and wp.get("official_website"):
            parts.append(f"website: {wp['official_website'].get('url', 'available')}")

        return "\n".join(parts) if parts else "No structured facts available."

    def _detect_unknowns(self, data: dict[str, Any]) -> list[str]:
        unknowns = []
        section_labels = {
            "annual_accounts": "Annual accounts",
            "website_profiles": "Website and online profiles",
            "hiring_activity": "Hiring and public activity",
            "leadership_workplaces": "Leadership and workplaces",
        }
        for key, label in section_labels.items():
            section = data.get(key, {})
            status = section.get("status", "not_available")
            if status in ("not_available", "failed"):
                unknowns.append(f"{label}: {status}")
        return unknowns

    def _rule_based_synthesis(self, data: dict[str, Any]) -> dict[str, Any]:
        """Fallback synthesis when no LLM is available."""
        li = data.get("legal_identity", {})
        name_claim = li.get("legal_name", {})
        name = name_claim.get("value", "Unknown") if isinstance(name_claim, dict) else "Unknown"
        form_claim = li.get("legal_form", {})
        form = form_claim.get("value", "") if isinstance(form_claim, dict) else ""

        summary_parts = [f"{name}"]
        if form:
            summary_parts.append(f"is a {form} registered in Norway")

        aa = data.get("annual_accounts", {})
        if aa.get("status") == "available":
            rev = aa.get("revenue", {})
            if isinstance(rev, dict) and rev.get("value") is not None:
                summary_parts.append(
                    f"with revenue of {rev['value']:,.0f} {rev.get('currency','NOK')} "
                    f"({rev.get('period','latest')})"
                )

        summary = " ".join(summary_parts) + "."
        unknowns = self._detect_unknowns(data)

        available_count = sum(
            1 for k in ["legal_identity", "annual_accounts", "leadership_workplaces",
                        "website_profiles", "hiring_activity"]
            if data.get(k, {}).get("status") == "available"
        )

        if available_count >= 4:
            confidence = "High — most sections have verified data."
        elif available_count >= 2:
            confidence = "Medium — some sections have data, others are unavailable."
        else:
            confidence = "Low — limited data available."

        return {
            "company_summary": summary,
            "key_observations": [],
            "unknowns": unknowns,
            "confidence_assessment": confidence,
        }
