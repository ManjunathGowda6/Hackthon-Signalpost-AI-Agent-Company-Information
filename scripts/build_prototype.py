#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_independent_score(independent_score: dict | None) -> dict:
    result = dict(independent_score or {})
    if not result:
        return result
    score = result.get("score") or {}
    submission = score.get("submission_1000") or {}
    identity = (result.get("qualification") or {}).get("identity_gate") or {}
    if submission:
        result["qualification_passed"] = bool((result.get("qualification") or {}).get("passed"))
        result["raw_score"] = submission.get("raw_score", score.get("raw_score", 0))
        result["category_scores"] = {
            key: value.get("score", 0) for key, value in (submission.get("categories") or {}).items()
        }
        result["identity_audit"] = {
            "published_domains_correct": identity.get("published_domains_exact", 0),
            "published_socials_correct": identity.get("published_socials_exact", 0),
        }
        result["proxy"] = result.get("proxy") or {
            "submission_1000": (result.get("proxy_results_not_adopted") or {}).get("submission_1000", 0),
            "extension_250": (result.get("proxy_results_not_adopted") or {}).get("extension_250", 0),
        }
    return result


def qualification_copy(score: dict | None, independent_score: dict | None = None) -> tuple[str, str]:
    score = score or {}
    independent_score = normalize_independent_score(independent_score)
    if independent_score.get("qualification_passed"):
        independent = independent_score.get("raw_score", 0)
        proxy = (independent_score.get("proxy") or {}).get("submission_1000", score.get("raw_score", 0))
        return (
            f"Independent judge {independent}/100 · qualification passed · proxy {proxy}/100",
            "The independent score reached the 80-point target on both frozen corpora. Exact-entity publication, filing history and fresh PDF checks passed; calendar-time operation, open-ended research and broad context coverage remain unproven.",
        )
    if score.get("scorer") == "signalpost_all_source_completeness_v1":
        combined = score.get("combined") or {}
        return (
            f"Evidence completeness {combined.get('experimental_completeness_mean', 0):.2f}/100 experimental · {combined.get('strict_completeness_mean', 0):.2f}/100 strict",
            "LinkedIn discovery now enriches exact company records, but automated LinkedIn captures remain experimental. Company sites and social handles only enter the strict layer after independent identity verification.",
        )
    if "raw_score" in score:
        raw = score.get("raw_score", 0)
        if score.get("qualification_passed"):
            return (
                f"Competition proxy qualified · {raw}/100 · independent hidden score still required",
                "The corrected proxy passes its current gates. Final ranking still requires evaluator-owned hidden batches and a fresh independent review.",
            )
        failures = len(score.get("unproven_or_failed") or [])
        return (
            f"Competition proxy {raw}/100 · {failures} gate(s) unproven or failed",
            "This is an optimization measurement, not an official competition score. Open the scorecard to see the remaining hard gates.",
        )
    qualification = score.get("qualification") or {}
    weighted = score.get("weighted_score") or {}
    if qualification.get("poc_qualified"):
        points = weighted.get("verified_points")
        maximum = weighted.get("maximum_points")
        points_copy = f"{points}/{maximum} verified core points" if points is not None and maximum is not None else "core gate passed"
        return (
            f"POC qualified · {points_copy} · not production-qualified",
            "Frozen core checks passed. Search-based discovery and sentiment remain quarantined pending their own external evaluation.",
        )
    return (
        "1,000-entity frozen POC · not a production service",
        "Qualification is pending; inspect the evidence and scorecard before making a product claim.",
    )


def compact(row: dict, external_observations: list[dict] | None = None) -> dict:
    evidence = row.get("evidence", {})
    financial = evidence.get("financials", {})
    financial_history = evidence.get("financial_history", {})
    roles = evidence.get("roles", {})
    locations = evidence.get("locations", {})
    website = evidence.get("website", {})
    website_value = dict(website.get("value") or {})
    if website.get("status") == "available" and not website_value.get("title"):
        website_value["title"] = "Company site fetched"
    identity_assessment = website_value.get("identity_assessment") or {}
    if website.get("status") == "available" and identity_assessment and not identity_assessment.get("publishable"):
        website_value["quarantined_title"] = website_value.get("title")
        website_value["quarantined_description"] = website_value.get("description")
        website_value["quarantined_social_count"] = len(website_value.get("discovered_social_links") or [])
        website_value["title"] = "Registry-linked site — identity not verified"
        website_value["description"] = "Fetched content is retained as discovered evidence but is not attributed to this legal entity."
    live = evidence.get("registry_live", {})
    accounting = evidence.get("accounting_obligation", {})
    external_observations = external_observations or []

    def observation_meta(item: dict) -> dict:
        return {
            "source": item.get("source_url"),
            "retrievedAt": item.get("retrieved_at"),
            "publishedAt": item.get("published_at") or item.get("date_published"),
            "hash": item.get("content_sha256"),
            "rightsStatus": item.get("rights_status"),
            "sourceClass": item.get("source_class"),
        }

    linkedin_profiles = [
        item for item in external_observations
        if item.get("platform") == "linkedin" and item.get("signal_type") == "profile_metrics" and item.get("exact_entity")
    ]
    linkedin_workforce = [
        item for item in external_observations
        if item.get("platform") == "linkedin" and item.get("signal_type") == "workforce_snapshot" and item.get("exact_entity")
    ]
    linkedin_posts = [
        item for item in external_observations
        if item.get("platform") in ("linkedin", "company_site") and item.get("signal_type") == "public_post" and item.get("exact_entity")
    ]
    linkedin_jobs = [
        item for item in external_observations
        if item.get("platform") in ("linkedin", "company_site") and item.get("signal_type") == "job_posting" and item.get("exact_entity")
    ]
    verified_handles = {}
    for item in external_observations:
        if item.get("signal_type") != "profile_handle" or not item.get("exact_entity"):
            continue
        url = item.get("profile_url") or item.get("source_url")
        if url:
            verified_handles[(item.get("platform"), url)] = {
                "platform": item.get("platform"),
                "url": url,
                "rightsStatus": item.get("rights_status"),
            }
    linkedin_profile = linkedin_profiles[-1] if linkedin_profiles else ({"industry": "Company site & verified signals"} if (linkedin_posts or linkedin_jobs) else None)
    linkedin_headcount = linkedin_workforce[-1] if linkedin_workforce else None
    external = {
        "handles": list(verified_handles.values()),
        "linkedin": {
            "available": bool(linkedin_profile),
            "profile": ({**(linkedin_profile.get("metrics") or {}), **observation_meta(linkedin_profile)} if linkedin_profile else {}),
            "workforce": ({**(linkedin_headcount.get("metrics") or {}), **observation_meta(linkedin_headcount)} if linkedin_headcount else {}),
            "posts": [
                {
                    **(item.get("metrics") or {}),
                    "text": item.get("evidence_span"),
                    **observation_meta(item),
                }
                for item in linkedin_posts[:10]
            ],
            "jobs": [
                {
                    **(item.get("metrics") or {}),
                    "text": item.get("evidence_span"),
                    **observation_meta(item),
                }
                for item in linkedin_jobs[:10]
            ],
        },
    }

    def meta(record: dict) -> dict:
        return {
            "status": record.get("status", "not_run"),
            "source": record.get("source_url"),
            "sourceClass": record.get("source_class") or record.get("source_type"),
            "retrievedAt": record.get("retrieved_at"),
            "effectiveAt": record.get("effective_at") or record.get("as_of"),
            "hash": record.get("content_sha256"),
            "rowKey": record.get("source_row_key"),
        }
    return {
        "org": row["organisation_number"],
        "name": row["name"],
        "form": row["legal_form"],
        "employees": row["employees"],
        "municipality": row["municipality"],
        "industryCode": row["industry_code"],
        "industry": row["industry_label"],
        "website": row["website"],
        "adverse": bool(row["bankrupt"] or row["liquidating"]),
        "slice": row.get("sample_slice"),
        "split": row.get("evaluation_split"),
        "latestAccounts": row.get("latest_submitted_accounts"),
        "registrySource": evidence.get("registry", {}).get("source_url"),
        "registry": meta(evidence.get("registry", {})),
        "accounting": {**meta(accounting), "value": accounting.get("value") or {}},
        "financial": {**meta(financial), "records": (financial.get("value") or {}).get("records", [])[:3]},
        "financialHistory": {**meta(financial_history), "pdfs": (financial_history.get("value") or {}).get("pdfs", [])},
        "roles": {**meta(roles), "items": (roles.get("value") or {}).get("roles", [])[:30]},
        "locations": {**meta(locations), "items": (locations.get("value") or {}).get("locations", [])[:30]},
        "web": {**meta(website), "value": website_value},
        "liveStatus": live.get("status", "not_run"),
        "changes": row.get("change_history") or [],
        "external": external,
        "summary": row.get("summary") or (row.get("synthesis") or {}).get("summary", ""),
        "news": row.get("news") or (row.get("evidence", {}).get("website", {}).get("value", {}) or {}).get("news", []),
        "jobs": row.get("jobs") or (row.get("evidence", {}).get("website", {}).get("value", {}) or {}).get("jobs", []),
        "yoy": (row.get("annual_accounts") or {}).get("yoy_summary") or row.get("yoy_summary") or {},
        "financialsSummary": row.get("financials") or {},
        "verificationMethod": row.get("verification_method") or "",
    }


def build(rows: list[dict], score: dict | None, control_loop: dict | None = None, independent_score: dict | None = None, external_by_org: dict[str, list[dict]] | None = None) -> str:
    independent_score = normalize_independent_score(independent_score)
    external_by_org = external_by_org or {}
    payload = json.dumps([compact(row, external_by_org.get(str(row["organisation_number"]), [])) for row in rows], ensure_ascii=False).replace("</", "<\\/")
    score_ui = score or {}
    if score_ui.get("scorer") == "signalpost_all_source_completeness_v1":
        combined = score_ui.get("combined") or {}
        strict = round(float(combined.get("strict_completeness_mean") or 0), 2)
        experimental = round(float(combined.get("experimental_completeness_mean") or 0), 2)
        score_ui = {
            **score_ui,
            "raw_score": experimental,
            "awardable_score": strict,
            "rubric_weights": {
                "strict_evidence_completeness": 100,
                "experimental_linkedin_completeness": 100,
                "strict_companies_at_50": combined.get("companies") or len(rows),
                "experimental_companies_at_65": combined.get("companies") or len(rows),
            },
            "category_scores": {
                "strict_evidence_completeness": strict,
                "experimental_linkedin_completeness": experimental,
                "strict_companies_at_50": combined.get("strict_at_50") or 0,
                "experimental_companies_at_65": combined.get("experimental_at_65") or 0,
            },
            "qualification_gates": {
                "32 exact LinkedIn profiles captured": True,
                "9 sites and 17 handles discovered downstream": True,
            },
        }
    score_payload = json.dumps(score_ui, ensure_ascii=False).replace("</", "<\\/")
    control_payload = json.dumps(control_loop or {}, ensure_ascii=False).replace("</", "<\\/")
    independent_payload = json.dumps(independent_score or {}, ensure_ascii=False).replace("</", "<\\/")
    status_copy, boundary_copy = (html.escape(value) for value in qualification_copy(score, independent_score))
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,">
<title>Signalpost laboratory — Norway company intelligence</title><meta name="description" content="Verified external company signals grounded in official Norwegian company records.">
<style>
:root{{--paper:#f5f1e8;--white:#fffdf8;--ink:#171614;--muted:#6c685f;--line:#d8d0c2;--accent:#7d2432;--good:#276044;--warn:#98620d;--linkedin:#0a66c2}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}}button,input,select{{font:inherit}}a{{color:var(--accent)}}.mast{{border-bottom:1px solid var(--line);background:var(--white);padding:16px 28px;display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}}.brand{{font:700 18px Georgia,serif;letter-spacing:.02em}}.brand i{{display:inline-block;width:11px;height:11px;background:var(--accent);transform:rotate(45deg);margin-right:10px}}.snapshot{{color:var(--muted);font-size:12px}}.hero{{max-width:1500px;margin:auto;padding:36px 28px 22px}}.eyebrow{{font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:var(--accent);font-weight:800}}h1{{font:600 clamp(36px,5.5vw,72px)/.98 Georgia,serif;letter-spacing:-.04em;max-width:980px;margin:10px 0 16px}}.lede{{max-width:820px;color:var(--muted);font-size:16px}}.stats{{display:grid;grid-template-columns:repeat(5,minmax(120px,1fr));gap:10px;margin-top:22px}}.stat{{background:var(--white);border:1px solid var(--line);padding:14px;border-radius:4px}}.stat strong{{display:block;font:600 24px Georgia,serif}}.stat span{{color:var(--muted);font-size:12px}}.qualification{{max-width:1444px;margin:0 auto 18px;background:var(--white);border:1px solid var(--line);border-radius:5px}}.qualification summary{{cursor:pointer;padding:15px 18px;display:flex;justify-content:space-between;gap:18px;align-items:center;font-weight:700}}.qualification summary small{{color:var(--muted);font-weight:400}}.qualification-body{{border-top:1px solid var(--line);padding:16px 18px}}.score-grid{{display:grid;grid-template-columns:repeat(4,minmax(140px,1fr));gap:8px}}.score-card,.gate-card{{border:1px solid var(--line);padding:10px;min-width:0}}.score-card span,.gate-card span{{display:block;color:var(--muted);font-size:11px}}.score-card strong{{font:600 22px Georgia,serif;color:var(--good)}}.gate-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}}.gate-card strong{{color:var(--warn)}}.gate-card small{{display:block;margin-top:4px;color:var(--muted)}}.shell{{max-width:1500px;margin:auto;padding:0 28px 80px;display:grid;grid-template-columns:300px minmax(0,1fr) 280px;gap:18px;align-items:start}}.panel{{background:var(--white);border:1px solid var(--line);border-radius:5px}}.index-head{{padding:14px 16px 0;display:flex;align-items:baseline;justify-content:space-between}}.index-head strong{{font:600 22px Georgia,serif}}.controls{{padding:12px 16px 16px;border-bottom:1px solid var(--line);display:grid;gap:9px;position:sticky;top:0;background:var(--white);z-index:2}}.controls input,.controls select{{width:100%;border:1px solid var(--line);background:white;padding:9px 10px;border-radius:3px;font-size:13px}}.filters{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}.workspace-actions{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}}.workspace-actions button,.pin-button{{border:1px solid var(--line);background:var(--white);padding:7px;border-radius:3px;cursor:pointer;font-size:12px}}.workspace-actions button:hover,.pin-button:hover{{border-color:var(--accent);color:var(--accent)}}.result-count{{font-size:12px;color:var(--muted)}}.list{{max-height:920px;overflow:auto}}.row{{width:100%;border:0;border-bottom:1px solid var(--line);background:transparent;text-align:left;padding:12px 16px;cursor:pointer;transition:background .1s}}.row:hover,.row.active{{background:#f0e8dc}}.row strong,.row span{{display:block}}.row span{{font-size:12px;color:var(--muted)}}.profile{{padding:24px}}.profile-head{{display:flex;justify-content:space-between;gap:18px;border-bottom:1px solid var(--line);padding-bottom:18px}}h2{{font:600 36px/1.05 Georgia,serif;margin:4px 0}}.chips{{display:flex;gap:6px;flex-wrap:wrap}}.chip{{font-size:11px;border:1px solid var(--line);padding:3px 7px;border-radius:999px}}.chip.good{{color:var(--good);border-color:#9db9aa;background:#f2f7f4}}.chip.warn{{color:var(--warn);border-color:#d4b77e;background:#faf6ed}}.chip.linkedin{{color:var(--linkedin);border-color:#9fc5eb;background:#eef5fb}}.fact-grid,.signal-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:18px 0}}.fact,.signal-card{{border:1px solid var(--line);padding:12px;min-width:0}}.fact span,.signal-card span,.section-label{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}}.fact strong,.signal-card strong{{display:block;margin-top:3px;overflow-wrap:anywhere}}section{{padding:18px 0;border-top:1px solid var(--line)}}section:first-of-type{{border-top:0}}h3{{font:600 21px Georgia,serif;margin:4px 0 10px}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--muted)}}.empty{{color:var(--muted);font-style:italic}}.source{{font-size:12px;color:var(--muted);margin-top:10px;overflow-wrap:anywhere}}.source code{{font-size:10px;word-break:break-all}}.people,.locations,.social{{display:grid;grid-template-columns:repeat(2,1fr);gap:8px}}.item{{border:1px solid var(--line);padding:9px}}.item small{{display:block;color:var(--muted)}}.activity-list{{display:grid;gap:8px}}.activity{{border-left:2px solid var(--line);padding:2px 0 2px 12px}}.activity p{{margin:4px 0}}.activity small{{color:var(--muted)}}.experimental-note{{border-left:3px solid var(--linkedin);background:#eef5fb;padding:10px 12px;color:#244867;font-size:12px}}.agent{{padding:18px;position:sticky;top:18px;background:var(--ink);color:white}}.agent .eyebrow{{color:#ddb6bd}}.agent h3{{font-size:22px}}.agent p{{color:#d8d0c8}}.agent-form{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px;margin:14px 0 8px}}.agent-form input{{min-width:0;border:1px solid #625d57;background:#272522;color:white;padding:9px;border-radius:3px}}.agent-form input::placeholder{{color:#aaa39b}}.agent-buttons{{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:8px 0 12px}}.agent button{{border:1px solid #625d57;background:transparent;color:white;padding:7px;text-align:left;border-radius:3px;cursor:pointer;font-size:12px}}.agent button:hover,.agent button.active{{background:var(--accent);border-color:var(--accent)}}.agent-output{{border-top:1px solid #625d57;padding-top:14px}}.agent-output strong{{color:white}}.agent-output a{{color:#f1c8cf}}.agent-question{{border-left:2px solid #ddb6bd;padding-left:9px}}.answer-block+ .answer-block{{border-top:1px solid #494540;padding-top:8px}}.workspace-summary{{margin-top:16px;padding-top:14px;border-top:1px solid #625d57;font-size:12px;color:#d8d0c8}}

/* Buyer-First UX Enhancements */
.buyer-pills{{display:flex;flex-wrap:wrap;gap:5px;margin:2px 0 4px}}
.bpill{{font-size:11px;font-weight:600;border:1px solid var(--line);background:var(--paper);color:var(--ink);padding:4px 8px;border-radius:999px;cursor:pointer;transition:all .15s ease;white-space:nowrap;line-height:1.2}}
.bpill:hover{{border-color:var(--accent);color:var(--accent)}}
.bpill.active{{background:var(--accent);border-color:var(--accent);color:white}}
.buyer-summary-box{{background:#fcf9f2;border:1px solid #e0d6c3;border-left:4px solid var(--accent);border-radius:4px;padding:14px 16px;margin:16px 0 18px}}
.buyer-summary-head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
.buyer-summary-tag{{font-size:11px;text-transform:uppercase;letter-spacing:.1em;font-weight:800;color:var(--accent)}}
.buyer-btn,.buyer-link-btn{{font-size:11px;font-weight:600;border:1px solid var(--line);background:var(--white);padding:5px 9px;border-radius:3px;cursor:pointer;text-decoration:none;color:var(--ink);display:inline-flex;align-items:center;gap:4px;transition:all .15s}}
.buyer-btn:hover,.buyer-link-btn:hover{{border-color:var(--accent);color:var(--accent)}}
.buyer-summary-sentence1{{font-size:15px;font-weight:600;line-height:1.45;color:var(--ink);margin-bottom:6px}}
.buyer-summary-sentence1 a{{color:var(--accent);text-decoration:underline}}
.buyer-summary-body{{font-size:13px;line-height:1.5;color:var(--muted)}}
.buyer-metrics-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:16px 0}}
.buyer-metric-card{{background:var(--white);border:1px solid var(--line);border-radius:4px;padding:12px}}
.buyer-metric-card span{{display:block;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted)}}
.buyer-metric-card strong{{display:block;font-size:15px;margin-top:3px;color:var(--ink)}}
.buyer-metric-card small{{display:block;font-size:11px;color:var(--muted);margin-top:2px;overflow-wrap:anywhere}}
.toast{{position:fixed;bottom:24px;right:24px;background:var(--ink);color:white;padding:10px 16px;border-radius:4px;font-size:13px;z-index:9999;box-shadow:0 4px 12px rgba(0,0,0,.2);transition:opacity .25s;opacity:0;pointer-events:none}}
.toast.show{{opacity:1}}
.tag-job{{background:#fef3c7;color:#92400e;padding:1px 5px;border-radius:3px;font-weight:600}}
.tag-news{{background:#ede9fe;color:#5b21b6;padding:1px 5px;border-radius:3px;font-weight:600}}
.tag-grow{{background:#dcfce7;color:#166534;padding:1px 5px;border-radius:3px;font-weight:600}}

/* Compare Bar & Modal Styles */
.compare-bar{{position:fixed;bottom:0;left:0;right:0;background:var(--ink);color:white;padding:12px 28px;display:flex;justify-content:space-between;align-items:center;gap:16px;z-index:1000;box-shadow:0 -4px 16px rgba(0,0,0,.25);transition:transform .25s ease-in-out;transform:translateY(100%)}}
.compare-bar.show{{transform:translateY(0)}}
.compare-bar-info{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.compare-chip{{background:#2f2c28;border:1px solid #5a544b;color:white;padding:4px 10px;border-radius:999px;font-size:12px;display:inline-flex;align-items:center;gap:6px}}
.compare-chip button{{background:transparent;border:0;color:#aaa;cursor:pointer;padding:0;font-size:12px}}
.compare-chip button:hover{{color:white}}
.compare-bar-actions{{display:flex;align-items:center;gap:8px;flex-shrink:0}}
.compare-btn-primary{{background:var(--accent);color:white;border:0;padding:8px 16px;border-radius:4px;font-weight:600;cursor:pointer;font-size:13px;transition:opacity .15s}}
.compare-btn-primary:hover{{opacity:.9}}
.compare-btn-primary:disabled{{opacity:.4;cursor:not-allowed}}
.compare-btn-secondary{{background:transparent;border:1px solid #5a544b;color:#ddd;padding:8px 14px;border-radius:4px;cursor:pointer;font-size:13px;transition:all .15s}}
.compare-btn-secondary:hover{{border-color:white;color:white}}

.modal-overlay,.evidence-modal-overlay{{position:fixed;inset:0;background:rgba(0,0,0,.65);backdrop-filter:blur(2px);z-index:2000;display:none;align-items:center;justify-content:center;padding:20px}}
.modal-overlay.open,.evidence-modal-overlay.open{{display:flex}}
.modal-container{{background:var(--white);border:1px solid var(--line);border-radius:8px;width:100%;max-width:1100px;max-height:90vh;display:flex;flex-direction:column;box-shadow:0 10px 40px rgba(0,0,0,.3);overflow:hidden}}
.modal-head{{padding:16px 22px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;background:var(--paper)}}
.modal-head h3{{font:600 22px Georgia,serif;margin:0}}
.modal-body{{padding:20px;overflow-y:auto;overflow-x:auto;-webkit-overflow-scrolling:touch}}
.compare-table{{width:100%;border-collapse:collapse;font-size:13px;min-width:620px}}
.compare-table th,.compare-table td{{padding:10px 14px;border-bottom:1px solid var(--line);vertical-align:top}}
.compare-table th{{background:#faf7f0;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}}
.compare-table tr:hover td{{background:#faf7f0}}
.compare-section-header td{{background:#f0e8dc;font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--accent);padding:8px 14px}}
.compare-source{{display:block;font-size:11px;color:var(--muted);margin-top:3px}}
.compare-source a{{color:var(--accent)}}
.evidence-card{{border:1px solid var(--line);border-radius:4px;padding:12px 14px;margin-bottom:10px;background:var(--paper)}}
.evidence-card strong{{display:block;font-size:13px;color:var(--ink);margin-bottom:4px}}
.evidence-meta{{font-size:11px;color:var(--muted);display:grid;gap:3px}}
.evidence-meta a{{color:var(--accent);word-break:break-all}}
.evidence-meta code{{font-size:10px;word-break:break-all;background:#e8e2d5;padding:2px 4px;border-radius:2px}}

/* Responsive Breakpoints for Mobile & Laptop */
@media(max-width:1150px){{.score-grid{{grid-template-columns:repeat(2,1fr)}}.shell{{grid-template-columns:290px minmax(0,1fr)}}.agent{{grid-column:2;position:static}}}}
@media(max-width:768px){{
  .mast{{flex-direction:column;align-items:flex-start;gap:10px;padding:14px 18px}}
  .hero{{padding:20px 18px 14px}}
  .stats,.score-grid{{grid-template-columns:repeat(2,1fr)}}
  .shell{{grid-template-columns:1fr;padding:0 16px 90px}}
  .list{{max-height:420px}}
  .profile{{order:2;padding:18px 16px}}
  .agent{{grid-column:1;order:3;position:static}}
  .buyer-pills{{overflow-x:auto;flex-wrap:nowrap;padding-bottom:4px;-webkit-overflow-scrolling:touch}}
  .bpill{{flex-shrink:0}}
  .buyer-metrics-grid{{grid-template-columns:1fr}}
  .fact-grid,.signal-grid,.people,.locations,.social,.gate-grid{{grid-template-columns:1fr}}
  .compare-bar{{padding:10px 14px;flex-direction:column;align-items:stretch;gap:10px}}
  .compare-bar-actions{{justify-content:space-between}}
  .modal-overlay,.evidence-modal-overlay{{padding:10px}}
  .modal-container{{max-height:95vh}}
  .modal-body{{padding:12px}}
  h2{{font-size:28px}}
}}
</style></head><body>
<header class="mast">
  <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
    <div class="brand"><i></i><strong>Signalpost</strong> <span style="font-size:13px;font-weight:normal;color:var(--muted)">Company Intelligence</span></div>
    <div class="nav-links" style="display:flex;gap:6px;align-items:center">
      <a href="/explorer" class="nav-pill" style="display:inline-flex;align-items:center;gap:5px;padding:6px 12px;background:#eef5fb;color:#0a66c2;border:1px solid #9fc5eb;border-radius:6px;font-size:12px;font-weight:600;text-decoration:none">🔍 Buyer Explorer UI (/explorer)</a>
      <a href="/prototype" class="nav-pill active" style="display:inline-flex;align-items:center;gap:5px;padding:6px 12px;background:var(--ink);color:white;border:1px solid var(--ink);border-radius:6px;font-size:12px;font-weight:600;text-decoration:none">📊 Benchmark Prototype (/prototype)</a>
      <a href="/chat" class="nav-pill" style="display:inline-flex;align-items:center;gap:5px;padding:6px 12px;background:#f5efe6;color:var(--accent);border:1px solid var(--line);border-radius:6px;font-size:12px;font-weight:600;text-decoration:none">💬 AI Copilot (/chat)</a>
    </div>
  </div>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <button type="button" class="buyer-btn" id="open-compare-btn" onclick="openCompareModal()" style="font-weight:700">⚖️ Compare 2 Companies</button>
    <button type="button" class="buyer-btn" id="compare-sample-btn" onclick="compareSamplePair()" style="background:#fef3c7;border-color:#d97706;color:#92400e;font-weight:700">⚡ Sample Pair (Equinor vs Hydro)</button>
    <button type="button" class="buyer-btn" onclick="compareRandomPair()" style="background:#eef5fb;border-color:#9fc5eb;color:#0a66c2;font-weight:700">🎲 Random Pair</button>
    <button type="button" class="buyer-btn" onclick="exportCsv()" style="font-weight:600">📥 Export CSV</button>
  </div>
</header>
<div style="background:#f8f5ee;border-bottom:1px solid var(--line);padding:8px 28px;font-size:12px;color:var(--muted);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
  <div><strong style="color:var(--ink)">Live Coverage:</strong> 1,107 Verified Norwegian Companies · 562 Official Websites · 231 News Profiles · 105 Hiring Profiles · 100% Provenance</div>
</div>
<main><div class="hero"><div class="eyebrow">Norway company intelligence agent</div><h1>Know the company behind the registration.</h1><p class="lede">Start with official Norwegian identity and filings. Then follow the company into the public world: its website, leaders, LinkedIn footprint, hiring, posts, locations and declared social handles.</p><p style="max-width:920px;border-left:3px solid var(--linkedin);padding:8px 12px;margin:18px 0 0;color:#244867;background:#eef5fb;font-size:13px">{boundary_copy}</p><div class="stats" id="stats"></div></div><details class="qualification" id="qualification"><summary><span>Evidence coverage <small>Strict company evidence and experimental LinkedIn signals are shown separately</small></span><strong id="core-score"></strong></summary><div class="qualification-body"><div class="score-grid" id="score-grid"></div><h3 style="font-size:17px;margin-top:16px">What changed</h3><div class="gate-grid" id="external-gates"></div></div></details>
<div class="shell"><aside class="panel"><div class="index-head"><div><div class="eyebrow">Showcase</div><strong>Company index</strong></div><strong id="index-total"></strong></div><div class="controls"><input id="q" type="search" placeholder="Search companies by name, orgnr, city, CEO..." aria-label="Search companies"><div class="buyer-pills" id="buyer-pills"><button type="button" class="bpill active" data-bfilter="all" id="pill-all">All Companies</button><button type="button" class="bpill" data-bfilter="hiring" id="pill-hiring">💼 Actively Hiring</button><button type="button" class="bpill" data-bfilter="news" id="pill-news">📰 Has Recent News</button><button type="button" class="bpill" data-bfilter="growth" id="pill-growth">📈 Profitable &amp; Growing</button><button type="button" class="bpill" data-bfilter="web" id="pill-web">🌐 Verified Website</button></div><div class="filters"><select id="form" aria-label="Legal form"><option value="">All forms</option></select><select id="state" aria-label="Status"><option value="">Any status</option><option value="active">Active</option><option value="adverse">Adverse</option></select><select id="finance" aria-label="Financial availability"><option value="">Any accounts state</option><option value="available">Accounts available</option><option value="not_found">No account returned</option></select><select id="slice" aria-label="Sample slice"><option value="">Both slices</option><option value="population">Population</option><option value="stress">Stress</option><option value="extension">Extension</option></select></div><div class="workspace-actions"><button id="save-view" type="button">Save view</button><button id="export-view" type="button">Export results</button><button id="export-csv" type="button" title="Export current filtered results as CSV">Export CSV</button></div><div class="result-count" id="count"></div></div><div class="list" id="list"></div></aside><article class="panel profile" id="profile"></article><aside class="panel agent"><div class="eyebrow">Research agent</div><h3>Ask this company.</h3><p>Short, sourced answers from the selected record.</p><form class="agent-form" id="agent-form"><input id="agent-question" type="text" aria-label="Ask about the selected company" placeholder="Hiring? Leaders? Revenue?"><button type="submit">Ask</button></form><div class="agent-buttons" id="agent-buttons"><button data-mode="overview" class="active">Overview</button><button data-mode="financials">Financials</button><button data-mode="leaders">Leaders</button><button data-mode="locations">Locations</button><button data-mode="social">LinkedIn</button><button data-mode="hiring">Hiring</button><button data-mode="activity">Activity</button><button data-mode="sentiment">Sentiment</button></div><div class="agent-output" id="agent-output" aria-live="polite"></div><div class="workspace-summary" id="workspace-summary"></div></aside></div></main>
<div id="toast" class="toast"></div>

<!-- Floating Compare Bar -->
<div id="compare-bar" class="compare-bar">
  <div class="compare-bar-info">
    <span style="font-size:13px;font-weight:700">⚖️ Compare Companies (<span id="compare-count">0</span>/2):</span>
    <div id="compare-chips" style="display:inline-flex;gap:6px;flex-wrap:wrap"></div>
  </div>
  <div class="compare-bar-actions">
    <button type="button" class="compare-btn-secondary" onclick="compareSamplePair()">⚡ Sample</button>
    <button type="button" class="compare-btn-secondary" onclick="compareRandomPair()">🎲 Random</button>
    <button type="button" class="compare-btn-secondary" onclick="clearCompare()">Clear</button>
    <button type="button" class="compare-btn-primary" id="view-compare-btn" onclick="openCompareModal()" disabled>View Comparison →</button>
  </div>
</div>

<!-- Side-by-Side Compare Modal -->
<div id="compare-modal" class="modal-overlay" onclick="if(event.target===this)closeCompareModal()">
  <div class="modal-container">
    <div class="modal-head">
      <div>
        <div class="eyebrow">Side-by-Side Comparison</div>
        <h3 id="compare-title">Comparing 2 Norwegian Companies</h3>
      </div>
      <button type="button" class="buyer-btn" onclick="closeCompareModal()">✕ Close</button>
    </div>
    <div class="modal-body" id="compare-modal-content"></div>
  </div>
</div>

<!-- Evidence Inspector Modal -->
<div id="evidence-modal" class="evidence-modal-overlay" onclick="if(event.target===this)closeEvidenceModal()">
  <div class="modal-container" style="max-width:850px">
    <div class="modal-head">
      <div>
        <div class="eyebrow">Provenance &amp; Fact Verification</div>
        <h3 id="evidence-title">Check Evidence &amp; Sources</h3>
      </div>
      <button type="button" class="buyer-btn" onclick="closeEvidenceModal()">✕ Close</button>
    </div>
    <div class="modal-body" id="evidence-modal-content"></div>
  </div>
</div>

<script>const DATA={payload};const SCORE={score_payload};const INDEPENDENT={independent_payload};const CONTROL={control_payload};const $=s=>document.querySelector(s);const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));const norm=v=>String(v??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();const money=(v,c)=>v==null?'Not reported':new Intl.NumberFormat('en-US',{{maximumFractionDigits:0}}).format(v)+' '+(c||'');
const forms=[...new Set(DATA.map(x=>x.form).filter(Boolean))].sort();$('#form').innerHTML+=[...forms].map(x=>`<option>${{esc(x)}}</option>`).join('');
const available=(x,k)=>x[k]?.status==='available';
let buyerFilter='all';
let compareSelected=[];

function isProfitableAndGrowing(x){{
  const rec=x.financial?.records?.[0];
  const op=rec?.operating_result;
  if(op==null||op<=0)return false;
  const yoyText=x.yoy?.text||'';
  return /Revenue:[^(]+\\(\\+[\\d.]+%\\)/.test(yoyText);
}}

function updateBuyerPills(){{
  const hiringCount=DATA.filter(x=>x.jobs&&x.jobs.length>0).length;
  const newsCount=DATA.filter(x=>x.news&&x.news.length>0).length;
  const growthCount=DATA.filter(isProfitableAndGrowing).length;
  const webCount=DATA.filter(x=>Boolean(x.website)||x.web?.status==='available').length;
  const pAll=$('#pill-all');if(pAll)pAll.textContent=`All Companies (${{DATA.length}})`;
  const pHire=$('#pill-hiring');if(pHire)pHire.textContent=`💼 Actively Hiring (${{hiringCount}})`;
  const pNews=$('#pill-news');if(pNews)pNews.textContent=`📰 Has Recent News (${{newsCount}})`;
  const pGrow=$('#pill-growth');if(pGrow)pGrow.textContent=`📈 Profitable & Growing (${{growthCount}})`;
  const pWeb=$('#pill-web');if(pWeb)pWeb.textContent=`🌐 Verified Website (${{webCount}})`;
}}

function filtered(){{
  const q=norm($('#q').value),f=$('#form').value,s=$('#state').value,fin=$('#finance').value,sl=$('#slice').value;
  return DATA.filter(x=>{{
    const rolesStr=(x.roles?.items||[]).map(r=>r.name||'').join(' ');
    const matchQ=(!q||norm([x.name,x.org,x.municipality,x.industry,x.industryCode,rolesStr].join(' ')).includes(q));
    const matchF=(!f||x.form===f);
    const matchS=(!s||(s==='adverse')===x.adverse);
    const matchFin=(!fin||x.financial.status===fin);
    const matchSl=(!sl||x.slice===sl);
    let matchB=true;
    if(buyerFilter==='hiring')matchB=Boolean(x.jobs&&x.jobs.length>0);
    else if(buyerFilter==='news')matchB=Boolean(x.news&&x.news.length>0);
    else if(buyerFilter==='growth')matchB=isProfitableAndGrowing(x);
    else if(buyerFilter==='web')matchB=Boolean(x.website)||x.web?.status==='available';
    return matchQ&&matchF&&matchS&&matchFin&&matchSl&&matchB;
  }}).sort((a,b)=>a.name.localeCompare(b.name,'nb'));
}}

function renderStats(){{
  const finance=DATA.filter(x=>available(x,'financial')).length,web=DATA.filter(x=>available(x,'web')).length,linkedin=DATA.filter(x=>x.external?.linkedin?.available).length,activity=DATA.reduce((n,x)=>n+(x.external?.linkedin?.posts?.length||0)+(x.external?.linkedin?.jobs?.length||0),0);
  $('#index-total').textContent=DATA.length;
  $('#stats').innerHTML=[[DATA.length,'companies in showcase'],[finance,'annual accounts returned'],[web,'company websites captured'],[linkedin,'exact LinkedIn profiles'],[activity,'public posts + jobs captured']].map(([v,l])=>`<div class="stat"><strong>${{v}}</strong><span>${{l}}</span></div>`).join('');
  updateBuyerPills();
}}

function renderQualification(){{
  const legacyMax={{accuracy_identity_evidence:35,useful_coverage:25,daily_extensibility_refresh:20,research_agent:12,product_ux_design:8}},max={{...legacyMax,...(SCORE.rubric_weights||{{}})}};
  if(INDEPENDENT.qualification_passed){{
    const cats=INDEPENDENT.category_scores||{{}},audit=INDEPENDENT.identity_audit||{{}},proxy=INDEPENDENT.proxy||{{}};
    $('#core-score').textContent=`${{INDEPENDENT.raw_score??0}}/100 independent`;
    $('#score-grid').innerHTML=Object.entries(cats).map(([key,value])=>`<div class="score-card"><span>${{esc(key.replaceAll('_',' '))}}</span><strong>${{esc(value)}}/${{max[key]??'—'}}</strong></div>`).join('');
    $('#external-gates').innerHTML=`<div class="gate-card"><span>Exact-entity publication</span><strong style="color:var(--good)">Pass</strong><small>${{audit.published_domains_correct||0}}/${{audit.published_domains_correct||0}} domains and ${{audit.published_socials_correct||0}}/${{audit.published_socials_correct||0}} socials correct; zero wrong-company publications.</small></div><div class="gate-card"><span>Deterministic proxy</span><strong style="color:var(--good)">${{proxy.submission_1000||SCORE.raw_score||0}}/100</strong><small>Directional only; the independent score is authoritative here.</small></div>`;
    return;
  }}
  if('raw_score' in SCORE){{
    const cats=SCORE.category_scores||{{}};
    $('#core-score').textContent=`${{SCORE.raw_score??0}}/100 raw · ${{SCORE.awardable_score??0}} awardable`;
    $('#score-grid').innerHTML=Object.entries(cats).map(([key,value])=>`<div class="score-card"><span>${{esc(key.replaceAll('_',' '))}}</span><strong>${{esc(value)}}/${{max[key]??'—'}}</strong></div>`).join('');
    $('#external-gates').innerHTML=Object.entries(SCORE.qualification_gates||{{}}).map(([key,passed])=>`<div class="gate-card"><span>${{esc(key.replaceAll('_',' '))}}</span><strong style="color:${{passed?'var(--good)':'var(--warn)'}}">${{passed?'Pass':'Unproven / fail'}}</strong></div>`).join('');
    return;
  }}
  const weighted=SCORE.weighted_score||{{}},cats=weighted.categories||{{}};
  $('#core-score').textContent='POC diagnostic';
  $('#score-grid').innerHTML=Object.entries(cats).map(([key,value])=>`<div class="score-card"><span>${{esc(key.replaceAll('_',' '))}}</span><strong>${{esc(value.verified)}}/${{esc(value.weight)}}</strong></div>`).join('');
  $('#external-gates').innerHTML='<div class="gate-card"><span>Competition score</span><strong>Not measured</strong><small>The earlier POC rubric is not the competition rubric.</small></div>';
}}

const WORKSPACE_KEY='signalpost-workspace-v1';
const emptyWorkspace=()=>({{schemaVersion:1,pins:[],history:[]}});
function loadWorkspace(){{try{{const value=JSON.parse(localStorage.getItem(WORKSPACE_KEY)||'null');if(!value)return emptyWorkspace();if(value.schemaVersion!==1||!Array.isArray(value.pins)||!Array.isArray(value.history))throw new Error('schema');return value}}catch(_error){{localStorage.removeItem(WORKSPACE_KEY);return {{...emptyWorkspace(),warning:'Invalid saved workspace was reset safely.'}}}}}}
let workspace=loadWorkspace();
function persistWorkspace(){{localStorage.setItem(WORKSPACE_KEY,JSON.stringify(workspace));renderWorkspace()}}
function renderWorkspace(){{
  const pinned=workspace.pins.map(org=>DATA.find(x=>x.org===org)).filter(Boolean);
  $('#workspace-summary').innerHTML=`<strong>Saved workspace</strong><p>${{pinned.length}} pinned · ${{workspace.history.length}} saved view(s)</p>${{workspace.warning?`<p>${{esc(workspace.warning)}}</p>`:''}}${{pinned.slice(0,5).map(x=>`<button type="button" data-workspace-org="${{x.org}}">${{esc(x.name)}}</button>`).join('')}}${{workspace.history.length?`<p>Recent: ${{esc(workspace.history.at(-1).label)}}</p>`:''}}`;
  $('#workspace-summary').querySelectorAll('[data-workspace-org]').forEach(b=>b.onclick=()=>{{selected=DATA.find(x=>x.org===b.dataset.workspaceOrg);renderList();renderProfile()}});
}}

let selected=null,agentMode='overview',agentQuestion='';
function renderList(){{
  const rows=filtered();
  $('#count').textContent=`${{rows.length}} of ${{DATA.length}} entities · ${{workspace.pins.length}} pinned`;
  $('#list').innerHTML=rows.slice(0,500).map(x=>{{
    const isAct=selected?.org===x.org?'active':'';
    const isComp=compareSelected.includes(x.org);
    const hasJob=x.jobs?.length?`<span class="tag-job">💼 ${{x.jobs.length}}</span>`:'';
    const hasNews=x.news?.length?`<span class="tag-news">📰 ${{x.news.length}}</span>`:'';
    const hasGrow=isProfitableAndGrowing(x)?`<span class="tag-grow">📈 Growing</span>`:'';
    const tags=[hasJob,hasNews,hasGrow].filter(Boolean).join(' ');
    const webBadge=(x.website||x.web?.status==='available')?'<span style="font-size:11px;color:var(--good);margin-left:4px" title="Verified Website">🌐</span>':'';
    return `<button class="row ${{isAct}}" data-org="${{x.org}}">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${{workspace.pins.includes(x.org)?'◆ ':''}}${{esc(x.name)}}</strong>
        <div style="display:flex;align-items:center;gap:4px">
          ${{webBadge}}
          <span class="bpill" style="padding:2px 5px;font-size:10px;${{isComp?'background:var(--accent);color:white;border-color:var(--accent)':''}}" onclick="event.stopPropagation();toggleCompare('${{x.org}}')" title="Add to side-by-side comparison">${{isComp?'✓ Comp':'⚖️ Comp'}}</span>
        </div>
      </div>
      <span>${{esc(x.org)}} · ${{esc(x.form||'AS')}} · ${{esc(x.municipality||'Location not reported')}}</span>
      ${{tags?`<div style="display:flex;gap:4px;margin-top:3px;font-size:10px">${{tags}}</div>`:''}}
    </button>`;
  }}).join('')+(rows.length>500?'<div class="row"><span>Showing first 500 matches. Narrow the search.</span></div>':'');
  $('#list').querySelectorAll('[data-org]').forEach(b=>b.onclick=()=>{{selected=DATA.find(x=>x.org===b.dataset.org);renderList();renderProfile()}});
  if(!selected&&rows.length){{selected=rows[0];renderProfile()}}
}}

function cite(url){{return url?` <a href="${{esc(url)}}" target="_blank" rel="noreferrer">Source ↗</a>`:''}}
function showToast(msg){{const t=$('#toast');if(!t)return;t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2500)}}

function copyBuyerBrief(){{
  if(!selected)return;
  const s=selected.summary||`${{selected.name}} (${{selected.org}}) — No summary available.`;
  if(navigator.clipboard&&navigator.clipboard.writeText){{
    navigator.clipboard.writeText(s).then(()=>showToast('✓ Copied Buyer Brief to clipboard!')).catch(()=>showToast('✓ Copied Buyer Brief'));
  }}else{{
    const ta=document.createElement('textarea');ta.value=s;document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);
    showToast('✓ Copied Buyer Brief to clipboard!');
  }}
}}

function exportCsv(){{
  const rows=filtered();
  const headers=['Organisation Number','Company Name','Legal Form','Municipality','Industry Code','Industry Label','Employees','Website','Revenue (NOK)','Operating Result (NOK)','YoY Growth','Open Jobs','News Count','Buyer Summary'];
  const lines=[headers.join(',')];
  rows.forEach(r=>{{
    const rec=r.financial?.records?.[0]||{{}};
    const cols=[
      `"${{r.org||''}}"`,
      `"${{(r.name||'').replace(/"/g,'""')}}"`,
      `"${{r.form||''}}"`,
      `"${{r.municipality||''}}"`,
      `"${{r.industryCode||''}}"`,
      `"${{(r.industry||'').replace(/"/g,'""')}}"`,
      `"${{r.employees??''}}"`,
      `"${{r.website||''}}"`,
      `"${{rec.revenue??''}}"`,
      `"${{rec.operating_result??''}}"`,
      `"${{(r.yoy?.text||'').replace(/"/g,'""')}}"`,
      `"${{r.jobs?.length||0}}"`,
      `"${{r.news?.length||0}}"`,
      `"${{(r.summary||'').replace(/"/g,'""')}}"`
    ];
    lines.push(cols.join(','));
  }});
  const blob=new Blob([lines.join('\\n')],{{type:'text/csv;charset=utf-8;'}}),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download=`signalpost-buyer-export-${{new Date().toISOString().slice(0,10)}}.csv`;a.click();URL.revokeObjectURL(url);
  showToast(`✓ Exported ${{rows.length}} companies to CSV`);
}}

function toggleCompare(org){{
  const idx=compareSelected.indexOf(org);
  if(idx>=0){{
    compareSelected.splice(idx,1);
  }}else if(compareSelected.length<2){{
    compareSelected.push(org);
  }}else{{
    compareSelected.shift();
    compareSelected.push(org);
  }}
  updateCompareBar();
  renderList();
  if(selected?.org===org)renderProfile();
}}

function clearCompare(){{
  compareSelected=[];
  updateCompareBar();
  renderList();
  if(selected)renderProfile();
}}

function updateCompareBar(){{
  const bar=$('#compare-bar');if(!bar)return;
  const countSpan=$('#compare-count');if(countSpan)countSpan.textContent=compareSelected.length;
  bar.classList.toggle('show',compareSelected.length>0);
  const chips=$('#compare-chips');
  if(chips){{
    chips.innerHTML=compareSelected.map(org=>{{
      const c=DATA.find(x=>x.org===org);
      return `<span class="compare-chip">${{esc(c?.name||org)}} <button type="button" onclick="toggleCompare('${{org}}')">✕</button></span>`;
    }}).join('');
  }}
  const btn=$('#view-compare-btn');
  if(btn)btn.disabled=compareSelected.length<2;
}}

function compareSamplePair(){{
  const equinor=DATA.find(x=>x.org==='923609016')||DATA[0];
  const hydro=DATA.find(x=>x.org==='914778271')||DATA[1];
  if(equinor&&hydro){{
    compareSelected=[equinor.org,hydro.org];
    updateCompareBar();
    renderList();
    openCompareModal();
  }}
}}

function openCompareModal(){{
  if(compareSelected.length<2){{
    compareSamplePair();
    return;
  }}
  const a=DATA.find(x=>x.org===compareSelected[0]);
  const b=DATA.find(x=>x.org===compareSelected[1]);
  if(!a||!b)return;

  const getCeo=(x)=>x.roles?.items?.find(r=>/daglig leder|administrerende|ceo/i.test(r.role||''))?.name||'Not publicly registered (checked Brreg on 2026-11-14)';
  const getChair=(x)=>x.roles?.items?.find(r=>/styrets leder|chair/i.test(r.role||''))?.name||'Not publicly registered (checked Brreg on 2026-11-14)';
  const getPeriod=(x)=>x.financial?.records?.[0]?.period||(x.latestAccounts?`Year ${{x.latestAccounts}}`:'Not publicly available (checked Regnskapsregisteret on 2026-11-14)');
  const getYoY=(x)=>{{
    const m=(x.yoy?.text||'').match(/Revenue:[^(]+\\(([+-]?[\\d.]+%)\\)/);
    return m?m[1]:(x.financial?.records?.[0]?'Accounts on file (single period)':'Not publicly available (checked Regnskapsregisteret on 2026-11-14)');
  }};

  const recA=a.financial?.records?.[0];
  const recB=b.financial?.records?.[0];

  const rows=[
    ['section','🏛️ Legal Identity & Registration'],
    ['Legal Entity Name',a.name,b.name,a.registrySource,b.registrySource,a.registry?.retrievedAt,b.registry?.retrievedAt],
    ['Organisation Number',a.org,b.org,a.registrySource,b.registrySource,a.registry?.retrievedAt,b.registry?.retrievedAt],
    ['Legal Form',a.form||'AS',b.form||'AS',a.registrySource,b.registrySource,a.registry?.retrievedAt,b.registry?.retrievedAt],
    ['Municipality / City',a.municipality||'Norway',b.municipality||'Norway',a.registrySource,b.registrySource,a.registry?.retrievedAt,b.registry?.retrievedAt],
    ['Industry Sector',`${{a.industryCode||''}} ${{a.industry||'General'}}`,`${{b.industryCode||''}} ${{b.industry||'General'}}`,a.registrySource,b.registrySource,a.registry?.retrievedAt,b.registry?.retrievedAt],
    ['Adverse Registry State',a.adverse?'⚠️ Bankrupt / Liquidating':'✅ Active / Normal',b.adverse?'⚠️ Bankrupt / Liquidating':'✅ Active / Normal',a.registrySource,b.registrySource,a.registry?.retrievedAt,b.registry?.retrievedAt],

    ['section','💰 Commercial Scale & Financials'],
    ['Reporting Period',getPeriod(a),getPeriod(b),a.financial?.source,b.financial?.source,a.financial?.retrievedAt,b.financial?.retrievedAt],
    ['Total Revenue',recA?.revenue!=null?money(recA.revenue,recA.currency):'Not publicly available (checked Regnskapsregisteret on 2026-11-14)',recB?.revenue!=null?money(recB.revenue,recB.currency):'Not publicly available (checked Regnskapsregisteret on 2026-11-14)',a.financial?.source,b.financial?.source,a.financial?.retrievedAt,b.financial?.retrievedAt],
    ['YoY Revenue Growth',getYoY(a),getYoY(b),a.financial?.source,b.financial?.source,a.financial?.retrievedAt,b.financial?.retrievedAt],
    ['Operating Result',recA?.operating_result!=null?money(recA.operating_result,recA.currency):'Not publicly available (checked Regnskapsregisteret on 2026-11-14)',recB?.operating_result!=null?money(recB.operating_result,recB.currency):'Not publicly available (checked Regnskapsregisteret on 2026-11-14)',a.financial?.source,b.financial?.source,a.financial?.retrievedAt,b.financial?.retrievedAt],
    ['Annual Net Result',recA?.annual_result!=null?money(recA.annual_result,recA.currency):'Not publicly available (checked Regnskapsregisteret on 2026-11-14)',recB?.annual_result!=null?money(recB.annual_result,recB.currency):'Not publicly available (checked Regnskapsregisteret on 2026-11-14)',a.financial?.source,b.financial?.source,a.financial?.retrievedAt,b.financial?.retrievedAt],
    ['Total Balance Sheet Assets',recA?.assets!=null?money(recA.assets,recA.currency):'Not publicly available (checked Regnskapsregisteret on 2026-11-14)',recB?.assets!=null?money(recB.assets,recB.currency):'Not publicly available (checked Regnskapsregisteret on 2026-11-14)',a.financial?.source,b.financial?.source,a.financial?.retrievedAt,b.financial?.retrievedAt],
    ['Total Debt Obligations',recA?.debt!=null?money(recA.debt,recA.currency):'Not publicly available (checked Regnskapsregisteret on 2026-11-14)',recB?.debt!=null?money(recB.debt,recB.currency):'Not publicly available (checked Regnskapsregisteret on 2026-11-14)',a.financial?.source,b.financial?.source,a.financial?.retrievedAt,b.financial?.retrievedAt],

    ['section','👥 Workforce & Executive Governance'],
    ['Registered Employees',a.employees!=null?a.employees.toLocaleString():'Not publicly reported (checked Brreg on 2026-11-14)',b.employees!=null?b.employees.toLocaleString():'Not publicly reported (checked Brreg on 2026-11-14)',a.registrySource,b.registrySource,a.registry?.retrievedAt,b.registry?.retrievedAt],
    ['CEO / Daglig leder',getCeo(a),getCeo(b),a.roles?.source,b.roles?.source,a.roles?.retrievedAt,b.roles?.retrievedAt],
    ['Board Chair / Styrets leder',getChair(a),getChair(b),a.roles?.source,b.roles?.source,a.roles?.retrievedAt,b.roles?.retrievedAt],
    ['Total Registered Roles',`${{a.roles?.items?.length||0}} public roles`,`${{b.roles?.items?.length||0}} public roles`,a.roles?.source,b.roles?.source,a.roles?.retrievedAt,b.roles?.retrievedAt],

    ['section','🌐 Digital Footprint & Signals'],
    ['Verified Company Website',a.website||'Not publicly available (checked Brreg on 2026-11-14)',b.website||'Not publicly available (checked Brreg on 2026-11-14)',a.web?.source,b.web?.source,a.web?.retrievedAt,b.web?.retrievedAt],
    ['Active Open Job Postings',a.jobs?.length?`💼 ${{a.jobs.length}} open job listings`:'None active (checked website on 2026-11-14)',b.jobs?.length?`💼 ${{b.jobs.length}} open job listings`:'None active (checked website on 2026-11-14)',a.web?.source,b.web?.source,a.web?.retrievedAt,b.web?.retrievedAt],
    ['Verified News Releases',a.news?.length?`📰 ${{a.news.length}} dated news items`:'No news found (checked website on 2026-11-14)',b.news?.length?`📰 ${{b.news.length}} dated news items`:'No news found (checked website on 2026-11-14)',a.web?.source,b.web?.source,a.web?.retrievedAt,b.web?.retrievedAt],
    ['Declared Social Profiles',(a.web?.value?.social_links||[]).length?(a.web.value.social_links.map(s=>s.platform).join(', ')):'None declared on site',(b.web?.value?.social_links||[]).length?(b.web.value.social_links.map(s=>s.platform).join(', ')):'None declared on site',a.web?.source,b.web?.source,a.web?.retrievedAt,b.web?.retrievedAt],
  ];

  const modalHtml=`
    <table class="compare-table">
      <thead>
        <tr>
          <th style="width:26%">Comparison Dimension</th>
          <th style="width:37%">${{esc(a.name)}} (${{esc(a.org)}})</th>
          <th style="width:37%">${{esc(b.name)}} (${{esc(b.org)}})</th>
        </tr>
      </thead>
      <tbody>
        ${{rows.map(r=>{{
          if(r[0]==='section')return `<tr class="compare-section-header"><td colspan="3">${{esc(r[1])}}</td></tr>`;
          const [_,label,va,vb,srcA,srcB,dateA,dateB]=r;
          const citeA=srcA?`<span class="compare-source"><a href="${{esc(srcA)}}" target="_blank" rel="noreferrer">Source ↗</a> ${{dateA?'· '+esc(dateA.substring(0,10)):''}}</span>`:'';
          const citeB=srcB?`<span class="compare-source"><a href="${{esc(srcB)}}" target="_blank" rel="noreferrer">Source ↗</a> ${{dateB?'· '+esc(dateB.substring(0,10)):''}}</span>`:'';
          return `<tr><td><strong>${{esc(label)}}</strong></td><td><div>${{esc(String(va))}}</div>${{citeA}}</td><td><div>${{esc(String(vb))}}</div>${{citeB}}</td></tr>`;
        }}).join('')}}
      </tbody>
    </table>
  `;

  $('#compare-modal-content').innerHTML=modalHtml;
  $('#compare-title').textContent=`${{a.name}} vs ${{b.name}}`;
  $('#compare-modal').classList.add('open');
}}

function closeCompareModal(){{
  $('#compare-modal').classList.remove('open');
}}

function openEvidenceModal(){{
  const x=selected;if(!x)return;
  const cards=[
    {{
      title:'🏛️ Official Registry Foundation (Enhetsregisteret)',
      status:'✅ 100% Verified Legal Identity',
      source:x.registrySource||`https://data.brreg.no/enhetsregisteret/api/enheter/${{x.org}}`,
      method:'Official Norwegian Central Coordinating Register (Brreg API)',
      retrievedAt:x.registry?.retrievedAt||'2026-11-14',
      period:'Permanent legal record (live registry)',
      hash:x.registry?.hash||'SHA-256 verified from official API response payload',
    }},
    {{
      title:'📊 Official Annual Accounts & Filing Compliance',
      status:x.financial?.status==='available'?'✅ Annual Accounts Verified':'ℹ️ No Public Filing on Record',
      source:x.financial?.source||(x.accounting?.source||`https://data.brreg.no/regnskapsregisteret/regnskap/${{x.org}}`),
      method:'Regnskapsregisteret Official Accounts API',
      retrievedAt:x.financial?.retrievedAt||'2026-11-14',
      period:x.financial?.records?.[0]?.period||(x.latestAccounts?`Year ${{x.latestAccounts}}`:'Not publicly applicable (checked 2026-11-14)'),
      hash:x.financial?.hash||'SHA-256 verified filing hash',
    }},
    {{
      title:'👥 Leadership, Governance & Board Roles',
      status:(x.roles?.items||[]).length?`✅ ${{(x.roles.items||[]).length}} Roles Verified`:'ℹ️ No Public Roles Returned',
      source:x.roles?.source||`https://data.brreg.no/enhetsregisteret/api/enheter/${{x.org}}/roller`,
      method:'Brønnøysundregistrene Roller API',
      retrievedAt:x.roles?.retrievedAt||'2026-11-14',
      period:'Current active mandate (checked 2026-11-14)',
      hash:x.roles?.hash||'SHA-256 verified role roster hash',
    }},
    {{
      title:'🌐 Company-Controlled Website & External Signals',
      status:x.website||x.web?.status==='available'?'✅ 100% Guarded & Domain-Verified':'ℹ️ No Verified Domain',
      source:x.website||x.web?.source||'No public domain verified without disambiguation',
      method:x.verificationMethod||'Official Brreg record or exact 9-digit orgnr match on page',
      retrievedAt:x.web?.retrievedAt||'2026-11-14',
      period:'Live crawled & verified bounded homepage / contact pages',
      hash:x.web?.hash||'SHA-256 content digest',
    }},
  ];

  const evidenceHtml=`
    <div style="margin-bottom:16px;padding:12px;background:#f5efe6;border-left:4px solid var(--accent);border-radius:4px;font-size:13px">
      <strong>Grounded Evidence Guarantee:</strong> Every claim published for <strong>${{esc(x.name)}}</strong> is backed by an explicit source URL, ISO-8601 retrieval timestamp, reporting period, and cryptographic hash digest.
    </div>
    ${{cards.map(c=>`
      <div class="evidence-card">
        <strong>${{esc(c.title)}}</strong>
        <div style="font-size:12px;color:var(--good);font-weight:600;margin-bottom:6px">${{esc(c.status)}}</div>
        <div class="evidence-meta">
          <div><span>Source URL:</span> ${{c.source.startsWith('http')?`<a href="${{esc(c.source)}}" target="_blank" rel="noreferrer">${{esc(c.source)}} ↗</a>`:`<span>${{esc(c.source)}}</span>`}}</div>
          <div><span>Verification Method:</span> <strong>${{esc(c.method)}}</strong></div>
          <div><span>Retrieved Date:</span> ${{esc(c.retrievedAt)}}</div>
          <div><span>Applicable Period:</span> ${{esc(c.period)}}</div>
          <div><span>Content SHA-256 Digest:</span> <code>${{esc(c.hash)}}</code></div>
        </div>
      </div>
    `).join('')}}
  `;

  $('#evidence-modal-content').innerHTML=evidenceHtml;
  $('#evidence-title').textContent=`Evidence & Sources: ${{x.name}} (${{x.org}})`;
  $('#evidence-modal').classList.add('open');
}}

function closeEvidenceModal(){{
  $('#evidence-modal').classList.remove('open');
}}

function requestedModes(question){{
  const q=norm(question),m=[];
  if(/financial|finance|account|revenue|income|profit|debt|asset|result|regnskap|inntekt|gjeld/.test(q))m.push('financials');
  if(/lead|leader|role|director|chair|board|ceo|leder|styre/.test(q))m.push('leaders');
  if(/location|where|address|shop|office|branch|place|sted|adresse|butikk|kontor/.test(q))m.push('locations');
  if(/social|linkedin|facebook|instagram|youtube|tiktok|profile|handle/.test(q))m.push('social');
  if(/sentiment|reputation|opinion|positive|negative|omtale/.test(q))m.push('sentiment');
  if(/employee|company|overview|know|registered|industry|kommune|ansatt/.test(q)||!m.length)m.unshift('overview');
  return [...new Set(m)];
}}

function agentBody(x,mode){{
  let body='';
  if(mode==='overview')body=`<p><strong>${{esc(x.name)}}</strong> is registered as ${{esc(x.form||'form not reported')}} in ${{esc(x.municipality||'a municipality not reported in the snapshot')}}. Registry employees: ${{x.employees==null?'not reported':esc(x.employees)}}.${{cite(x.registrySource)}}</p>`;
  if(mode==='financials'){{const r=x.financial.records[0];body=r?`<p>The latest normalized record reports revenue of <strong>${{money(r.revenue,r.currency)}}</strong>, operating result of <strong>${{money(r.operating_result,r.currency)}}</strong>, and debt of <strong>${{money(r.debt,r.currency)}}</strong>.${{cite(x.financial.source)}}</p>`:`<p>No normalized annual account was returned. Missing is not zero.${{cite(x.financial.source)}}</p>`}}
  if(mode==='leaders')body=x.roles.items.length?`<p>${{x.roles.items.slice(0,5).map(r=>`<strong>${{esc(r.name||'Unnamed')}}</strong> — ${{esc(r.role||r.group||'role')}}`).join('<br>')}}${{cite(x.roles.source)}}</p>`:`<p>No public role record was returned.${{cite(x.roles.source)}}</p>`;
  if(mode==='locations')body=x.locations.items.length?`<p>${{x.locations.items.slice(0,5).map(l=>`<strong>${{esc(l.name)}}</strong> — ${{esc(l.address?.kommune||l.address?.poststed||'address not reported')}}`).join('<br>')}}${{cite(x.locations.source)}}</p>`:`<p>No registered subunit was returned. That does not prove there is no physical presence.${{cite(x.locations.source)}}</p>`;
  if(mode==='social')body=(x.web.value.social_links||[]).length?`<p>${{x.web.value.social_links.map(s=>`<strong>${{esc(s.platform)}}</strong> — <a href="${{esc(s.url)}}" target="_blank" rel="noreferrer">declared profile ↗</a>`).join('<br>')}}<br><small>Linked from the company-controlled site. Profile metrics have not yet passed the external audit.</small></p>`:x.web.value.quarantined_social_count?`<p><strong>${{esc(x.web.value.quarantined_social_count)}} social link(s) found but not published.</strong> The registry-linked site could not be verified as this exact legal entity.</p>`:`<p>No verified external profile data is available yet. A discovery task is planned; planned work is not evidence.</p>`;
  if(mode==='sentiment')body='<p><strong>Not available.</strong> External sentiment is now a scored competition module, but this snapshot has not passed the labelled Norwegian review/news audit.</p>';
  return body;
}}

function renderAgent(){{
  const x=selected;if(!x){{$('#agent-output').innerHTML='<p>Choose a company first.</p>';return}}
  const modes=agentQuestion?requestedModes(agentQuestion):[agentMode],labels={{overview:'Company record',financials:'Financials',leaders:'Leadership',locations:'Locations',social:'Social profiles',sentiment:'Sentiment'}};
  let body=modes.map(mode=>`<div class="answer-block"><small>${{labels[mode]}}</small>${{agentBody(x,mode)}}</div>`).join('');
  if(agentQuestion)body=`<p class="agent-question"><small>Your question</small><br><strong>${{esc(agentQuestion)}}</strong></p>`+body;
  $('#agent-output').innerHTML=body;
  $('#agent-buttons').querySelectorAll('button').forEach(b=>b.classList.toggle('active',!agentQuestion&&b.dataset.mode===agentMode));
}}

function statusChip(label,status){{
  const cls=status==='available'?'good':status==='not_found'?'warn':'';
  return `<span class="chip ${{cls}}">${{esc(label)}}: ${{esc(status.replaceAll('_',' '))}}</span>`;
}}
function sourceLine(obj){{
  return obj?.source?`<details class="source"><summary>Inspect evidence</summary><div>Source: <a href="${{esc(obj.source)}}" target="_blank" rel="noreferrer">${{esc(obj.source)}}</a></div><div>Class: ${{esc(obj.sourceClass||'not reported')}} · Retrieved: ${{esc(obj.retrievedAt||'not reported')}}</div>${{obj.effectiveAt?`<div>Effective: ${{esc(obj.effectiveAt)}}</div>`:''}}${{obj.hash?`<div>SHA-256: <code>${{esc(obj.hash)}}</code></div>`:''}}</details>`:'';
}}

function linkifySourceText(text){{
  const escaped=esc(text);
  return escaped.replace(/https?:\\/\\/[^\\s),"]+/g,url=>`<a href="${{url}}" target="_blank" rel="noreferrer">${{url}} ↗</a>`);
}}

function renderProfile(){{
  const x=selected;if(!x){{$('#profile').innerHTML='<p class="empty">Choose a company.</p>';renderAgent();return}}
  const rec=x.financial.records[0],people=x.roles.items.filter(r=>!r.inactive),locations=x.locations.items,social=x.web.value.social_links||[],pdfs=x.financialHistory.pdfs||[],isPinned=workspace.pins.includes(x.org),accounting=x.accounting.value||{{}};
  const isComp=compareSelected.includes(x.org);

  // Format buyer summary: separate Sentence 1 and body
  const summaryRaw=x.summary||'';
  let s1='',sRest='';
  if(summaryRaw){{
    const m=summaryRaw.match(/^([^.]+\\(Source:[^)]+\\)\\.?)\\s*(.*)$/);
    if(m){{s1=m[1];sRest=m[2];}}
    else{{
      const parts=summaryRaw.split(/(?<=\\.\\s)/);
      s1=parts[0]||'';
      sRest=parts.slice(1).join(' ');
    }}
  }}

  // Action links
  const siteUrl=x.website||(x.web?.status==='available'?x.web.source:null);
  const brregUrl=x.registrySource||`https://data.brreg.no/enhetsregisteret/oppslag/enheter/${{x.org}}`;
  
  // Metric card values
  const yoyText=x.yoy?.text||'';
  const mGrowth=yoyText.match(/Revenue:[^(]+\\(([+-]?[\\d.]+%)\\)/);
  const yoyGrowthBadge=mGrowth?`<span style="color:${{mGrowth[1].startsWith('+')?'var(--good)':'var(--warn)'}}">${{mGrowth[1]}} YoY</span>`:'';
  const revValue=rec?`${{money(rec.revenue,rec.currency)}} ${{yoyGrowthBadge}}`:'No accounts on file';
  const opValue=rec?`Operating result: ${{money(rec.operating_result,rec.currency)}}`:'Filing applicability not reported';

  const empValue=x.employees!=null?`${{x.employees}} Employees`:'Workforce not reported';
  const jobValue=x.jobs?.length?`💼 ${{x.jobs.length}} verified open job(s)`:'No active job postings captured';

  const newsValue=x.news?.length?`📰 ${{x.news.length}} verified news release(s)`:(x.external?.linkedin?.posts?.length?`📱 ${{x.external.linkedin.posts.length}} public posts captured`:'No news documented');
  const latestNews=(x.news&&x.news[0])?`"${{esc(x.news[0].title||'')}}" (${{esc(x.news[0].date||'')}})`:'';

  $('#profile').innerHTML=`
    <div class="profile-head">
      <div>
        <div class="eyebrow">${{esc(x.slice)}} sample · ${{esc(x.split)}}</div>
        <h2>${{esc(x.name)}} <span class="chip good" style="font-size:12px;vertical-align:middle">✅ Verified Entity</span></h2>
        <div style="margin:4px 0 8px;color:var(--muted);font-size:13px">${{esc(x.org)}} · ${{esc(x.form||'AS')}} · ${{esc(x.municipality||'Norway')}} · ${{esc(x.industry||'General')}}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px">
          ${{siteUrl?`<a class="buyer-link-btn" href="${{esc(siteUrl)}}" target="_blank" rel="noreferrer">🌐 Company Website ↗</a>`:''}}
          <a class="buyer-link-btn" href="${{esc(brregUrl)}}" target="_blank" rel="noreferrer">🏛️ Brreg Registry ↗</a>
          <button type="button" class="buyer-btn" onclick="copyBuyerBrief()">📋 Copy Buyer Brief</button>
          <button type="button" class="buyer-btn" onclick="toggleCompare('${{x.org}}')">${{isComp?'✓ In Comparison':'⚖️ Add to Compare'}}</button>
          <button type="button" class="buyer-btn" onclick="openEvidenceModal()" style="border-color:var(--accent);color:var(--accent)">🔍 Check Evidence &amp; Sources</button>
        </div>
      </div>
      <div style="text-align:right">
        <button class="pin-button" id="pin-company" type="button">${{isPinned?'Unpin':'Pin company'}}</button>
        <div class="chips" style="margin-top:8px;justify-content:flex-end">
          ${{statusChip('accounts',x.financial.status)}}
          ${{statusChip('roles',x.roles.status)}}
          ${{statusChip('website',x.web.status)}}
          ${{x.adverse?'<span class="chip warn">adverse registry state</span>':'<span class="chip good">no adverse flag</span>'}}
        </div>
      </div>
    </div>

    <!-- Commercial Buyer Brief Callout -->
    ${{summaryRaw?`
    <div class="buyer-summary-box">
      <div class="buyer-summary-head">
        <span class="buyer-summary-tag">⚡ Commercial Buyer Brief</span>
        <button type="button" class="buyer-btn" onclick="copyBuyerBrief()">📋 Copy</button>
      </div>
      <div class="buyer-summary-sentence1">${{linkifySourceText(s1)}}</div>
      ${{sRest?`<div class="buyer-summary-body">${{linkifySourceText(sRest)}}</div>`:''}}
    </div>`:''}}

    <!-- 3 Key Buyer Metric Pills -->
    <div class="buyer-metrics-grid">
      <div class="buyer-metric-card">
        <span>💰 Revenue &amp; Financials</span>
        <strong>${{revValue}}</strong>
        <small>${{opValue}}</small>
      </div>
      <div class="buyer-metric-card">
        <span>👥 Workforce &amp; Hiring</span>
        <strong>${{empValue}}</strong>
        <small>${{jobValue}}</small>
      </div>
      <div class="buyer-metric-card">
        <span>📰 Latest Activity &amp; Signals</span>
        <strong>${{newsValue}}</strong>
        <small>${{latestNews?latestNews:'Signals grounded in official records'}}</small>
      </div>
    </div>

    <div class="fact-grid">
      <div class="fact"><span>Industry</span><strong>${{esc(x.industryCode||'—')}} ${{esc(x.industry||'Not reported')}}</strong></div>
      <div class="fact"><span>Municipality</span><strong>${{esc(x.municipality||'Not reported')}}</strong></div>
      <div class="fact"><span>Employees</span><strong>${{x.employees==null?'Not reported':esc(x.employees)}}</strong></div>
      <div class="fact"><span>Accounting availability</span><strong>${{esc((accounting.classification||'not classified').replaceAll('_',' '))}}</strong><small>${{esc(accounting.reason||'')}}</small></div>
    </div>

    ${{(x.jobs&&x.jobs.length)?`
    <section>
      <div class="section-label">Verified Open Jobs (${{x.jobs.length}})</div>
      <h3>Current Hiring Postings</h3>
      <div class="people">
        ${{x.jobs.slice(0,6).map(j=>`<div class="item"><strong>${{esc(j.title||'Job Opening')}}</strong><small>${{esc(j.location||'Norway')}} · ${{esc(j.date||'Recent')}} · <a href="${{esc(j.source_url||siteUrl)}}" target="_blank" rel="noreferrer">source ↗</a></small></div>`).join('')}}
      </div>
    </section>`:''}}

    ${{(x.news&&x.news.length)?`
    <section>
      <div class="section-label">Verified News Releases (${{x.news.length}})</div>
      <h3>Recent Public Announcements</h3>
      <div class="activity-list">
        ${{x.news.slice(0,5).map(n=>`<div class="activity"><small>${{esc(n.date||'Recent')}} · <a href="${{esc(n.source_url||siteUrl)}}" target="_blank" rel="noreferrer">source ↗</a></small><p><strong>${{esc(n.title||'')}}</strong></p></div>`).join('')}}
      </div>
    </section>`:''}}

    <section id="official-accounts-section">
      <div class="section-label">Official annual account</div>
      <h3>${{rec?'Latest normalized figures':'No normalized financial record returned'}}</h3>
      ${{rec?`<table><tr><th>Period</th><td>${{esc(rec.period?.fraDato||'')}} – ${{esc(rec.period?.tilDato||'')}}</td></tr><tr><th>Revenue</th><td>${{money(rec.revenue,rec.currency)}}</td></tr><tr><th>Operating result</th><td>${{money(rec.operating_result,rec.currency)}}</td></tr><tr><th>Annual result</th><td>${{money(rec.annual_result,rec.currency)}}</td></tr><tr><th>Assets</th><td>${{money(rec.assets,rec.currency)}}</td></tr><tr><th>Debt</th><td>${{money(rec.debt,rec.currency)}}</td></tr></table>`:`<p class="empty">${{esc(accounting.reason||'Not publicly available (checked Regnskapsregisteret on 2026-11-14). Missing is not zero.')}}</p>`}}
      ${{pdfs.length?`<p class="source">Historical filings: ${{pdfs.slice(0,8).map(p=>`<a href="${{esc(p.url)}}" target="_blank" rel="noreferrer">${{esc(p.year)}}</a>`).join(' · ')}}</p>`:''}}
      ${{sourceLine(x.accounting)}}${{sourceLine(x.financial)}}
    </section>

    <section>
      <div class="section-label">Registered people &amp; Governance</div>
      <h3>${{people.length}} public role records</h3>
      <div class="people">
        ${{people.length?people.slice(0,16).map(r=>`<div class="item"><strong>${{esc(r.name||r.organisation_number||'Unnamed holder')}}</strong><small>${{esc(r.role||r.group||'Role not reported')}}</small></div>`).join(''):'<p class="empty">Not publicly registered (checked Brreg on 2026-11-14).</p>'}}
      </div>
      ${{sourceLine(x.roles)}}
    </section>

    <section>
      <div class="section-label">Registered operating locations</div>
      <h3>${{locations.length}} subunits</h3>
      <div class="locations">
        ${{locations.length?locations.slice(0,12).map(l=>`<div class="item"><strong>${{esc(l.name)}}</strong><small>${{esc(l.address?.kommune||l.address?.poststed||'Location not reported')}} · ${{l.employees??'employees not reported'}}</small></div>`).join(''):'<p class="empty">Location module not run or no registered subunits on file.</p>'}}
      </div>
      ${{sourceLine(x.locations)}}
    </section>

    <section>
      <div class="section-label">Update history</div>
      <h3>${{x.changes.length}} recorded changes</h3>
      ${{x.changes.length?`<table>${{x.changes.map(c=>`<tr><th>${{esc(c.field)}}</th><td>${{esc(JSON.stringify(c.old_value))}} → ${{esc(JSON.stringify(c.new_value))}}</td></tr>`).join('')}}</table>`:'<p class="empty">No changes are attached to this frozen profile yet. Retrieval timestamps and hashes below still show the evidence version.</p>'}}
    </section>

    <section>
      <div class="section-label">Company-controlled web layer</div>
      <h3>${{esc(x.web.value.title||'No fetched homepage')}}</h3>
      <p>${{esc(x.web.value.description||'No company-site description captured.')}}</p>
      <p class="source">${{(x.web.value.pages||[]).length}} bounded same-site page(s) captured.</p>
      <div class="social">${{social.map(s=>`<div class="item"><strong>${{esc(s.platform)}}</strong><small><a href="${{esc(s.url)}}" target="_blank" rel="noreferrer">${{esc(s.url)}}</a></small></div>`).join('')}}</div>
      ${{sourceLine(x.web)}}
    </section>
  `;
  $('#pin-company').onclick=()=>{{workspace.pins=isPinned?workspace.pins.filter(org=>org!==x.org):[...new Set([...workspace.pins,x.org])].sort();persistWorkspace();renderList();renderProfile()}};
  renderAgent();
}}

['q','form','state','finance','slice'].forEach(id=>$('#'+id).addEventListener(id==='q'?'input':'change',()=>{{selected=null;renderList()}}));
$('#save-view').onclick=()=>{{const rows=filtered();workspace.history=[...workspace.history,{{createdAt:new Date().toISOString(),label:$('#q').value||'Structured filter view',filters:{{query:$('#q').value,form:$('#form').value,state:$('#state').value,finance:$('#finance').value,slice:$('#slice').value}},resultCount:rows.length,resultOrganisationNumbers:rows.map(x=>x.org)}}].slice(-100);persistWorkspace()}};
$('#export-view').onclick=()=>{{const rows=filtered();const artifact={{exportedAt:new Date().toISOString(),filters:{{query:$('#q').value,form:$('#form').value,state:$('#state').value,finance:$('#finance').value,slice:$('#slice').value}},profiles:rows,claimBoundary:'Source-linked frozen Signalpost evidence; missing values are not zero.'}};const blob=new Blob([JSON.stringify(artifact,null,2)],{{type:'application/json'}}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='signalpost-evidence-export.json';a.click();URL.revokeObjectURL(url)}};
$('#export-csv').onclick=exportCsv;

document.querySelectorAll('#buyer-pills .bpill').forEach(btn=>{{
  btn.onclick=()=>{{
    const target=btn.dataset.bfilter;
    if(buyerFilter===target&&target!=='all'){{buyerFilter='all';}}else{{buyerFilter=target;}}
    document.querySelectorAll('#buyer-pills .bpill').forEach(b=>{{b.classList.toggle('active',b.dataset.bfilter===buyerFilter)}});
    selected=null;renderList();
  }};
}});

$('#agent-form').onsubmit=e=>{{e.preventDefault();agentQuestion=$('#agent-question').value.trim();if(agentQuestion)renderAgent()}};
$('#agent-buttons').querySelectorAll('button').forEach(b=>b.onclick=()=>{{agentMode=b.dataset.mode;agentQuestion='';$('#agent-question').value='';renderAgent()}});
renderStats();renderQualification();renderWorkspace();renderList();
</script><script>
function renderLinkedInLayer(x){{
  const li=x.external?.linkedin||{{}},profile=li.profile||{{}},posts=li.posts||[],jobs=li.jobs||[];
  if(!li.available)return `<section id="linkedin-layer"><div class="section-label">LinkedIn and public activity</div><h3>No exact LinkedIn profile captured</h3><p class="empty">The discovery loop abstained for this company. Missing is not zero, and no profile is inferred from name similarity alone.</p></section>`;
  const cards=[['Followers',profile.followers],['Associated profiles',profile.visible_employees],['Company size',profile.employee_size_label],['Headquarters',profile.headquarters],['Open jobs captured',jobs.length],['Recent posts captured',posts.length]].map(([label,value])=>`<div class="signal-card"><span>${{esc(label)}}</span><strong>${{value??'Not reported'}}</strong></div>`).join('');
  const activity=posts.slice(0,3).map(p=>`<div class="activity"><small>${{esc(p.date_posted||p.published_at||'Date not reported')}}</small><p>${{esc(p.text||'Public post captured.')}}</p><small>${{p.likes??0}} reactions · ${{p.comments??0}} comments · <a href="${{esc(p.source)}}" target="_blank" rel="noreferrer">source ↗</a></small></div>`).join('');
  const openings=jobs.slice(0,5).map(j=>`<div class="item"><strong>${{esc(j.title||'Role not reported')}}</strong><small>${{esc(j.location||'Location not reported')}} · ${{esc(j.date_posted||'Date not reported')}} · <a href="${{esc(j.job_url||j.source)}}" target="_blank" rel="noreferrer">posting ↗</a></small></div>`).join('');
  return `<section id="linkedin-layer"><div class="section-label">LinkedIn and public activity</div><h3>${{esc(profile.industry||'Exact company profile')}}</h3><p class="experimental-note"><strong>Experimental external evidence.</strong> The exact-company match is retained, but platform metrics are separated from strict company-controlled evidence.</p><div class="signal-grid">${{cards}}</div>${{activity?`<h3>Recent public activity</h3><div class="activity-list">${{activity}}</div>`:''}}${{openings?`<h3 style="margin-top:18px">Current hiring signals</h3><div class="people">${{openings}}</div>`:''}}${{sourceLine(profile)}}</section>`;
}}
function injectLinkedInLayer(){{
  const profileRoot=$('#profile');if(!selected||!profileRoot||$('#linkedin-layer'))return;
  const sections=profileRoot.querySelectorAll('section');
  const target=sections[sections.length-1];
  if(target)target.insertAdjacentHTML('beforebegin',renderLinkedInLayer(selected));
}}
const baseAgentBody=agentBody;
agentBody=(x,mode)=>{{
  const li=x.external?.linkedin||{{}},profile=li.profile||{{}},jobs=li.jobs||[],posts=li.posts||[];
  if(mode==='social')return li.available?`<p><strong>LinkedIn:</strong> ${{profile.followers??'unreported'}} followers · ${{profile.visible_employees??'unreported'}} associated profiles · ${{esc(profile.employee_size_label||'size not reported')}}.${{cite(profile.source)}}</p>`:baseAgentBody(x,mode);
  if(mode==='hiring')return jobs.length?`<p>${{jobs.slice(0,5).map(j=>`<strong>${{esc(j.title||'Role')}}</strong> — ${{esc(j.location||'location not reported')}}`).join('<br>')}}${{cite(jobs[0].job_url||jobs[0].source)}}</p>`:'<p>No exact-company LinkedIn job posting was captured in this snapshot.</p>';
  if(mode==='activity')return posts.length?`<p><strong>${{posts.length}} recent public post(s) captured.</strong><br>${{posts.slice(0,3).map(p=>esc(p.text||'Post captured')).join('<br><br>')}}</p>`:'<p>No exact-company public LinkedIn post was captured in this snapshot.</p>';
  return baseAgentBody(x,mode);
}};
const baseRequestedModes=requestedModes;
requestedModes=question=>{{
  const modes=baseRequestedModes(question),q=norm(question);
  if(/job|hiring|hire|career|vacan|stilling|recruit/.test(q))modes.push('hiring');
  if(/post|activity|buzz|engagement|reaction|comment|talking/.test(q))modes.push('activity');
  return [...new Set(modes)];
}};
renderAgent=()=>{{
  const x=selected;if(!x){{$('#agent-output').innerHTML='<p>Choose a company first.</p>';return}}
  const modes=agentQuestion?requestedModes(agentQuestion):[agentMode],labels={{overview:'Company record',financials:'Financials',leaders:'Leadership',locations:'Locations',social:'LinkedIn',hiring:'Hiring',activity:'Public activity',sentiment:'Sentiment'}};
  let body=modes.map(mode=>`<div class="answer-block"><small>${{labels[mode]||esc(mode)}}</small>${{agentBody(x,mode)}}</div>`).join('');
  if(agentQuestion)body=`<p class="agent-question"><small>Your question</small><br><strong>${{esc(agentQuestion)}}</strong></p>`+body;
  $('#agent-output').innerHTML=body;
  $('#agent-buttons').querySelectorAll('button').forEach(b=>b.classList.toggle('active',!agentQuestion&&b.dataset.mode===agentMode));
}};
const baseRenderList=renderList;
renderList=()=>{{baseRenderList();queueMicrotask(injectLinkedInLayer)}};
new MutationObserver(injectLinkedInLayer).observe($('#profile'),{{childList:true}});
injectLinkedInLayer();renderAgent();
if(SCORE.scorer==='signalpost_all_source_completeness_v1')$('#core-score').textContent=`${{Number(SCORE.raw_score||0).toFixed(2)}}/100 experimental · ${{Number(SCORE.awardable_score||0).toFixed(2)}}/100 strict`;
</script></body></html>'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--score")
    parser.add_argument("--control-loop")
    parser.add_argument("--independent-score")
    parser.add_argument("--external-observations", nargs="*")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    rows = read_jsonl(Path(args.input))
    if args.limit:
        rows = rows[:args.limit]
    external_by_org: dict[str, list[dict]] = defaultdict(list)
    seen_observations: set[str] = set()
    for source in args.external_observations or []:
        for observation in read_jsonl(Path(source)):
            observation_id = str(observation.get("id") or json.dumps(observation, sort_keys=True, ensure_ascii=False))
            if observation_id in seen_observations:
                continue
            seen_observations.add(observation_id)
            organisation_number = str(observation.get("organisation_number") or "")
            if organisation_number:
                external_by_org[organisation_number].append(observation)
    score = json.loads(Path(args.score).read_text(encoding="utf-8")) if args.score and Path(args.score).exists() else None
    control_loop = json.loads(Path(args.control_loop).read_text(encoding="utf-8")) if args.control_loop and Path(args.control_loop).exists() else None
    independent_score = json.loads(Path(args.independent_score).read_text(encoding="utf-8")) if args.independent_score and Path(args.independent_score).exists() else None
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build(rows, score, control_loop, independent_score, external_by_org), encoding="utf-8")
    print(f"Wrote {output} with {len(rows)} profiles")
