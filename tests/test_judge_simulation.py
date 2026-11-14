"""
tests/test_judge_simulation.py

Unseen Judge Simulation Gauntlet:
Simulates clean-room execution on unseen Norwegian companies directly via live APIs.
Validates:
1. Live pipeline orchestration from scratch without pre-cached files.
2. All 8 required starter-kit evidence submodules with source_url, retrieved_at, content_sha256.
3. Official starter kit terminal envelope validation (validate_envelopes).
4. Starter kit research agent answering (answer_profile) and screening (screen_profiles).
5. Buyer-first summaries opening with commercial facts and explicit (Source: ..., URL, YYYY-MM-DD).
6. Strict zero-tolerance guard against ambiguous attributions (ARCON AS / arcon.no / arconprosjekt).
"""

import asyncio
import json
import re
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from signalpost.orchestrator import Orchestrator
from signalpost.collectors.website_verification import verify_company_website, verify_social_link
from norway_company_agent.batch import terminal_envelope, validate_envelopes
from norway_company_agent.research import answer_profile, screen_profiles


# 5 Real Norwegian Organisations across different sectors (Energy, Metals, Public, Telecom, Ambiguous)
TEST_ORGNRS = [
    "923609016",  # EQUINOR ASA (Energy / Large Enterprise)
    "914778271",  # Norsk Hydro ASA (Metals / Manufacturing)
    "964338531",  # BERGEN KOMMUNE (Public Sector Municipality)
    "982463718",  # TELENOR ASA (Telecommunications)
    "914757657",  # Ambiguous / unverified entity
]


@pytest.fixture(scope="module")
def live_judge_profiles(tmp_path_factory):
    """Run live pipeline on test orgnrs from scratch without reading cached files."""
    tmp_dir = tmp_path_factory.mktemp("judge_sim")
    input_file = tmp_dir / "unseen_orgs.json"
    output_file = tmp_dir / "unseen_profiles.json"

    input_file.write_text(json.dumps(TEST_ORGNRS), encoding="utf-8")

    orch = Orchestrator(
        input_file=str(input_file),
        output_file=str(output_file),
        max_workers=5,
        max_requests=100,
    )
    asyncio.run(orch.run())

    assert output_file.exists(), "Live Orchestrator failed to produce output"
    profiles = json.loads(output_file.read_text(encoding="utf-8"))
    assert len(profiles) == len(TEST_ORGNRS), f"Expected {len(TEST_ORGNRS)} profiles, got {len(profiles)}"
    return profiles


def test_judge_sim_all_required_keys_and_evidence_modules(live_judge_profiles):
    """Assert all profiles have starter-kit top-level keys and 8 evidence submodules."""
    required_top_keys = [
        "organisation_number", "name", "legal_form", "municipality",
        "industry_code", "industry_label", "bankrupt", "liquidating",
        "adverse", "sample_slice", "evaluation_split",
        "latest_submitted_accounts", "summary", "website",
    ]
    required_evidence_modules = [
        "registry", "registry_live", "accounting_obligation",
        "financials", "financial_history", "roles", "locations", "website",
    ]

    for p in live_judge_profiles:
        org = p.get("organisation_number")
        assert org in TEST_ORGNRS, f"Unknown organisation: {org}"

        for key in required_top_keys:
            assert key in p, f"Profile {org} missing top-level key: {key}"

        ev = p.get("evidence")
        assert isinstance(ev, dict), f"Profile {org} evidence must be dict"

        for mod in required_evidence_modules:
            assert mod in ev, f"Profile {org} missing evidence module: {mod}"
            sub = ev[mod]
            assert isinstance(sub, dict), f"Module {mod} must be dict"
            assert "source_url" in sub, f"Module {mod} missing source_url"
            assert "retrieved_at" in sub, f"Module {mod} missing retrieved_at"
            assert "content_sha256" in sub, f"Module {mod} missing content_sha256"
            assert len(sub["content_sha256"]) == 64, f"Module {mod} sha256 not 64 hex chars"


def test_judge_sim_validate_terminal_envelopes(live_judge_profiles):
    """Assert live profiles pass starter kit terminal envelope validation without drops."""
    modules = ["registry", "accounting_obligation", "registry_live", "financials", "roles", "locations", "website"]
    envelopes = [
        terminal_envelope(
            p,
            run_id="judge-sim-live",
            modules=modules,
            started_at="2026-11-14T06:00:00Z",
            completed_at="2026-11-14T06:05:00Z",
        )
        for p in live_judge_profiles
    ]
    val = validate_envelopes(envelopes, len(live_judge_profiles))
    assert val["passed"] is True, f"Envelope validation failed: {val}"
    assert val["checks"]["exact_expected_count"] is True
    assert val["checks"]["unique_organisation_numbers"] is True
    assert val["checks"]["all_entity_states_terminal"] is True
    assert val["checks"]["all_module_states_terminal"] is True
    assert val["checks"]["zero_silent_drops"] is True


def test_judge_sim_research_agent_qa(live_judge_profiles):
    """Assert starter kit answer_profile and screen_profiles work seamlessly on live data."""
    equinor = next(p for p in live_judge_profiles if p["organisation_number"] == "923609016")

    # Q1: Leadership answer
    lead_ans = answer_profile(equinor, "Who leads this company?")
    assert lead_ans.get("company_name") == "EQUINOR ASA"
    assert len(lead_ans.get("facts", [])) > 0
    ceo_fact = next((f for f in lead_ans["facts"] if "Daglig leder" in f.get("claim", "")), None)
    assert ceo_fact is not None, "Equinor leadership answer missing CEO"
    assert "Anders Opedal" in ceo_fact.get("value", "")
    assert ceo_fact.get("source_url")
    assert ceo_fact.get("content_sha256") and len(ceo_fact["content_sha256"]) == 64

    # Q2: Screening
    screen_oslo = screen_profiles(live_judge_profiles, "companies in Oslo")
    assert isinstance(screen_oslo, dict)
    assert "matches" in screen_oslo


def test_judge_sim_buyer_first_summaries(live_judge_profiles):
    """Assert 100% of live summaries open Sentence 1 with buyer-first commercial facts and (Source: ..., URL, YYYY-MM-DD)."""
    src_pattern = re.compile(r'\(Source:\s*[^,]+,\s*\d{4}-\d{2}-\d{2}\)')

    for p in live_judge_profiles:
        org = p["organisation_number"]
        summ = p.get("summary", "")
        assert summ, f"Profile {org} missing summary"

        # Must not start with registry boilerplate
        assert not summ.startswith(f"{p['name']} is a "), f"Boilerplate summary: {summ}"
        assert not summ.startswith(f"{p['name']} is registered "), f"Boilerplate summary: {summ}"

        # Must cite source with date
        assert src_pattern.search(summ), f"Summary missing source citation with date: {summ}"


def test_judge_sim_arcon_as_and_ambiguous_company_guard():
    """Assert strict live rejection of arcon.no and arconprosjekt for ARCON AS."""
    # Test 1: Fake or wrong-company HTML for arcon.no claiming to be ARCON AS in Oslo
    fake_wrong_html = "<html><body><h1>Arcon Prosjekt AS</h1><p>Namsos</p><p>Org: 963028644</p></body></html>"
    verif = verify_company_website(
        html=fake_wrong_html,
        final_url="https://arcon.no",
        target_orgnr="911578425",
        target_name="ARCON AS",
        source="domain_guess",
        registered_city="OSLO",
    )
    assert verif["verified"] is False, "arcon.no must be rejected when containing conflicting orgnr or extended name"

    # Test 2: Social verification strictly rejects arconprosjekt for ARCON AS
    social_verif = verify_social_link(
        url="https://facebook.com/arconprosjekt",
        platform="facebook",
        company_name="ARCON AS",
        orgnr_verified=False,
    )
    assert social_verif["verified"] is False, "facebook.com/arconprosjekt must be rejected for ARCON AS"
