"""Website verification utilities for audit compliance.

Implements three competition-audit rules:
  1. Parent Group vs Own Website ownership check
  2. Strict social-media link verification
  3. Strict news & publication-date validation
"""
from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# 1. PARENT-GROUP / OWN-WEBSITE OWNERSHIP CHECK
# ---------------------------------------------------------------------------

def check_website_ownership(
    html: str,
    final_url: str,
    target_orgnr: str,
    target_name: str,
) -> dict[str, Any]:
    """Determine whether *final_url* belongs to the target company or a parent group.

    Returns a dict:
        ownership  - "own" | "parent_group" | "unknown"
        reason     - human-readable explanation
        suppress_socials - True when social/news/jobs should NOT be attributed
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")

    # ---- Check 1: Does the exact 9-digit orgnr appear? ----
    orgnr_found = target_orgnr in html

    # ---- Check 2: Does the target company's distinctive name appear in
    #      the page title / <h1> / header / footer? ----
    distinctive = _distinctive_tokens(target_name)
    title_tag = soup.find("title")
    title_text = (title_tag.get_text(strip=True).lower() if title_tag else "")
    h1_tags = [h.get_text(strip=True).lower() for h in soup.find_all("h1")]

    header_el = soup.find("header") or soup.find(attrs={"role": "banner"})
    header_text = header_el.get_text(separator=" ", strip=True).lower() if header_el else ""

    combined_identity = " ".join([title_text] + h1_tags + [header_text])

    name_match = _tokens_overlap(distinctive, combined_identity)

    # ---- Check 3: Look for *different* orgnr in footer / terms ----
    footer_el = soup.find("footer") or soup.find(attrs={"role": "contentinfo"})
    footer_text = footer_el.get_text(separator=" ", strip=True) if footer_el else ""
    other_orgnrs = set(re.findall(r"\b\d{9}\b", footer_text)) - {target_orgnr}

    # ---- Decision tree ----
    if orgnr_found and name_match:
        return {"ownership": "own", "reason": "orgnr + name match on page",
                "suppress_socials": False}

    if orgnr_found and not other_orgnrs:
        return {"ownership": "own", "reason": "orgnr found, no competing orgnr",
                "suppress_socials": False}

    if other_orgnrs:
        return {"ownership": "parent_group",
                "reason": f"Different orgnr(s) in footer: {other_orgnrs}",
                "suppress_socials": True}

    if name_match:
        return {"ownership": "own", "reason": "distinctive name matches site identity",
                "suppress_socials": False}

    # Heuristic: domain matches company name (ignoring generic suffixes)
    domain = urlparse(final_url).netloc.lower().replace("www.", "")
    if _tokens_overlap(distinctive, domain.replace(".", " ")):
        return {"ownership": "own", "reason": "domain matches company name",
                "suppress_socials": False}

    return {"ownership": "unknown",
            "reason": "Could not confirm ownership; treating as parent-group",
            "suppress_socials": True}


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
) -> tuple[bool, str]:
    """Return (keep, reason) for a single social link URL.

    *link_element_html*  - outer HTML of the <a> tag (for context)
    *parent_context_text* - text of the surrounding parent element (e.g. <div>)
    """
    url_lower = link_url.lower()

    # Rule A: reject share / template links
    if _SHARE_PATTERNS.search(url_lower):
        return False, "generic share/template link"

    # Rule B: reject links found inside an agency credit block
    combined_ctx = (link_element_html + " " + parent_context_text).lower()
    if _AGENCY_MARKERS.search(combined_ctx):
        return False, "inside web-agency credit block"

    # Rule C: handle/slug must overlap with target company name
    slug = _extract_social_slug(link_url)
    if slug:
        company_tokens = _distinctive_tokens(target_name)
        if not company_tokens:
            # Cannot verify - keep (benefit of the doubt when name is empty)
            return True, "no distinctive tokens to compare"
        slug_tokens = set(re.findall(r"[a-z0-9]+", slug.lower()))
        # Remove noise tokens from both sides
        slug_tokens -= {"official", "page", "pages", "company", "profile"}
        company_tokens_set = set(company_tokens)
        overlap = slug_tokens & company_tokens_set
        if not overlap:
            return False, f"slug '{slug}' has no overlap with company name tokens {company_tokens_set}"

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
    """Return (keep, reason) for a candidate news item.

    *date_source* should be one of:
        "datePublished", "article:published_time", "pubDate",
        "<time datetime>", "published", "visible_date"
      - or one of the FORBIDDEN ones listed above.
    """
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
