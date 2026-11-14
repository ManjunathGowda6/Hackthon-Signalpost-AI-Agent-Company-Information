#!/usr/bin/env python3
"""
tests/test_ux_features.py

Verifies 100% of the buyer-first UX enhancements across:
- out/index.html
- out/prototype.html
- docs/index.html
- signalpost/web/templates/explorer.html
- signalpost/web/explorer_api.py
"""

from pathlib import Path
import json
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_starter_kit_prototype_dom_integrity():
    for rel_path in ["out/index.html", "out/prototype.html", "docs/index.html"]:
        p = ROOT / rel_path
        assert p.exists(), f"Missing file: {p}"
        html = p.read_text(encoding="utf-8")

        # Starter kit mandatory DOM elements
        required_ids = [
            "profile", "q", "form", "state", "finance", "slice",
            "save-view", "export-view", "count", "list",
            "agent-form", "agent-question", "agent-buttons", "agent-output",
            "workspace-summary", "buyer-pills", "export-csv",
        ]
        for rid in required_ids:
            assert f'id="{rid}"' in html or f"id='{rid}'" in html, f"Missing id={rid} in {rel_path}"

        # Buyer quick-filter pills
        assert "Actively Hiring" in html, f"Missing Actively Hiring in {rel_path}"
        assert "Has Recent News" in html, f"Missing Has Recent News in {rel_path}"
        assert "Profitable &amp; Growing" in html or "Profitable & Growing" in html, f"Missing Profitable & Growing in {rel_path}"
        assert "Verified Website" in html, f"Missing Verified Website in {rel_path}"

        # Buyer card snapshot features
        assert "buyer-summary-box" in html, f"Missing buyer-summary-box in {rel_path}"
        assert "buyer-metrics-grid" in html, f"Missing buyer-metrics-grid in {rel_path}"
        assert "✅ Verified Entity" in html, f"Missing Verified Entity badge in {rel_path}"
        assert "copyBuyerBrief" in html, f"Missing copyBuyerBrief in {rel_path}"
        assert "exportCsv" in html, f"Missing exportCsv in {rel_path}"


def test_explorer_html_buyer_features():
    p = ROOT / "signalpost" / "web" / "templates" / "explorer.html"
    assert p.exists()
    html = p.read_text(encoding="utf-8")

    assert "renderBuyerPills" in html
    assert "selectBuyerPill" in html
    assert "exportCurrentCsv" in html
    assert "copyBuyerBrief" in html
    assert "✅ Verified" in html
    assert "Actively Hiring" in html
    assert "Has Recent News" in html
    assert "Profitable &amp; Growing" in html or "Profitable & Growing" in html


def test_explorer_api_growth_filter():
    from signalpost.web.explorer_api import _build_card, COMPANIES_IX, PROFILES_IX, init_explorer
    init_explorer()
    equinor = COMPANIES_IX.get("923609016")
    assert equinor is not None
    card = _build_card(equinor)
    assert "summary" in card
    assert "yoy_growth" in card
    assert "is_growing" in card
    assert "news_count" in card
    assert "jobs_count" in card
