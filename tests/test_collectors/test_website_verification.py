"""Tests for the three audit-compliance rules in website_verification.py.

Audit Issue 1: Parent Group vs. Own Website Ownership Check
Audit Issue 2: Strict Social Media Link Verification
Audit Issue 3: Strict News & Publication Date Validation
"""
import pytest

from signalpost.collectors.website_verification import (
    check_website_ownership,
    verify_social_link,
    validate_news_item,
    _distinctive_tokens,
    _tokens_overlap,
    _extract_social_slug,
)


# ==========================================================================
# AUDIT ISSUE 1: Parent Group vs. Own Website Ownership
# ==========================================================================

class TestWebsiteOwnership:
    """Test parent-group detection and own-site confirmation."""

    def test_own_site_orgnr_and_name(self):
        """Site shows target orgnr AND name -> own site."""
        html = """
        <html><head><title>Equinor - Energy company</title></head>
        <body>
          <header><h1>Equinor ASA</h1></header>
          <footer>Org.nr: 923609016</footer>
        </body></html>
        """
        result = check_website_ownership(html, "https://equinor.com", "923609016", "EQUINOR ASA")
        assert result["ownership"] == "own"
        assert result["suppress_socials"] is False

    def test_own_site_orgnr_only(self):
        """Site shows target orgnr, no competing orgnr -> own site."""
        html = """
        <html><head><title>Some Company</title></head>
        <body><footer>Organisasjonsnummer: 123456789</footer></body></html>
        """
        result = check_website_ownership(html, "https://example.com", "123456789", "Some Company AS")
        assert result["ownership"] == "own"
        assert result["suppress_socials"] is False

    def test_parent_group_different_orgnr(self):
        """Footer has a DIFFERENT orgnr -> parent group site, suppress socials."""
        html = """
        <html><head><title>Big Group Corporation</title></head>
        <body>
          <header><h1>Big Group</h1></header>
          <footer>
            Big Group AS - Org.nr: 999888777
            Alle rettigheter forbeholdt
          </footer>
        </body></html>
        """
        result = check_website_ownership(
            html, "https://biggroup.no", "111222333", "Little Subsidiary AS"
        )
        assert result["ownership"] == "parent_group"
        assert result["suppress_socials"] is True

    def test_own_site_name_match_no_orgnr(self):
        """No orgnr anywhere, but name matches site identity -> own site."""
        html = """
        <html><head><title>Fjord Consulting</title></head>
        <body><header><h1>Fjord Consulting</h1></header>
        <footer>Contact us at info@fjordconsulting.no</footer>
        </body></html>
        """
        result = check_website_ownership(
            html, "https://fjordconsulting.no", "444555666", "Fjord Consulting AS"
        )
        assert result["ownership"] == "own"
        assert result["suppress_socials"] is False

    def test_unknown_ownership(self):
        """No orgnr, no name match, no domain match -> unknown (suppressed)."""
        html = """
        <html><head><title>Totally Different Site</title></head>
        <body><h1>Welcome</h1><footer>No info here</footer></body></html>
        """
        result = check_website_ownership(
            html, "https://random-site.com", "777888999", "Nordland Teknikk AS"
        )
        assert result["ownership"] in ("unknown", "parent_group")
        assert result["suppress_socials"] is True

    def test_domain_matches_company_name(self):
        """Domain closely matches company name -> own site."""
        html = """
        <html><head><title>Welcome</title></head>
        <body><h1>Welcome</h1></body></html>
        """
        result = check_website_ownership(
            html, "https://nordlandteknikk.no", "777888999", "Nordland Teknikk AS"
        )
        assert result["ownership"] == "own"
        assert result["suppress_socials"] is False


# ==========================================================================
# AUDIT ISSUE 2: Strict Social Media Link Verification
# ==========================================================================

class TestSocialLinkVerification:
    """Test agency-block rejection, share-link rejection, and slug matching."""

    def test_valid_social_link(self):
        """Matching company name in slug -> accepted."""
        keep, reason = verify_social_link(
            "https://www.linkedin.com/company/equinor",
            '<a href="https://www.linkedin.com/company/equinor">LinkedIn</a>',
            "EQUINOR ASA",
        )
        assert keep is True

    def test_reject_share_link(self):
        """Facebook sharer.php -> rejected."""
        keep, reason = verify_social_link(
            "https://www.facebook.com/sharer.php?u=https://example.com",
            '<a href="...">Share on Facebook</a>',
            "Test Company AS",
        )
        assert keep is False
        assert "share" in reason.lower()

    def test_reject_twitter_intent(self):
        """Twitter intent/tweet -> rejected."""
        keep, reason = verify_social_link(
            "https://twitter.com/intent/tweet?text=hello",
            '<a href="...">Tweet this</a>',
            "Test Company AS",
        )
        assert keep is False

    def test_reject_agency_credit_block(self):
        """Link inside 'Designet av' agency credit -> rejected."""
        keep, reason = verify_social_link(
            "https://www.instagram.com/webbyra_oslo",
            '<a href="https://www.instagram.com/webbyra_oslo">Instagram</a>',
            "Fjord Service AS",
            parent_context_text="Designet av WebByraa Oslo",
        )
        assert keep is False
        assert "agency" in reason.lower()

    def test_reject_utviklet_av_block(self):
        """Link inside 'utviklet av' block -> rejected."""
        keep, reason = verify_social_link(
            "https://www.facebook.com/some_agency",
            '<a href="...">Facebook</a>',
            "Test Company AS",
            parent_context_text="Nettside utviklet av Some Agency",
        )
        assert keep is False

    def test_reject_powered_by(self):
        """Link in 'powered by' context -> rejected."""
        keep, reason = verify_social_link(
            "https://www.linkedin.com/company/squarespace",
            '<a href="...">LinkedIn</a>',
            "My Company AS",
            parent_context_text="Powered by Squarespace",
        )
        assert keep is False

    def test_reject_wix_link(self):
        """wix.com social link -> rejected as template."""
        keep, reason = verify_social_link(
            "https://www.wix.com/my-site/follow",
            '<a href="...">Follow</a>',
            "Test Company AS",
        )
        assert keep is False

    def test_reject_no_slug_overlap(self):
        """Slug has no overlap with company name -> rejected."""
        keep, reason = verify_social_link(
            "https://www.linkedin.com/company/totally-different",
            '<a href="...">LinkedIn</a>',
            "Nordland Elektro AS",
        )
        assert keep is False
        assert "no overlap" in reason.lower()

    def test_accept_partial_name_overlap(self):
        """Slug partially matches company name -> accepted."""
        keep, reason = verify_social_link(
            "https://www.facebook.com/nordlandelektro",
            '<a href="...">Facebook</a>',
            "Nordland Elektro AS",
        )
        assert keep is True


# ==========================================================================
# AUDIT ISSUE 3: Strict News & Publication Date Validation
# ==========================================================================

class TestNewsValidation:
    """Test nav label rejection, missing date rejection, and forbidden date sources."""

    def test_valid_news_item(self):
        """Proper headline with datePublished -> accepted."""
        keep, reason = validate_news_item(
            "Equinor reports Q3 2025 results",
            "2025-10-15T10:00:00Z",
            "datePublished",
        )
        assert keep is True

    def test_reject_nav_label_om_oss(self):
        """'Om oss' page title -> rejected as navigation."""
        keep, reason = validate_news_item("Om oss", "2024-01-01", "datePublished")
        assert keep is False
        assert "navigation" in reason.lower()

    def test_reject_nav_label_kontakt(self):
        """'Kontakt' -> rejected."""
        keep, reason = validate_news_item("Kontakt", "2024-01-01", "datePublished")
        assert keep is False

    def test_reject_nav_label_tjenester(self):
        """'Tjenester' -> rejected."""
        keep, reason = validate_news_item("Tjenester", "2024-01-01", "datePublished")
        assert keep is False

    def test_reject_nav_label_produkter(self):
        """'Produkter' -> rejected."""
        keep, reason = validate_news_item("Produkter", "2024-01-01", "datePublished")
        assert keep is False

    def test_reject_nav_label_karriere(self):
        """'Karriere' -> rejected."""
        keep, reason = validate_news_item("Karriere", "2024-01-01", "datePublished")
        assert keep is False

    def test_reject_nav_label_privacy(self):
        """'Privacy' -> rejected."""
        keep, reason = validate_news_item("Privacy", "2024-01-01", "datePublished")
        assert keep is False

    def test_reject_nav_label_cookies(self):
        """'Cookies' -> rejected."""
        keep, reason = validate_news_item("Cookies", "2024-01-01", "datePublished")
        assert keep is False

    def test_reject_nav_label_home(self):
        """'Home' and 'Hjem' -> rejected."""
        keep1, _ = validate_news_item("Home", "2024-01-01", "datePublished")
        keep2, _ = validate_news_item("Hjem", "2024-01-01", "datePublished")
        assert keep1 is False
        assert keep2 is False

    def test_reject_no_date(self):
        """Missing publish date -> rejected."""
        keep, reason = validate_news_item("Great headline", None, None)
        assert keep is False
        assert "no publication date" in reason.lower()

    def test_reject_lastmod_as_date(self):
        """XML sitemap lastmod used as publish date -> rejected."""
        keep, reason = validate_news_item(
            "Some Article", "2024-03-15", "lastmod"
        )
        assert keep is False
        assert "forbidden" in reason.lower()

    def test_reject_updated_as_date(self):
        """Atom <updated> used as publish date -> rejected."""
        keep, reason = validate_news_item(
            "Some Article", "2024-03-15", "updated"
        )
        assert keep is False

    def test_reject_modified_time(self):
        """article:modified_time -> rejected."""
        keep, reason = validate_news_item(
            "Some Article", "2024-03-15", "modified_time"
        )
        assert keep is False

    def test_reject_last_modified_header(self):
        """HTTP Last-Modified header -> rejected."""
        keep, reason = validate_news_item(
            "Some Article", "2024-03-15", "last-modified"
        )
        assert keep is False

    def test_accept_pubdate(self):
        """RSS pubDate -> accepted."""
        keep, reason = validate_news_item(
            "Company wins award", "Tue, 15 Oct 2024 10:00:00 GMT", "pubDate"
        )
        assert keep is True

    def test_accept_published(self):
        """Atom <published> -> accepted."""
        keep, reason = validate_news_item(
            "New partnership", "2024-10-15T10:00:00Z", "published"
        )
        assert keep is True

    def test_accept_time_datetime(self):
        """<time datetime> -> accepted."""
        keep, reason = validate_news_item(
            "Quarterly results", "2024-10-15", "<time datetime>"
        )
        assert keep is True

    def test_accept_article_published_time(self):
        """article:published_time (OpenGraph) -> accepted."""
        keep, reason = validate_news_item(
            "New product launch", "2024-10-15", "article:published_time"
        )
        assert keep is True


# ==========================================================================
# HELPER FUNCTION TESTS
# ==========================================================================

class TestHelpers:
    """Test internal helper functions."""

    def test_distinctive_tokens_strips_suffixes(self):
        tokens = _distinctive_tokens("Nordland Elektro AS")
        assert "nordland" in tokens
        assert "elektro" in tokens
        assert "as" not in tokens

    def test_distinctive_tokens_strips_norge(self):
        tokens = _distinctive_tokens("BigCorp Norge Holding AS")
        assert "bigcorp" in tokens
        assert "norge" not in tokens
        assert "holding" not in tokens
        assert "as" not in tokens

    def test_distinctive_tokens_empty(self):
        assert _distinctive_tokens("") == []
        assert _distinctive_tokens(None) == []

    def test_tokens_overlap_true(self):
        assert _tokens_overlap(["equinor"], "welcome to equinor energy") is True

    def test_tokens_overlap_false(self):
        assert _tokens_overlap(["equinor"], "welcome to statoil") is False

    def test_tokens_overlap_empty(self):
        assert _tokens_overlap([], "any text") is False

    def test_extract_social_slug_linkedin_company(self):
        assert _extract_social_slug("https://www.linkedin.com/company/equinor") == "equinor"

    def test_extract_social_slug_linkedin_in(self):
        assert _extract_social_slug("https://www.linkedin.com/in/john-doe") == "john-doe"

    def test_extract_social_slug_facebook(self):
        assert _extract_social_slug("https://www.facebook.com/equinor") == "equinor"

    def test_extract_social_slug_empty_path(self):
        assert _extract_social_slug("https://www.facebook.com/") is None
