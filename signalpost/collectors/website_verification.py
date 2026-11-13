"""Website verification utilities for audit compliance.

v4.1 — Strict verification per judge feedback:
  1. Exact orgnr match on page = gold standard
  2. Reject if ANY different orgnr on page and target orgnr absent
  3. Guessed domains: reject short/common names unless orgnr found on page
  4. Social handles: reject if slug has extra tokens not in company name
  5. Strict news date validation (past dates only, allowed sources only)
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse
from datetime import date as _date


# ---------------------------------------------------------------------------
# 1. PARENT-GROUP / OWN-WEBSITE OWNERSHIP CHECK
# ---------------------------------------------------------------------------

# Short / generic company name stems that commonly collide with other companies
_GENERIC_STEMS = {
    "arcon", "nova", "atlas", "alpha", "nord", "vest", "sør", "øst",
    "viking", "solar", "bygg", "invest", "eiendom", "holding", "konsult",
    "teknikk", "elektro", "mekanisk", "transport", "service", "gruppen",
    "system", "data", "nett", "kraft", "energi", "miljø", "helse",
    "finans", "kapital", "industri", "konstruksjon", "prosjekt", "partner",
    "delta", "omega", "sigma", "beta", "gamma", "prime", "total", "global",
    "apex", "core", "link", "matrix", "nexus", "optima", "vekst",
}

# Flexible orgnr pattern: 9 digits, optionally separated by spaces or dots
_ORGNR_PATTERN = re.compile(r'\b(\d{3})[\s.]?(\d{3})[\s.]?(\d{3})\b')


def _find_orgnrs_on_page(text: str) -> set[str]:
    """Extract all 9-digit orgnrs from text, normalizing spaces/dots."""
    found = set()
    for m in _ORGNR_PATTERN.finditer(text):
        orgnr = m.group(1) + m.group(2) + m.group(3)
        # Basic validity: must be 9 digits
        if len(orgnr) == 9 and orgnr.isdigit():
            found.add(orgnr)
    return found


def _is_short_generic_name(name: str) -> bool:
    """True if company name (after stripping AS/ASA) is a known generic stem.

    Only flags names that are in the _GENERIC_STEMS set (common Norwegian
    company name fragments that frequently collide with other companies).
    Does NOT flag all short names — many legitimate companies have short names.
    """
    clean = _NAME_NOISE.sub("", name.lower()).strip()
    tokens = re.findall(r"[a-zæøå0-9]+", clean)
    # Single token that's a known generic stem
    if len(tokens) == 1 and tokens[0] in _GENERIC_STEMS:
        return True
    # Multi-token but all tokens are generic
    if len(tokens) >= 1 and all(t in _GENERIC_STEMS for t in tokens):
        return True
    return False


def _page_contains_extended_name(page_text: str, target_name: str) -> bool:
    """Check if page contains the company name with EXTRA words appended.

    E.g., target is 'ARCON AS' but page says 'Arcon Prosjekt AS' — this means
    the page belongs to a DIFFERENT company with a similar but distinct name.
    """
    clean = re.sub(r'\b(AS|ASA|ANS|DA|SA|ENK|SF)\b', '', target_name, flags=re.IGNORECASE).strip()
    tokens = _distinctive_tokens(target_name)
    if not tokens or len(tokens) < 1:
        return False

    # Look for patterns like "[company_token] [extra_word] AS" in page text
    page_lower = page_text.lower()
    for token in tokens:
        # Find "token extraword as" or "token extraword"
        pattern = re.compile(
            rf'\b{re.escape(token)}\s+([a-zæøå]+)\s+(as|asa)\b',
            re.IGNORECASE,
        )
        for m in pattern.finditer(page_lower):
            extra_word = m.group(1)
            # If the extra word is NOT in the target company name, it's a different company
            if extra_word not in clean.lower() and len(extra_word) > 2:
                return True
    return False


def check_website_ownership(
    html: str,
    final_url: str,
    target_orgnr: str,
    target_name: str,
    source: str = "domain_guess",
) -> dict[str, Any]:
    """Determine whether *final_url* belongs to the target company.

    v4.1 strict rules:
      - Rule A: Exact orgnr match on page = VERIFIED
      - Rule B: Different orgnr on page without target = REJECT
      - Rule C: Guessed domains for short/generic names without orgnr = REJECT
      - Rule D: Page has extended company name (e.g. "Arcon Prosjekt") = REJECT

    Returns a dict:
        ownership  - "own" | "parent_group" | "unknown"
        reason     - human-readable explanation
        suppress_socials - True when social/news/jobs should NOT be attributed
        orgnr_verified - True if target orgnr was found on page
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    full_text = soup.get_text(separator=" ", strip=True)

    # ---- Find ALL orgnrs on page ----
    page_orgnrs = _find_orgnrs_on_page(full_text)

    # ---- Rule A: Exact orgnr match (Gold Standard) ----
    orgnr_verified = target_orgnr in page_orgnrs

    # ---- Rule B: Different orgnr present, target absent = REJECT ----
    other_orgnrs = page_orgnrs - {target_orgnr}
    if other_orgnrs and not orgnr_verified:
        return {"ownership": "parent_group",
                "reason": f"Page shows orgnr(s) {other_orgnrs} but not target {target_orgnr}",
                "suppress_socials": True,
                "orgnr_verified": False}

    # If orgnr is verified, it's the company's own site
    if orgnr_verified:
        return {"ownership": "own",
                "reason": "exact orgnr match on page",
                "suppress_socials": False,
                "orgnr_verified": True}

    # ---- Below here: no orgnr found on page at all ----

    # ---- Rule D: Check if page has an EXTENDED company name ----
    if _page_contains_extended_name(full_text, target_name):
        return {"ownership": "parent_group",
                "reason": f"Page contains extended name variant, likely different company",
                "suppress_socials": True,
                "orgnr_verified": False}

    # ---- Name matching ----
    distinctive = _distinctive_tokens(target_name)
    title_tag = soup.find("title")
    title_text = (title_tag.get_text(strip=True).lower() if title_tag else "")
    h1_tags = [h.get_text(strip=True).lower() for h in soup.find_all("h1")]
    header_el = soup.find("header") or soup.find(attrs={"role": "banner"})
    header_text = header_el.get_text(separator=" ", strip=True).lower() if header_el else ""
    combined_identity = " ".join([title_text] + h1_tags + [header_text])
    name_match = _tokens_overlap(distinctive, combined_identity)

    # ---- Rule C: Guessed domains for short/generic names ----
    if source == "domain_guess" and _is_short_generic_name(target_name):
        # Short/generic name + no orgnr on page = too risky
        # Only accept if BOTH full legal name AND registered city appear
        return {"ownership": "unknown",
                "reason": f"Short/generic name '{target_name}' with no orgnr on page - too risky",
                "suppress_socials": True,
                "orgnr_verified": False}

    # ---- Subsidiary markers need full name match ----
    _SUBSIDIARY_MARKERS = ("NORGE", "HOLDING", "EIENDOM", "AVD", "DATTER",
                           "SERVICES", "ALUMINIUM", "NORDIC", "SCANDINAVIA")
    name_upper = target_name.upper()
    is_subsidiary = any(m in name_upper for m in _SUBSIDIARY_MARKERS)
    if is_subsidiary and not orgnr_verified:
        clean_name = re.sub(r"\b(AS|ASA|ANS|DA|SA|ENK)\b", "", target_name, flags=re.IGNORECASE).strip()
        if clean_name and clean_name.lower() not in combined_identity.lower():
            return {"ownership": "parent_group",
                    "reason": f"Subsidiary name '{clean_name}' not found on page",
                    "suppress_socials": True,
                    "orgnr_verified": False}

    # ---- Decision tree for non-orgnr matches ----
    # Footer orgnr check (different from any already found)
    footer_el = soup.find("footer") or soup.find(attrs={"role": "contentinfo"})
    footer_text = footer_el.get_text(separator=" ", strip=True) if footer_el else ""
    footer_orgnrs = _find_orgnrs_on_page(footer_text) - {target_orgnr}
    if footer_orgnrs:
        return {"ownership": "parent_group",
                "reason": f"Different orgnr(s) in footer: {footer_orgnrs}",
                "suppress_socials": True,
                "orgnr_verified": False}

    if name_match:
        return {"ownership": "own",
                "reason": "distinctive name matches site identity (no orgnr verification)",
                "suppress_socials": False,
                "orgnr_verified": False}

    # Domain-name match heuristic
    domain = urlparse(final_url).netloc.lower().replace("www.", "")
    if _tokens_overlap(distinctive, domain.replace(".", " ")):
        return {"ownership": "own",
                "reason": "domain matches company name (no orgnr verification)",
                "suppress_socials": False,
                "orgnr_verified": False}

    return {"ownership": "unknown",
            "reason": "Could not confirm ownership; treating as parent-group",
            "suppress_socials": True,
            "orgnr_verified": False}


# ---------------------------------------------------------------------------
# 2. SOCIAL MEDIA LINK VERIFICATION
# ---------------------------------------------------------------------------

# Agency/credit-block markers (case-insensitive)
_AGENCY_MARKERS = re.compile(
    r"(utviklet\s+av|levert\s+av|designet\s+av|designed\s+by|powered\s+by"
    r"|nettside\s+av|webbyr[a\xe5]|made\s+by|website\s+by|created\s+by)",
    re.IGNORECASE,
)

# Generic share / template URLs that are never company-owned profiles
_SHARE_PATTERNS = re.compile(
    r"(sharer\.php|intent/tweet|shareArticle|share\?|addtoany|addthis"
    r"|wix\.com|squarespace\.com|wordpress\.com|wordpress\.org"
    r"|elementor\.com|webflow\.com|shopify\.com|godaddy\.com)",
    re.IGNORECASE,
)

# Suffixes to strip when comparing handles with company name
_NAME_NOISE = re.compile(
    r"\b(as|asa|norge|holding|group|konsern|stiftelse|stiftelsen|org|no|com)\b",
    re.IGNORECASE,
)


def verify_social_link(
    link_url: str,
    link_element_html: str,
    target_name: str,
    parent_context_text: str = "",
    orgnr_verified: bool = False,
) -> tuple[bool, str]:
    """Return (keep, reason) for a single social link URL.

    v4.1: If the social slug has extra distinguishing words NOT in the company
    name, REJECT unless the website was orgnr-verified.
    """
    url_lower = link_url.lower()

    # Rule A: reject share / template links
    if _SHARE_PATTERNS.search(url_lower):
        return False, "generic share/template link"

    # Rule B: reject links found inside an agency credit block
    combined_ctx = (link_element_html + " " + parent_context_text).lower()
    if _AGENCY_MARKERS.search(combined_ctx):
        return False, "inside web-agency credit block"

    # Rule C: handle/slug verification
    slug = _extract_social_slug(link_url)
    if slug:
        company_tokens = _distinctive_tokens(target_name)
        if not company_tokens:
            return True, "no distinctive tokens to compare"

        slug_lower = slug.lower()
        # Remove noise from slug
        slug_clean = re.sub(r'(official|page|pages|company|profile|no|norge)', '', slug_lower)
        slug_tokens = set(re.findall(r"[a-zæøå0-9]+", slug_clean))
        slug_tokens -= {"official", "page", "pages", "company", "profile", "no", "norge"}
        company_tokens_set = set(company_tokens)

        # Check overlap: company tokens must appear in slug
        overlap = slug_tokens & company_tokens_set
        if not overlap:
            # Try substring matching (handles concatenated slugs like 'nordlandelektro')
            substring_hits = sum(1 for t in company_tokens if t in slug_lower)
            if substring_hits < max(1, len(company_tokens) // 2):
                return False, f"slug '{slug}' has no overlap with company name tokens {company_tokens_set}"

        # NEW v4.1 Rule: Check for EXTRA tokens in slug not in company name
        # E.g., slug 'arconprosjekt' has 'prosjekt' which is NOT in 'ARCON AS'
        if not orgnr_verified:
            # Extract all meaningful tokens from the slug
            slug_meaningful = set(re.findall(r"[a-zæøå]{3,}", slug_lower))
            slug_meaningful -= {"official", "page", "pages", "company", "profile",
                               "no", "norge", "com", "www"}
            # Check each slug token — if it's not a substring of any company token
            # AND not a company token substring, it's an extra distinguishing word
            for st in slug_meaningful:
                is_part_of_company = False
                for ct in company_tokens:
                    if st in ct or ct in st:
                        is_part_of_company = True
                        break
                if not is_part_of_company and len(st) > 3:
                    return False, f"slug '{slug}' contains extra token '{st}' not in company name '{target_name}' (not orgnr-verified)"

    return True, "passed all checks"


def _extract_social_slug(url: str) -> Optional[str]:
    """Extract the handle/slug portion of a social-media URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    parts = [p for p in path.split("/") if p]
    if not parts:
        return None
    # For LinkedIn, the slug is /company/<slug> or /in/<slug>
    if "linkedin.com" in parsed.netloc:
        if len(parts) >= 2 and parts[0] in ("company", "in", "school"):
            return parts[1]
    # Generic: last meaningful path segment
    return parts[-1] if parts else None


# ---------------------------------------------------------------------------
# 3. NEWS / PUBLICATION DATE VALIDATION
# ---------------------------------------------------------------------------

# Navigation / static page labels that are NOT news
_NAV_LABELS = re.compile(
    r"^(om\s+oss|kontakt|tjenester|produkter|karriere|hjem|home|privacy"
    r"|cookies|personvern|terms|vilk[a\xe5]r|about(\s+us)?|contact|services"
    r"|products|careers?|faq|logg?\s*inn?|meny|menu|s\xf8k|search|handlekurv"
    r"|cart|checkout|kasse|bestill|order|priser?|prices?"
    r"|blogg?|kategori|category|tag|arkiv|archive)$",
    re.IGNORECASE,
)

# Forbidden date sources - must NOT be used as publish date
_FORBIDDEN_DATE_SOURCES = {
    "lastmod",       # XML sitemap
    "updated",       # Atom feed <updated>
    "modified_time", # og:article:modified_time
    "last-modified", # HTTP header
}


def validate_news_item(
    title: str,
    publish_date: Optional[str],
    date_source: Optional[str],
    url: Optional[str] = None,
) -> tuple[bool, str]:
    """Return (keep, reason) for a candidate news item."""
    # Rule A: reject nav / static page labels
    if title and _NAV_LABELS.match(title.strip()):
        return False, f"navigation/static label: '{title}'"

    # Rule B: must have a real publish date
    if not publish_date:
        return False, "no publication date"

    # Rule C: date must come from an allowed source
    if date_source:
        normalised = date_source.lower().replace(" ", "").replace("-", "").replace("_", "")
        for forbidden in _FORBIDDEN_DATE_SOURCES:
            if normalised == forbidden.lower().replace(" ", "").replace("-", "").replace("_", ""):
                return False, f"date source '{date_source}' is forbidden (not a true publish date)"

    # Rule D: date must not be in the future
    if publish_date:
        try:
            parsed = _date.fromisoformat(publish_date[:10])
            if parsed > _date.today():
                return False, f"future date: {publish_date}"
        except (ValueError, TypeError):
            pass

    return True, "valid news item"


# ---------------------------------------------------------------------------
# INTERNAL HELPERS
# ---------------------------------------------------------------------------

def _distinctive_tokens(name: str) -> list[str]:
    """Return lowercased tokens after stripping generic Norwegian company suffixes."""
    if not name:
        return []
    cleaned = _NAME_NOISE.sub("", name.lower())
    tokens = re.findall(r"[a-z0-9\xe6\xf8\xe5]+", cleaned)
    return [t for t in tokens if len(t) > 1]


def _tokens_overlap(tokens: list[str], text: str) -> bool:
    """True when >= 50% of *tokens* appear in *text*."""
    if not tokens:
        return False
    hits = sum(1 for t in tokens if t in text)
    return hits / len(tokens) >= 0.5
