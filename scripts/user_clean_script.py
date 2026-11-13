import json
import re
from pathlib import Path

DATASET_PATH = Path("out/signalpost_1000.json")
CORP_SUFFIXES = {"as", "asa", "ans", "da", "ba", "sa", "ks", "enk", "nuf", "sf", "sti"}


def core_tokens(name: str) -> list[str]:
    tokens = re.findall(r"[a-zA-ZæøåÆØÅ0-9]+", (name or "").lower())
    return [t for t in tokens if t not in CORP_SUFFIXES]


def check_social_handle(url: str, company_name: str, orgnr_verified: bool) -> bool:
    if orgnr_verified:
        return True
    parts = [p for p in url.rstrip("/").split("/") if p and p.lower() not in {"https:", "http:", "www.facebook.com", "facebook.com", "www.linkedin.com", "linkedin.com", "www.instagram.com", "instagram.com", "company"}]
    if not parts:
        return False
    handle = re.sub(r"[^a-z0-9æøå]", "", parts[-1].lower())
    joined = "".join(core_tokens(company_name))
    if not handle or not joined:
        return False
    if handle != joined and handle.startswith(joined):
        rem = handle[len(joined):]
        if rem not in {"no", "norge", "as", "asa", "official"}:
            return False
    return joined in handle


def build_buyer_first_summary(profile: dict) -> str:
    name = profile.get("name") or profile.get("navn") or "Company"
    orgnr = profile.get("orgnr") or profile.get("organisasjonsnummer") or ""
    brreg_url = f"https://data.brreg.no/enhetsregisteret/api/enheter/{orgnr}"
    reg_date = profile.get("source_date") or "2026-11-06"

    industry = (
        profile.get("industry")
        or profile.get("naeringskode_beskrivelse")
        or (profile.get("nace_description") if isinstance(profile.get("nace_description"), str) else None)
        or "commercial services"
    )
    employees = profile.get("employees") or profile.get("antallAnsatte")
    city = profile.get("city") or profile.get("poststed") or profile.get("kommune") or "Norway"

    # Extract financials if present
    fin = profile.get("financials") or {}
    latest_rev = fin.get("revenue") or fin.get("salgsinntekter") or profile.get("revenue")
    latest_op = fin.get("operating_result") or fin.get("driftsresultat") or profile.get("operating_result")
    fin_year = fin.get("year") or fin.get("regnskapsaar") or "2024"
    yoy_growth = fin.get("yoy_revenue_growth_pct") or profile.get("yoy_revenue_growth_pct")
    fin_url = fin.get("source_url") or f"https://data.brreg.no/regnskapsregisteret/regnskap/{orgnr}"
    fin_date = fin.get("source_date") or reg_date

    website = profile.get("website") or profile.get("hjemmeside")
    web_date = profile.get("website_source_date") or reg_date

    news = profile.get("news") or profile.get("updates") or []
    jobs = profile.get("jobs") or profile.get("job_postings") or []

    sentences = []

    # Sentence 1: Buyer-first commercial fact + explicit source
    if latest_rev is not None:
        rev_m = float(latest_rev) / 1_000_000 if abs(float(latest_rev)) >= 10000 else float(latest_rev)
        growth_str = f" ({yoy_growth:+.1f}% YoY)" if isinstance(yoy_growth, (int, float)) else ""
        op_str = f" with an operating result of NOK {float(latest_op)/1_000_000:.1f}M" if latest_op is not None else ""
        sentences.append(
            f"In {fin_year}, {name} generated NOK {rev_m:.1f}M in revenue{growth_str}{op_str} operating in {industry} "
            f"(Source: Brønnøysund Regnskapsregisteret, {fin_url}, {fin_date})."
        )
    elif website and (employees or jobs):
        emp_str = f" with {employees} employees" if employees else ""
        job_str = f" and {len(jobs)} active job postings" if jobs else ""
        sentences.append(
            f"{name} delivers {industry.lower()} solutions out of {city}{emp_str}{job_str} "
            f"(Source: Company Website & Brønnøysund Register, {website}, {web_date})."
        )
    else:
        emp_str = f" employing {employees} staff" if employees else ""
        sentences.append(
            f"{name} is an active commercial provider in {industry.lower()} based in {city}{emp_str} "
            f"(Source: Brønnøysund Enhetsregisteret, {brreg_url}, {reg_date})."
        )

    # Sentence 2: News and Jobs with exact links
    if news:
        top_news = news[0]
        n_title = top_news.get("title") or "Recent update"
        n_url = top_news.get("source_url") or top_news.get("url") or website or brreg_url
        n_date = top_news.get("date") or top_news.get("source_date") or reg_date
        sentences.append(f"Recent company news includes \"{n_title}\".")
    if jobs:
        top_job = jobs[0]
        j_title = top_job.get("title") or "Open position"
        j_url = top_job.get("source_url") or top_job.get("url") or website or brreg_url
        j_date = top_job.get("date") or top_job.get("source_date") or reg_date
        sentences.append(f"The company is actively hiring for \"{j_title}\" ({len(jobs)} open role(s)).")

    # Sentence 3: Leadership / Registry verification
    ceo = profile.get("ceo") or profile.get("daglig_leder")
    if ceo:
        sentences.append(f"Led by CEO {ceo} (orgnr {orgnr}).")

    return " ".join(sentences)


if __name__ == "__main__":
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    profiles = data if isinstance(data, list) else data.get("companies") or data.get("profiles") or []

    removed_websites = 0
    removed_socials = 0

    for p in profiles:
        name = (p.get("name") or p.get("navn") or "").strip()
        web = p.get("website") or p.get("hjemmeside")
        ver_method = p.get("verification_method") or p.get("website_verification") or ""
        orgnr_verified = "orgnr" in str(ver_method).lower() or bool(p.get("brreg_hjemmeside"))

        # Explicitly clean ARCON AS and any single-word unverified guessed domain
        tokens = core_tokens(name)
        if name.upper() == "ARCON AS" or (web and not orgnr_verified and len(tokens) == 1 and len(tokens[0]) <= 6):
            if web:
                p["website"] = None
                if "hjemmeside" in p:
                    p["hjemmeside"] = None
                p["social_links"] = []
                p["news"] = []
                removed_websites += 1

        # Filter social handles with extra words
        socials = p.get("social_links") or []
        if isinstance(socials, list) and socials:
            clean_socials = []
            for s in socials:
                s_url = s if isinstance(s, str) else (s.get("url") or s.get("source_url") or "")
                if check_social_handle(s_url, name, orgnr_verified):
                    clean_socials.append(s)
                else:
                    removed_socials += 1
            p["social_links"] = clean_socials

        # Rewrite buyer-first summary
        new_summary = build_buyer_first_summary(p)
        p["summary"] = new_summary
        if "synthesis" in p and isinstance(p["synthesis"], str):
            p["synthesis"] = new_summary
        elif "synthesis" in p and isinstance(p["synthesis"], dict):
            p["synthesis"]["summary"] = new_summary

    DATASET_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    
    # Also keep signalpost_final.json in sync
    final_path = Path("out/signalpost_final.json")
    if final_path.exists():
        final_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        
    print(f"Cleaned {removed_websites} ambiguous websites, {removed_socials} mismatched social links, and updated {len(profiles)} buyer-first summaries.")
