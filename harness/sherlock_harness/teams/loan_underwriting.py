"""Large demo team #6 - loan underwriting / KYC (34 nodes, spec FR-E1).

application -> three parallel document chains (ID / income / bank statements) -> KYC match, employer check, credit bureau
-> four parallel fraud signals -> aggregate -> payment, DTI, risk score -> policy rules + exposure limit -> decision router
(conditional: approve+pricing / manual referral / decline) -> disclosures -> LLM letter -> ledger -> notify.
Built with `_kit.Pipeline`. The only model call is `letter_draft` (echo stub, STUB_URL).

Loaded by path by ``langgraph dev``; reaches `_kit.py` through sys.path.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import Context, Pipeline, ask_llm  # noqa: E402,F401

INPUT = {"app_id": "APP-77", "applicant": "Mira Haddad", "amount_text": "20,000.00", "term": 36, "device": "DEV-9",
         "id_doc": "ID|MH-4471920|MIRA HADDAD|issued 2021-04-12|expires 2029-06-30",
         "income_doc": "PAYSLIP|Acme Corp|gross 6,500.00 USD|monthly",
         "bank_doc": "2026-07|in 6400.00|out 5000.00|bal 3300.00;2026-08|in 6500.00|out 5400.00|bal 4400.00;"
                     "2026-09|in 6540.00|out 10630.00|bal 310.00"}
TODAY = "2026-10-14"
SANCTIONS = {"IVAN PETROV", "R. KARIM"}
EMPLOYERS = {"acme corp", "globex", "initech"}
BUREAU = {"MH-4471920": {"score": 718, "monthly_debt": 850.0, "util": 0.31, "delinq": 0},
          "XX-0000000": {"score": 590, "monthly_debt": 2100.0, "util": 0.8, "delinq": 2}}
APPS_30D = {"MH-4471920": 1}
DEVICES = {"DEV-9": 1, "DEV-0": 6}
CAP = {"A": 30000.0, "B": 25000.0, "C": 15000.0, "D": 0.0}
APR = {"A": 9.5, "B": 11.5, "C": 14.5, "D": 19.9}
EXPOSURE_LEFT = 400000.0

P = Pipeline("app_id applicant amount_text term device id_doc income_doc bank_doc amount id_fields id_ok income_fields "
             "income_ok employer_ok monthly_income bank_rows bank_ok bank_stats kyc bureau fraud_velocity fraud_device "
             "fraud_mismatch fraud_identity fraud_flag payment dti risk band decision exposure_ok route_to approved "
             "referral decline_codes apr monthly_payment terms disclosure letter_text ledger notice")


def money(text):
    return float(text.replace(",", ""))


@P.node("application_intake", faults={"thousands_sep": "Reads 20,000.00 as 20.0 (stops at the comma)"})
def application_intake(s, f):
    amount = float(s["amount_text"].split(",")[0]) if f("thousands_sep") else money(s["amount_text"])
    return {"amount": amount}


@P.node("id_parse", after="application_intake", faults={"swap_dates": "Swaps issue and expiry dates"})
def id_parse(s, f):
    _, number, name, issued, expires = s["id_doc"].split("|")
    issued, expires = issued.split()[1], expires.split()[1]
    if f("swap_dates"):
        issued, expires = expires, issued
    return {"id_fields": {"number": number, "name": name, "issued": issued, "expires": expires}}


@P.node("id_validate", after="id_parse", harmless=["skip_expiry"],
        faults={"skip_expiry": "Never checks the expiry date"})
def id_validate(s, f):
    expired = s["id_fields"]["expires"] < TODAY and not f("skip_expiry")
    future = s["id_fields"]["issued"] > TODAY and not f("skip_expiry")
    return {"id_ok": not (expired or future)}


@P.node("income_parse", after="application_intake", faults={"comma_split": "Reads 6,500.00 as 6.0"})
def income_parse(s, f):
    _, employer, gross, period = s["income_doc"].split("|")
    raw = gross.split()[1]
    return {"income_fields": {"employer": employer, "gross": float(raw.split(",")[0]) if f("comma_split")
                              else money(raw), "period": period}}


@P.node("income_validate", after="income_parse", faults={"period_blind": "Accepts any pay period, including unknown ones"},
        harmless=["period_blind"])
def income_validate(s, f):
    ok = s["income_fields"]["gross"] > 0 and (f("period_blind") or s["income_fields"]["period"] in ("weekly", "monthly", "annual"))
    return {"income_ok": ok}


@P.node("employer_verify", after="income_validate", kind="tool",
        faults={"stale_registry": "Checks a registry snapshot that lacks the employer"})
def employer_verify(s, f):
    registry = EMPLOYERS - {"acme corp"} if f("stale_registry") else EMPLOYERS
    return {"employer_ok": s["income_fields"]["employer"].lower() in registry}


@P.node("income_normalise", after="employer_verify",
        faults={"net_not_gross": "Uses 78% of gross (an after-tax guess)", "weekly_x4": "Converts weekly pay with x4 instead of x52/12"},
        harmless=["weekly_x4"])
def income_normalise(s, f):
    g, per = s["income_fields"]["gross"], s["income_fields"]["period"]
    monthly = {"monthly": g, "weekly": g * (4 if f("weekly_x4") else 52 / 12), "annual": g / 12}[per]
    return {"monthly_income": round(monthly * (0.78 if f("net_not_gross") else 1.0), 2)}


@P.node("bank_parse", after="application_intake", faults={"credit_debit_swap": "Reads the in and out columns the wrong way round"})
def bank_parse(s, f):
    rows = []
    for row in s["bank_doc"].split(";"):
        month, i, o, b = row.split("|")
        i, o = float(i.split()[1]), float(o.split()[1])
        rows.append({"month": month, "in": o if f("credit_debit_swap") else i, "out": i if f("credit_debit_swap") else o,
                     "bal": float(b.split()[1])})
    return {"bank_rows": rows}


@P.node("bank_validate", after="bank_parse", harmless=["skip_continuity"],
        faults={"skip_continuity": "Never checks that balances roll forward"})
def bank_validate(s, f):
    rows = s["bank_rows"]
    roll = all(round(a["bal"] + b["in"] - b["out"], 2) == b["bal"] for a, b in zip(rows, rows[1:]))
    return {"bank_ok": roll or f("skip_continuity")}


@P.node("bank_summary", after="bank_validate", faults={"max_balance": "Reports the highest balance where the lowest is meant"})
def bank_summary(s, f):
    rows, bals = s["bank_rows"], [r["bal"] for r in s["bank_rows"]]
    return {"bank_stats": {"avg_in": round(sum(r["in"] for r in rows) / len(rows), 2),
                           "min_bal": max(bals) if f("max_balance") else min(bals)}}


@P.node("kyc_match", after="id_validate", kind="tool",
        faults={"exact_case": "Compares names case-sensitively, so MIRA HADDAD never matches Mira Haddad"})
def kyc_match(s, f):
    a, b = s["applicant"], s["id_fields"]["name"]
    same = a == b if f("exact_case") else a.lower() == b.lower()
    status = "clear" if same and s["id_ok"] and b.upper() not in SANCTIONS else "review"
    return {"kyc": status}


@P.node("credit_bureau", after="id_parse", kind="tool",
        faults={"stale_report": "Returns the pre-payoff report (score 640, utilisation 0.8)",
                "thin_file": "Returns an empty tradeline file (no monthly debt)"})
def credit_bureau(s, f):
    rec = dict(BUREAU[s["id_fields"]["number"]])
    if f("stale_report"):
        rec.update(score=640, util=0.8)
    if f("thin_file"):
        rec.update(monthly_debt=0.0)
    return {"bureau": rec}


@P.node("fraud_velocity", after=["kyc_match", "credit_bureau"], harmless=["threshold_one"], faults={"threshold_one": "Flags an applicant seen even once in 30 days"})
def fraud_velocity(s, f):
    return {"fraud_velocity": 2 if APPS_30D[s["id_fields"]["number"]] >= (1 if f("threshold_one") else 3) else 0}


@P.node("fraud_device", after=["kyc_match", "credit_bureau"], harmless=["default_device"], faults={"default_device": "Falls back to the shared default device id"})
def fraud_device(s, f):
    return {"fraud_device": 2 if DEVICES["DEV-0" if f("default_device") else s["device"]] >= 3 else 0}


@P.node("fraud_mismatch", after=["income_normalise", "bank_summary", "credit_bureau"],
        faults={"zero_tolerance": "Requires payslip and bank inflow to match exactly"})
def fraud_mismatch(s, f):
    gap = abs(s["monthly_income"] - s["bank_stats"]["avg_in"]) / max(s["monthly_income"], 1)
    return {"fraud_mismatch": 3 if gap > (0.0 if f("zero_tolerance") else 0.05) else 0}


@P.node("fraud_identity", after=["kyc_match", "credit_bureau"], harmless=["months_as_days"], faults={"months_as_days": "Treats the ID age in months as days"})
def fraud_identity(s, f):
    y, m, d = (int(x) for x in s["id_fields"]["issued"].split("-"))
    age_days = (2026 - y) * 365 + (10 - m) * (1 if f("months_as_days") else 30) + (14 - d)
    return {"fraud_identity": 2 if age_days < 90 else 0}


@P.node("fraud_aggregate", after=["fraud_velocity", "fraud_device", "fraud_mismatch", "fraud_identity"],
        harmless=["threshold_two"], faults={"threshold_two": "Raises the fraud flag at weight 2 instead of 3"})
def fraud_aggregate(s, f):
    total = s["fraud_velocity"] + s["fraud_device"] + s["fraud_mismatch"] + s["fraud_identity"]
    return {"fraud_flag": total >= (2 if f("threshold_two") else 3)}


@P.node("payment_calc", after="fraud_aggregate", faults={"simple_interest": "Uses simple interest instead of an annuity"})
def payment_calc(s, f):
    p, n, r = s["amount"], s["term"], 0.09 / 12
    pay = p * (1 + 0.09 * n / 12) / n if f("simple_interest") else p * r / (1 - (1 + r) ** -n)
    return {"payment": round(pay, 2)}


@P.node("dti_calc", after=["payment_calc", "income_normalise"], faults={"omit_existing_debt": "Leaves existing monthly debt out"})
def dti_calc(s, f):
    debt = 0.0 if f("omit_existing_debt") else s["bureau"]["monthly_debt"]
    return {"dti": round((debt + s["payment"]) / s["monthly_income"], 2)}


@P.node("risk_score", after=["dti_calc", "bank_summary", "employer_verify"], harmless=["util_cutoff"],
        faults={"min_balance_x4": "Weights a thin balance four times too heavily",
                "util_cutoff": "Penalises utilisation above 0.3 instead of 0.5"})
def risk_score(s, f):
    b, pts = s["bureau"], 0
    pts += 0 if b["score"] >= 740 else 10 if b["score"] >= 700 else 20 if b["score"] >= 660 else 35
    pts += 0 if s["dti"] < 0.3 else 10 if s["dti"] < 0.4 else 25
    pts += 10 if b["util"] > (0.3 if f("util_cutoff") else 0.5) else 0
    pts += 15 * b["delinq"] + (15 if not s["employer_ok"] else 0)
    pts += (40 if f("min_balance_x4") else 10) if s["bank_stats"]["min_bal"] < 500 else 0
    return {"risk": pts, "band": "A" if pts <= 10 else "B" if pts <= 30 else "C" if pts <= 50 else "D"}


@P.node("policy_rules", after=["risk_score", "fraud_aggregate"], harmless=["kyc_ignored"],
        faults={"dti_limit_low": "Uses a 0.20 DTI limit instead of 0.43", "kyc_ignored": "Forgets to require KYC clear",
                "min_score_high": "Uses a minimum score of 740 instead of 620"})
def policy_rules(s, f):
    if s["dti"] > (0.20 if f("dti_limit_low") else 0.43) or s["bureau"]["score"] < (740 if f("min_score_high") else 620) or s["band"] == "D":
        return {"decision": "decline"}
    if s["fraud_flag"] or (s["kyc"] != "clear" and not f("kyc_ignored")):
        return {"decision": "refer"}
    return {"decision": "approve"}


@P.node("limit_check", after="policy_rules", kind="tool", faults={"stale_exposure": "Reads last quarter's remaining exposure (10,000)"})
def limit_check(s, f):
    return {"exposure_ok": s["amount"] <= (10000.0 if f("stale_exposure") else EXPOSURE_LEFT)}


@P.node("decision_router", after="limit_check", route=lambda s: s["route_to"],
        to={"approve": "approve_terms", "refer": "manual_referral", "decline": "decline_reason"},
        faults={"always_refer": "Sends every approval to manual review"})
def decision_router(s, f):
    d = s["decision"] if s["exposure_ok"] or s["decision"] != "approve" else "refer"
    return {"route_to": "refer" if f("always_refer") and d == "approve" else d}


@P.node("approve_terms", after="decision_router",
        faults={"band_shift": "Looks the amount cap up under the next band down"})
def approve_terms(s, f):
    band = {"A": "B", "B": "C", "C": "D", "D": "D"}[s["band"]] if f("band_shift") else s["band"]
    return {"approved": min(s["amount"], CAP[band])}


@P.node("manual_referral", after="decision_router", harmless=["wrong_queue"], faults={"wrong_queue": "Files referrals in the fraud queue"})
def manual_referral(s, f):
    return {"referral": "FRAUD-OPS" if f("wrong_queue") else "UW-REVIEW", "approved": 0.0}


@P.node("decline_reason", after="decision_router", harmless=["wrong_code"], faults={"wrong_code": "Prints reason code D9 for every decline"})
def decline_reason(s, f):
    codes = [c for c, hit in (("D1-DTI", s["dti"] > 0.43), ("D2-SCORE", s["bureau"]["score"] < 620),
                              ("D3-BAND", s["band"] == "D")) if hit]
    return {"decline_codes": ["D9"] if f("wrong_code") else codes, "approved": 0.0}


@P.node("pricing", after="approve_terms", faults={"term_surcharge": "Adds the long-term surcharge from 36 months instead of over 48",
                                                  "floor_payment": "Floors the monthly payment to whole units"})
def pricing(s, f):
    apr = APR[s["band"]] + (0.5 if s["term"] >= 36 and f("term_surcharge") or s["term"] > 48 else 0)
    r, n = apr / 1200, s["term"]
    pay = s["approved"] * r / (1 - (1 + r) ** -n)
    return {"apr": apr, "monthly_payment": float(int(pay)) if f("floor_payment") else round(pay, 2)}


@P.node("disclosures", any_of=["pricing", "manual_referral", "decline_reason"],
        faults={"monthly_rate_as_apr": "Prints the monthly rate where the APR is meant"})
def disclosures(s, f):
    if s["decision"] == "approve" and s["route_to"] == "approve":
        apr = round(s["apr"] / 12, 2) if f("monthly_rate_as_apr") else s["apr"]
        return {"terms": f"Amount: {s['approved']:.2f} USD at {apr:.2f}% APR for {s['term']} months | "
                         f"Payment: {s['monthly_payment']:.2f}",
                "disclosure": "Total cost shown is an estimate; rates are fixed for the term."}
    if s["route_to"] == "refer":
        return {"terms": f"Referred to {s['referral']}", "disclosure": "A reviewer will contact you within 2 days."}
    return {"terms": "Reasons: " + ", ".join(s["decline_codes"]),
            "disclosure": "You may request the credit report used for this decision."}


@P.node("letter_draft", after="disclosures", kind="llm", faults={"terse_instruction": "Prepends a prompt instruction, changing the model request"})
def letter_draft(s, f):
    return {"letter_text": ask_llm(("Answer briefly: " if f("terse_instruction") else "") + f"Write a formal letter for {s['applicant']}")}


@P.node("letter_assemble", after="letter_draft", faults={"wrong_salutation": "Greets the applicant by the wrong name part"})
def letter_assemble(s, f):
    name = s["applicant"].split()[0] if f("wrong_salutation") else "Ms " + s["applicant"].split()[-1]
    return {"letter_text": f"Dear {name},\n{s['letter_text']}"}


@P.node("ledger_write", after="letter_assemble", harmless=["requested_not_approved"],
        faults={"requested_not_approved": "Books the requested amount instead of the approved one",
                "drop_decision": "Writes the ledger row without the decision"})
def ledger_write(s, f):
    booked = s["amount"] if f("requested_not_approved") else s["approved"]
    return {"ledger": f"LEDGER|{s['app_id']}|{'' if f('drop_decision') else s['decision']}|{booked:.2f}"}


@P.node("notify", after="ledger_write", kind="tool", faults={"silent_mode": "Queues the notice instead of sending it"})
def notify(s, f):
    head = f"Application {s['app_id']} | Decision: {s['decision'].upper()} | Band: {s['band']}"
    mid = f"KYC: {s['kyc']} | Fraud: {'flagged' if s['fraud_flag'] else 'low'} | DTI: {s['dti']:.2f}"
    return {"final_output": "\n".join([head, s["terms"], mid, s["letter_text"], s["disclosure"], s["ledger"],
                                       "Status: " + ("QUEUED" if f("silent_mode") else "NOTIFIED")])}


NODES = P.order
FAULTS = P.faults
graph = P.compile()
CHECK = [
    {"type": "contains", "value": "Application APP-77 | Decision: APPROVE | Band: B"},
    {"type": "contains", "value": "Amount: 20000.00 USD at 11.50% APR for 36 months | Payment: 659.52"},
    {"type": "contains", "value": "KYC: clear | Fraud: low | DTI: 0.23"},
    {"type": "contains", "value": "Dear Ms Haddad,\necho: Write a formal letter for Mira Haddad"},
    {"type": "contains", "value": "LEDGER|APP-77|approve|20000.00"},
    {"type": "contains", "value": "Status: NOTIFIED"},
]
