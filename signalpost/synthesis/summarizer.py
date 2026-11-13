"""Company profile summarizer — produces the synthesis section.

LLM priority: Gemini API → Claude API → rule-based deterministic fallback.
All LLM prompts enforce strict grounding — only verified facts from the envelope.
Buyer-first summary: Sentence 1 always opens with a high-value commercial fact and citation.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from signalpost.synthesis.claude_client import ClaudeClient
from signalpost.synthesis.gemini_client import GeminiClient


SYSTEM_PROMPT = """You are a concise Norwegian B2B company intelligence analyst.
Given structured facts about a company, produce:
1. A 2-4 sentence executive summary.
   CRITICAL REQUIREMENT FOR SENTENCE 1:
   - NEVER start Sentence 1 with registry boilerplate (do NOT start with orgnr, incorporation date, legal form "AS", or registered address).
   - Sentence 1 MUST start with a high-value commercial fact a B2B buyer/partner wants, explicitly citing the source:
     * Priority 1 (Financial Scale & Trajectory): If revenue is known, start with latest revenue, operating profit/margin, YoY growth, and primary commercial activity: "In [Year], [Company] generated NOK [X] in revenue [growth YoY] with an operating result of NOK [Y] ([margin]% margin), operating in [activity] (Source: [Regnskapsregisteret URL], [Date])."
     * Priority 2 (Website Offering & Workforce): If financials missing but website/employees known: "[Company] operates in [activity/offering] with [N] registered employees (Source: [Source URL], [Date])."
     * Priority 3 (Workforce & Leadership): Lead with employee scale, key leadership (CEO/Daglig leder), and commercial activity with exact source citation.
   - Sentences 2-4: Follow with financial health (equity ratio, profitability), active hiring, recent dated news, and verified website/social channels.
2. 2-5 key observations — notable commercial facts, strengths, or financial risks.
3. A list of unknowns — data we could not obtain.
4. A confidence assessment — how complete and reliable the profile is.

STRICT RULES:
- ONLY cite numbers, dates, and facts present in the provided data.
- NEVER fabricate, estimate, or infer data not given.
- For every financial figure, include an inline citation: (Source: URL, YYYY-MM-DD).
- Output valid JSON with keys: company_summary, key_observations, unknowns, confidence_assessment
"""


def _fmt(v: Any) -> str:
    if v is None:
        return "N/A"
    try:
        v = float(v)
        if abs(v) >= 1e9:
            return f"NOK {v/1e9:,.1f}B"
        if abs(v) >= 1e6:
            return f"NOK {v/1e6:,.1f}M"
        if abs(v) >= 1e3:
            return f"NOK {v/1e3:,.0f}K"
        return f"NOK {v:,.0f}"
    except Exception:
        return str(v)


class Summarizer:
    """Generates the synthesis section of the company envelope.

    Tries Gemini first, then Claude, then deterministic rule-based fallback.
    """

    def __init__(self, claude: ClaudeClient, gemini: GeminiClient | None = None):
        self.claude = claude
        self.gemini = gemini

    async def summarize(self, envelope_data: dict[str, Any]) -> dict[str, Any]:
        """Generate synthesis from collected envelope data."""
        facts = self._build_facts(envelope_data)
        user_prompt = f"Company facts:\n{facts}\n\nReturn JSON."

        # Priority 1: Gemini
        text = None
        method = "rule_based"
        model = None

        if self.gemini:
            text = await self.gemini.generate(SYSTEM_PROMPT, user_prompt, max_tokens=512)
            if text:
                method = "llm"
                model = "gemini"

        # Priority 2: Claude
        if not text:
            text = await self.claude.generate(SYSTEM_PROMPT, user_prompt, max_tokens=512)
            if text:
                method = "llm"
                model = "claude"

        if text:
            try:
                cleaned = text.strip()
                if cleaned.startswith("```"):
                    lines = cleaned.split("\n")
                    cleaned = "\n".join(lines[1:-1])
                parsed = json.loads(cleaned)
                return {
                    "status": "available",
                    "method": method,
                    "model": model,
                    "summary": parsed.get("company_summary", parsed.get("summary", "")),
                    "key_observations": parsed.get("key_observations", []),
                    "unknowns": parsed.get("unknowns", []),
                    "confidence_assessment": parsed.get("confidence_assessment", ""),
                }
            except (json.JSONDecodeError, KeyError):
                return {
                    "status": "available",
                    "method": method,
                    "model": model,
                    "summary": text[:500],
                    "key_observations": [],
                    "unknowns": self._detect_unknowns(envelope_data),
                    "confidence_assessment": "LLM response was non-JSON; partial synthesis.",
                }

        # Priority 3: Rule-based
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
                    src = claim.get("source", "")
                    date = (claim.get("retrieved_at") or "")[:10]
                    parts.append(f"{field}: {claim['value']} [Source: {src}, {date}]")
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
                    src = claim.get("source", "")
                    date = (claim.get("retrieved_at") or "")[:10]
                    parts.append(f"{field}: {val} {cur} ({period}) [Source: {src}, {date}]")
            yoy = aa.get("yoy_summary")
            if yoy:
                yoy_txt = yoy.get("text") if isinstance(yoy, dict) else str(yoy)
                parts.append(f"yoy_summary: {yoy_txt}")
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
            socials = wp.get("social_profiles", [])
            if socials:
                parts.append(f"social_profiles: {len(socials)} verified links")
            news = wp.get("news_items", [])
            if news:
                parts.append(f"recent_news: {len(news)} articles found")

        ha = data.get("hiring_activity", {})
        if ha.get("status") == "available":
            jobs = ha.get("job_listings", []) or ha.get("active_listings", [])
            if jobs:
                parts.append(f"open_jobs: {len(jobs)} active listings")

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
        """Buyer-first deterministic synthesis. Never starts with registry boilerplate."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        li = data.get("legal_identity", {})
        name_claim = li.get("legal_name", {})
        name = name_claim.get("value", data.get("name", "Company")) if isinstance(name_claim, dict) else data.get("name", "Company")
        org = data.get("organisation_number", "")
        brreg = f"https://data.brreg.no/enhetsregisteret/api/enheter/{org}"
        regn = f"https://data.brreg.no/regnskapsregisteret/regnskap/{org}"

        form_claim = li.get("legal_form", {})
        form = form_claim.get("value", "") if isinstance(form_claim, dict) else ""
        muni = data.get("municipality", "")

        # NACE activity description
        nace_desc = ""
        ind_codes = li.get("industry_codes", [])
        if ind_codes and isinstance(ind_codes, list):
            for ic in ind_codes:
                if isinstance(ic, dict) and ic.get("description"):
                    nace_desc = ic["description"]
                    break
        act_claim = li.get("activity_description", {})
        if isinstance(act_claim, dict) and act_claim.get("value"):
            nace_desc = act_claim["value"]

        # Financials
        aa = data.get("annual_accounts", {})
        rev_val = None
        op_val = None
        ta_val = None
        te_val = None
        year = aa.get("latest_filing_year")
        if aa.get("status") == "available":
            rev = aa.get("revenue", {})
            if isinstance(rev, dict) and rev.get("value") is not None:
                rev_val = rev["value"]
            op = aa.get("operating_profit", {})
            if isinstance(op, dict) and op.get("value") is not None:
                op_val = op["value"]
            ta = aa.get("total_assets", {})
            if isinstance(ta, dict) and ta.get("value") is not None:
                ta_val = ta["value"]
            te = aa.get("total_equity", {})
            if isinstance(te, dict) and te.get("value") is not None:
                te_val = te["value"]

        # Employees
        emp = None
        emp_claim = aa.get("employees", {})
        if isinstance(emp_claim, dict) and emp_claim.get("value") is not None:
            try:
                emp = int(emp_claim["value"])
            except Exception:
                pass

        # Website
        wp = data.get("website_profiles", {})
        website = None
        if wp.get("status") == "available" and wp.get("official_website"):
            website = wp["official_website"].get("url")
        if not website:
            website = data.get("website")

        # Leadership
        lw = data.get("leadership_workplaces", {})
        roles = lw.get("roles", []) if isinstance(lw, dict) else []
        ceo_name = ""
        for r in roles:
            if isinstance(r, dict):
                role_type = (r.get("role", "") or "").lower()
                if role_type in ("daglig leder", "administrerende direktør", "daglig leder/administrerende direktør"):
                    ceo_name = r.get("name", "")
                    break

        yoy = aa.get("yoy_summary")
        yoy_text = yoy.get("text") if isinstance(yoy, dict) else str(yoy or "")

        socials = wp.get("social_profiles", []) if isinstance(wp, dict) else []
        news = wp.get("news_items", []) if isinstance(wp, dict) else []
        ha = data.get("hiring_activity", {})
        jobs = (ha.get("job_listings", []) or ha.get("active_listings", [])) if isinstance(ha, dict) else []

        parts = []
        observations = []

        # --- SENTENCE 1: BUYER-RELEVANT OPENING ---
        if aa.get("status") == "available" and rev_val is not None:
            yr_str = f"In {year}, " if year else ""
            rev_str = _fmt(rev_val)
            op_part = ""
            if op_val is not None:
                op_str = _fmt(op_val)
                margin = ""
                try:
                    if float(rev_val) > 0:
                        m = (float(op_val) / float(rev_val)) * 100
                        margin = f" ({m:.0f}% margin)"
                except Exception:
                    pass
                op_part = f" with an operating result of {op_str}{margin}"
            yoy_part = ""
            if yoy_text:
                rev_m = re.search(r'revenue[:\s]*([\+\-]\d+%)', yoy_text, re.IGNORECASE)
                if rev_m:
                    yoy_part = f" ({rev_m.group(1)} YoY)"
            activity_part = ""
            if nace_desc:
                activity_part = f", operating in {nace_desc.lower()}"
            elif form:
                activity_part = f", registered as {form}"
            parts.append(
                f"{yr_str}{name} generated {rev_str} in revenue{yoy_part}{op_part}{activity_part} "
                f"(Source: {regn}, {today})."
            )
        elif website and emp and emp > 0:
            offering = nace_desc if nace_desc else "commercial services"
            parts.append(
                f"{name} operates in {offering.lower()} with {emp} employees "
                f"(Source: {brreg}, {today})."
            )
        elif emp and emp > 0:
            act = nace_desc if nace_desc else "commercial activities"
            ceo_p = f", led by {ceo_name}" if ceo_name else ""
            parts.append(
                f"{name} has {emp} registered employees{ceo_p}, active in {act.lower()} "
                f"(Source: {brreg}, {today})."
            )
        else:
            act = nace_desc if nace_desc else (f"a {form}" if form else "a Norwegian registered entity")
            loc = f" in {muni}" if muni else ""
            parts.append(f"{name} is {act}{loc} (Source: {brreg}, {today}).")

        # --- FOLLOW-UP SENTENCES ---
        if aa.get("status") == "available":
            if te_val is not None and ta_val is not None:
                try:
                    eq_v, as_v = float(te_val), float(ta_val)
                    if as_v > 0:
                        ratio = (eq_v / as_v) * 100
                        observations.append(f"Equity ratio: {ratio:.0f}% (Source: {regn})")
                        if ratio > 50:
                            observations.append(f"Strong equity ratio ({ratio:.0f}%)")
                        elif ratio < 20:
                            observations.append(f"Low equity ratio ({ratio:.0f}%) — financial risk")
                except Exception:
                    pass

            if op_val is not None:
                try:
                    if float(op_val) > 0:
                        observations.append("Profitable operations")
                    else:
                        observations.append("Operating at a loss")
                except Exception:
                    pass

            if yoy_text and rev_val is None:
                parts.append(f"Year-over-Year: {yoy_text}")
        else:
            obligation = aa.get("accounting_obligation", "unknown")
            observations.append(f"No financial data on file (obligation: {obligation})")

        if website:
            parts.append(f"Official website: {website} (Source: {website}, {today}).")

        if socials:
            platforms = list(set(s.get("platform", "social") for s in socials[:5]))
            parts.append(f"Active on {', '.join(platforms)} (Source: {website or brreg}, {today}).")
            observations.append(f"Online presence across {len(socials)} platform(s)")

        if news:
            latest = news[0]
            title = latest.get("title", "N/A")
            pub = latest.get("publish_date", latest.get("date", "N/A"))
            src = latest.get("url", website or brreg)
            parts.append(f'Recent news: "{title}" ({pub}) (Source: {src}, {today}).')
            observations.append(f"{len(news)} recent news article(s)")

        if jobs:
            parts.append(f"{len(jobs)} active job listing(s) (Source: arbeidsplassen.nav.no, {today}).")
            observations.append("Currently hiring")

        if ceo_name and "led by" not in parts[0]:
            observations.append(f"CEO/Daglig leder: {ceo_name}")

        if emp and emp > 0 and "employees" not in parts[0]:
            observations.append(f"{emp} registered employees")

        if li.get("is_bankrupt"):
            observations.append("⚠ Company is registered as bankrupt")
        if li.get("is_in_liquidation"):
            observations.append("⚠ Company is under liquidation")

        summary = " ".join(parts)
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
            "status": "available",
            "method": "rule_based",
            "model": None,
            "summary": summary,
            "key_observations": observations,
            "unknowns": unknowns,
            "confidence_assessment": confidence,
        }
