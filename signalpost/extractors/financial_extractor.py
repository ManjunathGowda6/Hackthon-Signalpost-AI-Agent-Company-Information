"""Financial extractor for official Regnskapsregisteret data."""
from __future__ import annotations

from typing import Any, Optional
from datetime import datetime, timezone
from signalpost.models.envelope import AnnualAccounts, ClaimValue


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


ALWAYS_ACCOUNTING_OBLIGED_FORMS = {"AS", "ASA", "BRL", "BBL", "STI", "SF", "VPFO"}
THRESHOLD_OR_ACTIVITY_FORMS = {"ENK", "ANS", "DA", "SA", "FLI", "ESEK", "NUF", "UTLA", "ORGL", "SAM", "SPA", "KS", "BO"}


class FinancialExtractor:
    @staticmethod
    def assess_obligation(legal_form: Optional[str], latest_submitted: Optional[Any]) -> dict[str, Any]:
        form = str(legal_form or "").upper()
        if latest_submitted:
            classification = "filing_observed"
            reason = "The official registry reports a submitted annual-account filing."
        elif form in ALWAYS_ACCOUNTING_OBLIGED_FORMS:
            classification = "required_by_legal_form"
            reason = f"Brreg lists organisation form {form} as having a statutory accounting obligation."
        elif form in THRESHOLD_OR_ACTIVITY_FORMS:
            classification = "threshold_or_activity_dependent"
            reason = "Obligation depends on statutory size, activity, or turnover thresholds."
        else:
            classification = "special_rule_or_review_required"
            reason = "The legal form is insufficient for a definitive obligation classification."

        return {
            "classification": classification,
            "legal_form": form or None,
            "latest_submitted_accounts": latest_submitted or None,
            "reason": reason,
            "source": "https://www.brreg.no/en/submission-of-annual-accounts/reporting-obligations-to-the-register-of-company-accounts/who-has-an-accounting-obligation/",
        }

    @classmethod
    def extract_accounts(
        cls,
        accounts_data: Any,
        org_number: str,
        legal_form: Optional[str] = None,
        registry_employees: Optional[int] = None,
    ) -> AnnualAccounts:
        src = f"https://data.brreg.no/regnskapsregisteret/regnskap/{org_number}"
        now = utc_now()
        records = accounts_data if isinstance(accounts_data, list) else []

        obligation = cls.assess_obligation(legal_form, len(records) > 0)
        obligation_class = obligation["classification"]

        if not records:
            return AnnualAccounts(
                status="not_available",
                accounting_obligation=obligation_class,
                employees=ClaimValue(
                    value=registry_employees,
                    source=f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}",
                    retrieved_at=now,
                ) if registry_employees is not None else None,
            )

        def get_year(item):
            to_date = item.get("regnskapsperiode", {}).get("tilDato", "")
            return to_date[:4] if len(to_date) >= 4 else "0000"

        sorted_records = sorted(records, key=get_year, reverse=True)
        latest = sorted_records[0]
        latest_year_str = get_year(latest)
        latest_year = int(latest_year_str) if latest_year_str.isdigit() and int(latest_year_str) > 1900 else None
        currency = latest.get("valuta", "NOK")

        res = latest.get("resultatregnskapResultat", {})
        drifts = res.get("driftsresultat", {})
        inntekter = drifts.get("driftsinntekter", {})
        revenue_val = inntekter.get("sumDriftsinntekter") if inntekter.get("sumDriftsinntekter") is not None else inntekter.get("salgsinntekter")
        op_profit_val = drifts.get("driftsresultat")
        pbt_val = res.get("ordinaertResultatFoerSkattekostnad")
        net_income_val = res.get("aarsresultat")

        eiendeler = latest.get("eiendeler", {})
        assets_val = eiendeler.get("sumEiendeler")
        egenkap_gjeld = latest.get("egenkapitalGjeld", {})
        equity_val = egenkap_gjeld.get("egenkapital", {}).get("sumEgenkapital")
        debt_val = egenkap_gjeld.get("gjeldOversikt", {}).get("sumGjeld")

        history = []
        for item in sorted_records[1:6]:
            y_str = get_year(item)
            if not y_str.isdigit():
                continue
            item_res = item.get("resultatregnskapResultat", {})
            item_inn = item_res.get("driftsresultat", {}).get("driftsinntekter", {})
            item_rev = item_inn.get("sumDriftsinntekter") if item_inn.get("sumDriftsinntekter") is not None else item_inn.get("salgsinntekter")
            history.append({
                "year": int(y_str),
                "currency": item.get("valuta", "NOK"),
                "revenue": item_rev,
                "operating_profit": item_res.get("driftsresultat", {}).get("driftsresultat"),
                "net_income": item_res.get("aarsresultat"),
                "total_assets": item.get("eiendeler", {}).get("sumEiendeler"),
                "source": src,
            })

        period_str = str(latest_year) if latest_year else None

        return AnnualAccounts(
            status="available",
            latest_filing_year=latest_year,
            currency=currency,
            revenue=ClaimValue(value=revenue_val, currency=currency, period=period_str, source=src, retrieved_at=now) if revenue_val is not None else None,
            operating_profit=ClaimValue(value=op_profit_val, currency=currency, period=period_str, source=src, retrieved_at=now) if op_profit_val is not None else None,
            profit_before_tax=ClaimValue(value=pbt_val, currency=currency, period=period_str, source=src, retrieved_at=now) if pbt_val is not None else None,
            net_income=ClaimValue(value=net_income_val, currency=currency, period=period_str, source=src, retrieved_at=now) if net_income_val is not None else None,
            total_assets=ClaimValue(value=assets_val, currency=currency, period=period_str, source=src, retrieved_at=now) if assets_val is not None else None,
            total_equity=ClaimValue(value=equity_val, currency=currency, period=period_str, source=src, retrieved_at=now) if equity_val is not None else None,
            total_debt=ClaimValue(value=debt_val, currency=currency, period=period_str, source=src, retrieved_at=now) if debt_val is not None else None,
            employees=ClaimValue(value=registry_employees, period=period_str, source=f"https://data.brreg.no/enhetsregisteret/api/enheter/{org_number}", retrieved_at=now) if registry_employees is not None else None,
            accounting_obligation=obligation_class,
            historical_summary=history,
        )

    @staticmethod
    def generate_yoy_summary(accounts: "AnnualAccounts") -> Optional[dict[str, Any]]:
        """Generate a Year-over-Year written financial summary comparing latest vs prior year.
        
        Upgrade 4: YoY Written Financial Summary.
        """
        if accounts.status != "available" or not accounts.historical_summary:
            return None

        latest_year = accounts.latest_filing_year
        if not latest_year:
            return None

        # Find the prior year in historical data
        prior = None
        for h in accounts.historical_summary:
            if h.get("year") and h["year"] < latest_year:
                prior = h
                break

        if not prior:
            return None

        prior_year = prior["year"]
        src = f"https://data.brreg.no/regnskapsregisteret/regnskap"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        parts = [f"Financial comparison: {prior_year} vs {latest_year}"]
        metrics = []

        def fmt(val):
            if val is None:
                return "N/A"
            if abs(val) >= 1_000_000_000:
                return f"{val/1e9:.1f}B NOK"
            if abs(val) >= 1_000_000:
                return f"{val/1e6:.1f}M NOK"
            return f"{val:,.0f} NOK"

        def pct_change(old, new):
            if old and old != 0 and new is not None:
                return ((new - old) / abs(old)) * 100
            return None

        # Revenue
        curr_rev = accounts.revenue.value if accounts.revenue else None
        prev_rev = prior.get("revenue")
        if curr_rev is not None or prev_rev is not None:
            yoy = pct_change(prev_rev, curr_rev)
            yoy_str = f" ({yoy:+.1f}%)" if yoy is not None else ""
            metrics.append(f"Revenue: {fmt(prev_rev)} -> {fmt(curr_rev)}{yoy_str}")

        # Operating profit
        curr_op = accounts.operating_profit.value if accounts.operating_profit else None
        prev_op = prior.get("operating_profit")
        if curr_op is not None or prev_op is not None:
            yoy = pct_change(prev_op, curr_op)
            yoy_str = f" ({yoy:+.1f}%)" if yoy is not None else ""
            metrics.append(f"Operating result: {fmt(prev_op)} -> {fmt(curr_op)}{yoy_str}")

        # Total assets
        curr_assets = accounts.total_assets.value if accounts.total_assets else None
        prev_assets = prior.get("total_assets")
        if curr_assets is not None or prev_assets is not None:
            yoy = pct_change(prev_assets, curr_assets)
            yoy_str = f" ({yoy:+.1f}%)" if yoy is not None else ""
            metrics.append(f"Total assets: {fmt(prev_assets)} -> {fmt(curr_assets)}{yoy_str}")

        # Net income
        curr_net = accounts.net_income.value if accounts.net_income else None
        prev_net = prior.get("net_income")
        if curr_net is not None or prev_net is not None:
            yoy = pct_change(prev_net, curr_net)
            yoy_str = f" ({yoy:+.1f}%)" if yoy is not None else ""
            metrics.append(f"Net income: {fmt(prev_net)} -> {fmt(curr_net)}{yoy_str}")

        if not metrics:
            return None

        summary_text = parts[0] + ". " + "; ".join(metrics) + "."

        return {
            "text": summary_text,
            "latest_year": latest_year,
            "prior_year": prior_year,
            "metrics": metrics,
            "source_url": src,
            "date": now[:10],
            "retrieved_at": now,
        }

