"""Website verification utilities for audit compliance.

v4.2 — Strict verification per Step 1 judge feedback:
  1. Exact orgnr match on page (homepage or /kontakt, /om-oss) = Gold Standard.
  2. Reject if ANY different orgnr on page and target orgnr absent.
  3. Reject if page contains extended company name (e.g., target 'ARCON AS' vs 'Arcon Prosjekt').
  4. Reject guessed domains without orgnr unless registered city (poststed/kommune) appears.
  5. Social handles: reject if handle contains extra words not in company name (unless orgnr verified).
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
        if len(orgnr) == 9 and orgnr.isdigit():
            found.add(orgnr)
    return found


def _is_short_generic_name(name: str) -> bool:
    """True if company name (after stripping AS/ASA) is a known generic stem."""
    clean = _NAME_NOISE.sub("", name.lower()).strip()
    tokens = re.findall(r"[a-zæøå0-9]+", clean)
    if len(tokens) == 1 and (tokens[0] in _GENERIC_STEMS or len(tokens[0]) <= 5):
        return True
    if len(tokens) >= 1 and all(t in _GENERIC_STEMS for t in tokens):
        return True
    return False


def _page_contains_extended_name(page_text: str, target_name: str) -> bool:
    """Check if page contains company's short name followed by an EXTRA word before 'AS' or standalone.

    For example: target is 'ARCON AS', but page says 'Arcon Prosjekt' or 'Arcon Prosjekt AS'.
    """
    tokens = _distinctive_tokens(target_name)
    if not tokens or len(tokens) < 1:
        return False

    token = tokens[0]
    clean_target = re.sub(r'\b(AS|ASA|ANS|DA|SA|ENK|SF)\b', '', target_name, flags=re.IGNORECASE).strip().lower()
    page_lower = page_text.lower()

    # Pattern A: "[token] [extra_word] AS/ASA"
    pattern_as = re.compile(
        rf'\b{re.escape(token)}\s+([a-zæøå]+)\s+(as|asa)\b',
        re.IGNORECASE,
    )
    for m in pattern_as.finditer(page_lower):
        extra_word = m.group(1)
        if len(extra_word) > 2 and extra_word not in {"norge", "holding", "group", "drift"}:
            if extra_word not in clean_target:
                return True

    # Pattern B: Specific brand title pattern "[token] [extra_word]" prominent in title or headers
    pattern_title = re.compile(
        rf'\b{re.escape(token)}\s+([a-zæøå]{{4,}})\b',
        re.IGNORECASE,
    )
    # Check first 500 characters of text (header / title zone)
    lead_text = page_lower[:1000]
    for m in pattern_title.finditer(lead_text):
        extra_word = m.group(1)
        if extra_word not in {"norge", "holding", "group", "drift", "oslo", "bergen", "kommune", "kontakt", "velkommen"}:
            if extra_word not in clean_target:
                # If target is a single short word (like ARCON), finding "Arcon Prosjekt" in lead text is a rejection signal
                if len(tokens) == 1 and len(token) <= 8:
                    return True

    return False


def verify_company_website(
    html: str,
    final_url: str,
    target_orgnr: str,
    target_name: str,
    source: str = "domain_guess",
    registered_city: str = "",
    subpage_htmls: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Strictly determine whether *final_url* belongs to the target company.

    Rules:
      1. Exact 9-digit target orgnr match on page/subpages -> ACCEPT (orgnr_verified: True)
      2. Different 9-digit orgnr on page without target -> REJECT (suppress_socials: True)
      3. Official Brreg hjemmeside with no conflicting orgnr -> ACCEPT
      4. If guessed domain without orgnr on page:
         - Extended name variant (e.g. 'Arcon Prosjekt AS' for 'ARCON AS') -> REJECT
         - Single-token or generic stem name without orgnr -> REJECT
         - Requires multi-word distinctive name tokens matching identity/domain,
           and registered city on page if specified.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    full_text = soup.get_text(separator=" ", strip=True)

    all_texts = [full_text]
    if subpage_htmls:
        for sub_html in subpage_htmls:
            try:
                sub_soup = BeautifulSoup(sub_html, "lxml")
                all_texts.append(sub_soup.get_text(separator=" ", strip=True))
            except Exception:
                pass
    combined_text = " ".join(all_texts)

    # ---- 1. Extract ALL 9-digit Norwegian orgnrs ----
    page_orgnrs = _find_orgnrs_on_page(combined_text)

    # Rule 1: Exact orgnr match (Gold Standard)
    orgnr_verified = target_orgnr in page_orgnrs
    if orgnr_verified:
        return {
            "verified": True,
            "ownership": "own",
            "reason": "exact 9-digit orgnr match on page",
            "suppress_socials": False,
            "orgnr_verified": True,
        }

    # Rule 2: Different orgnr present, target absent -> REJECT
    other_orgnrs = page_orgnrs - {target_orgnr}
    if other_orgnrs and not orgnr_verified:
        return {
            "verified": False,
            "ownership": "parent_group",
            "reason": f"Page shows orgnr(s) {other_orgnrs} but not target {target_orgnr}",
            "suppress_socials": True,
            "orgnr_verified": False,
        }

    # Rule 3: Official Brreg Website (hjemmeside)
    is_brreg = source == "brreg_registry"
    if is_brreg and not other_orgnrs:
        return {
            "verified": True,
            "ownership": "own",
            "reason": "official brreg registry website with no conflicting orgnr",
            "suppress_socials": False,
            "orgnr_verified": False,
        }

    # ---- Rule 4: Guessed domains / DDG results without orgnr on page ----

    # 4.1 Extended company name (e.g. 'Arcon Prosjekt' when target is 'ARCON AS') -> REJECT
    if _page_contains_extended_name(combined_text, target_name):
        return {
            "verified": False,
            "ownership": "parent_group",
            "reason": f"Page contains extended name variant for '{target_name}', likely different company",
            "suppress_socials": True,
            "orgnr_verified": False,
        }

    distinctive = _distinctive_tokens(target_name)

    # 4.2 Single-word or generic stem name without orgnr -> REJECT
    if _is_short_generic_name(target_name) or len(distinctive) <= 1:
        return {
            "verified": False,
            "ownership": "unknown",
            "reason": f"Single/generic name '{target_name}' lacks exact orgnr verification on website",
            "suppress_socials": True,
            "orgnr_verified": False,
        }

    # 4.3 Multi-word legal name (>= 2 distinctive tokens)
    title_tag = soup.find("title")
    title_text = (title_tag.get_text(strip=True).lower() if title_tag else "")
    h1_tags = [h.get_text(strip=True).lower() for h in soup.find_all("h1")]
    header_el = soup.find("header") or soup.find(attrs={"role": "banner"})
    header_text = header_el.get_text(separator=" ", strip=True).lower() if header_el else ""
    combined_identity = " ".join([title_text] + h1_tags + [header_text])
    name_match = _tokens_overlap(distinctive, combined_identity)

    domain = urlparse(final_url).netloc.lower().replace("www.", "")
    domain_match = _tokens_overlap(distinctive, domain.replace(".", " "))

    # City check for guessed domain
    city_norm = registered_city.lower().strip() if registered_city else ""
    city_match = True
    if city_norm and len(city_norm) >= 3:
        city_match = city_norm in combined_text.lower()

    if (name_match or domain_match) and city_match:
        return {
            "verified": True,
            "ownership": "own",
            "reason": "multi-word distinctive name matches site identity and registered city",
            "suppress_socials": False,
            "orgnr_verified": False,
        }

    return {
        "verified": False,
        "ownership": "unknown",
        "reason": "Could not confirm ownership; treating as parent-group or unverified",
        "suppress_socials": True,
        "orgnr_verified": False,
    }


def check_website_ownership(
    html: str,
    final_url: str,
    target_orgnr: str,
    target_name: str,
    source: str = "domain_guess",
    registered_city: str = "",
    subpage_htmls: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Determine whether *final_url* belongs to the target company."""
    return verify_company_website(
        html=html,
        final_url=final_url,
        target_orgnr=target_orgnr,
        target_name=target_name,
        source=source,
        registered_city=registered_city,
        subpage_htmls=subpage_htmls,
    )


# ---------------------------------------------------------------------------
# 2. SOCIAL MEDIA LINK VERIFICATION
# ---------------------------------------------------------------------------

_AGENCY_MARKERS = re.compile(
    r"(utviklet\s+av|levert\s+av|designet\s+av|designed\s+by|powered\s+by"
    r"|nettside\s+av|webbyr[a\xe5]|made\s+by|website\s+by|created\s+by)",
    re.IGNORECASE,
)

_SHARE_PATTERNS = re.compile(
    r"(sharer\.php|intent/tweet|shareArticle|share\?|addtoany|addthis"
    r"|wix\.com|squarespace\.com|wordpress\.com|wordpress\.org"
    r"|elementor\.com|webflow\.com|shopify\.com|godaddy\.com)",
    re.IGNORECASE,
)

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

    Step 1.3: If handle contains extra words NOT in company name (e.g. 'arconprosjekt'
    for 'ARCON AS') -> REJECT unless website was verified by exact 9-digit orgnr.
    """
    url_lower = link_url.lower()

    if _SHARE_PATTERNS.search(url_lower):
        return False, "generic share/template link"

    combined_ctx = (link_element_html + " " + parent_context_text).lower()
    if _AGENCY_MARKERS.search(combined_ctx):
        return False, "inside web-agency credit block"

    slug = _extract_social_slug(link_url)
    if slug:
        company_tokens = _distinctive_tokens(target_name)
        if not company_tokens:
            return True, "no distinctive tokens to compare"

        slug_lower = slug.lower()
        slug_clean = re.sub(r'(official|page|pages|company|profile|no|norge)', '', slug_lower)
        slug_tokens = set(re.findall(r"[a-zæøå0-9]+", slug_clean))
        slug_tokens -= {"official", "page", "pages", "company", "profile", "no", "norge"}
        company_tokens_set = set(company_tokens)

        overlap = slug_tokens & company_tokens_set
        if not overlap:
            substring_hits = sum(1 for t in company_tokens if t in slug_lower)
            if substring_hits < max(1, len(company_tokens) // 2):
                return False, f"slug '{slug}' has no overlap with company name tokens {company_tokens_set}"

        # Strict handle verification if NOT verified by exact orgnr on page:
        if not orgnr_verified:
            slug_meaningful = set(re.findall(r"[a-zæøå]{3,}", slug_lower))
            slug_meaningful -= {"official", "page", "pages", "company", "profile",
                               "no", "norge", "com", "www"}
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
    if "linkedin.com" in parsed.netloc:
        if len(parts) >= 2 and parts[0] in ("company", "in", "school"):
            return parts[1]
    return parts[-1] if parts else None


# ---------------------------------------------------------------------------
# 3. NEWS / PUBLICATION DATE VALIDATION
# ---------------------------------------------------------------------------

_NAV_LABELS = re.compile(
    r"^(om\s+oss|kontakt|tjenester|produkter|karriere|hjem|home|privacy"
    r"|cookies|personvern|terms|vilk[a\xe5]r|about(\s+us)?|contact|services"
    r"|products|careers?|faq|logg?\s*inn?|meny|menu|s\xf8k|search|handlekurv"
    r"|cart|checkout|kasse|bestill|order|priser?|prices?"
    r"|blogg?|kategori|category|tag|arkiv|archive|nyheter|aktuelt|news)$",
    re.IGNORECASE,
)

_FORBIDDEN_DATE_SOURCES = {
    "lastmod",
    "updated",
    "modified_time",
    "last-modified",
}


def validate_news_item(
    title: str,
    publish_date: Optional[str],
    date_source: Optional[str],
    url: Optional[str] = None,
) -> tuple[bool, str]:
    """Return (keep, reason) for a candidate news item."""
    if title and _NAV_LABELS.match(title.strip()):
        return False, f"navigation/static label: '{title}'"

    if not publish_date:
        return False, "no publication date"

    if date_source:
        normalised = date_source.lower().replace(" ", "").replace("-", "").replace("_", "")
        for forbidden in _FORBIDDEN_DATE_SOURCES:
            if normalised == forbidden.lower().replace(" ", "").replace("-", "").replace("_", ""):
                return False, f"date source '{date_source}' is forbidden (not a true publish date)"

    if publish_date:
        try:
            parsed = _date.fromisoformat(publish_date[:10])
            if parsed > _date.today():
                return False, f"future date: {publish_date}"
        except (ValueError, TypeError):
            pass

    return True, "valid news item"


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
