"""Large demo team #7 - quarterly revenue report, a data/ML reporting pipeline (33 nodes, spec FR-E1).

request -> FX rates (tool) || four source extractors, each with a schema check -> merge -> dedupe -> currency
conversion -> outlier filter -> segment join -> three aggregations in parallel -> anomaly / concentration / growth /
forecast -> data-quality gate (conditional: clean pass or warning note) -> LLM narrative -> narrative check ->
two chart specs in parallel -> QA -> tables -> publish. Fault flags are NOT prefixed with the node (a node map is
needed, like order_desk). The only model call is `narrative_llm` (echo stub, STUB_URL).

Loaded by path by ``langgraph dev``; reaches `_kit.py` through sys.path.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import Context, Pipeline, ask_llm  # noqa: E402,F401

INPUT = {"period": "2026-Q3",
         "crm": "acme,2026-07,1000.00,USD;acme,2026-08,1200.00,USD;beta,2026-07,800.00,EUR;beta,2026-08,900.00,EUR;"
                "gamma,2026-09,500.00,GBP",
         "billing": "acme,2026-07,1000.00,USD;delta,2026-09,2000.00,USD;beta,2026-09,950.00,EUR",
         "webstore": "web,2026-07,300.00,USD;web,2026-08,320.00,USD;web,2026-09,340.00,USD",
         "refunds": "acme,2026-08,-200.00,USD"}
RATES = {"USD": 1.0, "EUR": 1.10, "GBP": 1.25}
SEGMENT = {"acme": "enterprise", "beta": "mid", "gamma": "mid", "delta": "enterprise", "web": "self-serve"}
PRIOR_QUARTER = 7000.0

P = Pipeline("period crm billing webstore refunds months rates raw_crm raw_billing raw_web raw_refunds ok_crm ok_billing ok_web ok_refunds rej_crm rej_billing "
             "merged deduped usd kept dropped segmented by_month by_segment total anomalies top_customer growth "
             "forecast gate gate_note prep summary_raw summary charts_month charts_segment qa tables")


def parse(text):
    return [{"customer": c, "month": m, "amount": float(a), "ccy": k}
            for c, m, a, k in (row.split(",") for row in text.split(";"))]


def check_rows(rows, months, f_range=True):
    good = [r for r in rows if r["ccy"] in RATES and (not f_range or r["month"] in months)]
    return good, len(rows) - len(good)


@P.node("report_request", prefixed=False, faults={"quarter_off_by_one": "Takes the quarter's months one month early (06-08)"})
def report_request(s, f):
    q = int(s["period"][-1])
    first = 3 * (q - 1) + (0 if f("quarter_off_by_one") else 1)
    return {"months": [f"{s['period'][:4]}-{m:02d}" for m in range(first, first + 3)]}


@P.node("fx_rates", after="report_request", kind="tool", prefixed=False,
        faults={"stale_eur_rate": "Serves a stale EUR rate of 1.0", "gbp_inverted": "Serves GBP as 1/1.25 (inverted quote)"})
def fx_rates(s, f):
    r = dict(RATES)
    if f("stale_eur_rate"):
        r["EUR"] = 1.0
    if f("gbp_inverted"):
        r["GBP"] = round(1 / 1.25, 4)
    return {"rates": r}


@P.node("extract_crm", after="report_request", kind="tool", prefixed=False, harmless=["skip_first_row"],
        faults={"skip_first_row": "Treats the first CRM row as a header and drops it"})
def extract_crm(s, f):
    rows = parse(s["crm"])
    return {"raw_crm": rows[1:] if f("skip_first_row") else rows}


@P.node("extract_billing", after="report_request", kind="tool", prefixed=False,
        faults={"swap_cols": "Reads the customer and currency columns swapped"})
def extract_billing(s, f):
    rows = parse(s["billing"])
    if f("swap_cols"):
        rows = [{**r, "customer": r["ccy"], "ccy": r["customer"]} for r in rows]
    return {"raw_billing": rows}


@P.node("extract_webstore", after="report_request", kind="tool", prefixed=False,
        faults={"drop_last_month": "Drops the last month of web-store sales (partial export)"})
def extract_webstore(s, f):
    rows = parse(s["webstore"])
    return {"raw_web": rows[:-1] if f("drop_last_month") else rows}


@P.node("extract_refunds", after="report_request", kind="tool", prefixed=False,
        faults={"sign_flip": "Stores refunds as positive amounts"})
def extract_refunds(s, f):
    rows = parse(s["refunds"])
    return {"raw_refunds": [{**r, "amount": abs(r["amount"])} for r in rows] if f("sign_flip") else rows}


@P.node("validate_crm", after="extract_crm", prefixed=False, harmless=["lenient_currency"],
        faults={"lenient_currency": "Accepts unknown currency codes"})
def validate_crm(s, f):
    good, bad = check_rows(s["raw_crm"], s["months"])
    return {"ok_crm": good, "rej_crm": bad}


@P.node("validate_billing", after="extract_billing", prefixed=False,
        faults={"month_boundary": "Rejects rows in the quarter's last month (off-by-one on the range)"})
def validate_billing(s, f):
    months = s["months"][:-1] if f("month_boundary") else s["months"]
    good, bad = check_rows(s["raw_billing"], months)
    return {"ok_billing": good, "rej_billing": bad}


@P.node("validate_webstore", after="extract_webstore", prefixed=False, harmless=["no_range_check"],
        faults={"no_range_check": "Skips the month-range check"})
def validate_webstore(s, f):
    good, bad = check_rows(s["raw_web"], s["months"], not f("no_range_check"))
    return {"ok_web": good}


@P.node("validate_refunds", after="extract_refunds", prefixed=False, faults={"drops_negatives": "Rejects negative amounts as invalid"})
def validate_refunds(s, f):
    rows = [r for r in s["raw_refunds"] if not (f("drops_negatives") and r["amount"] < 0)]
    return {"ok_refunds": rows}


@P.node("merge_sources", after=["validate_crm", "validate_billing", "validate_webstore", "validate_refunds"], prefixed=False,
        faults={"drop_refunds": "Leaves the refunds feed out of the merge"})
def merge_sources(s, f):
    return {"merged": s["ok_crm"] + s["ok_billing"] + s["ok_web"] + ([] if f("drop_refunds") else s["ok_refunds"])}


@P.node("dedupe", after="merge_sources", prefixed=False,
        faults={"drop_all_dupes": "Removes every copy of a duplicated row, not all but one",
                "key_ignores_month": "Dedupe key leaves the month out, so repeat customers collapse"})
def dedupe(s, f):
    key = (lambda r: (r["customer"], r["ccy"])) if f("key_ignores_month") else (lambda r: (r["customer"], r["month"], r["amount"], r["ccy"]))
    counts = {}
    for r in s["merged"]:
        counts[key(r)] = counts.get(key(r), 0) + 1
    seen, out = set(), []
    for r in s["merged"]:
        if (f("drop_all_dupes") and counts[key(r)] > 1) or key(r) in seen:
            continue
        seen.add(key(r))
        out.append(r)
    return {"deduped": out}


@P.node("currency_convert", after=["dedupe", "fx_rates"], prefixed=False,
        faults={"round_rate": "Rounds every exchange rate to one decimal place"})
def currency_convert(s, f):
    rate = lambda c: round(s["rates"][c], 1) if f("round_rate") else s["rates"][c]
    return {"usd": [{**r, "amount": round(r["amount"] * rate(r["ccy"]), 2), "ccy": "USD"} for r in s["deduped"]]}


@P.node("outlier_filter", after="currency_convert", prefixed=False,
        faults={"cap_1000": "Drops every row above 1000 USD as an outlier (limit should be 5000)"})
def outlier_filter(s, f):
    limit = 1000 if f("cap_1000") else 5000
    kept = [r for r in s["usd"] if abs(r["amount"]) <= limit]
    return {"kept": kept, "dropped": len(s["usd"]) - len(kept)}


@P.node("join_segments", after="outlier_filter", kind="tool", prefixed=False,
        faults={"stale_segments": "Uses last year's segment table, where beta is still enterprise"})
def join_segments(s, f):
    seg = dict(SEGMENT, beta="enterprise") if f("stale_segments") else SEGMENT
    return {"segmented": [{**r, "segment": seg[r["customer"]]} for r in s["kept"]]}


@P.node("agg_month", after="join_segments", prefixed=False, faults={"sum_abs": "Sums absolute amounts, so refunds add revenue"})
def agg_month(s, f):
    out = {m: 0.0 for m in s["months"]}
    for r in s["segmented"]:
        if r["month"] in out:
            out[r["month"]] += abs(r["amount"]) if f("sum_abs") else r["amount"]
    return {"by_month": {m: round(v, 2) for m, v in out.items()}}


@P.node("agg_segment", after="join_segments", prefixed=False, faults={"drop_selfserve": "Leaves the self-serve segment out"})
def agg_segment(s, f):
    out = {}
    for r in s["segmented"]:
        if not (f("drop_selfserve") and r["segment"] == "self-serve"):
            out[r["segment"]] = round(out.get(r["segment"], 0.0) + r["amount"], 2)
    return {"by_segment": dict(sorted(out.items()))}


@P.node("agg_total", after="join_segments", prefixed=False, faults={"exclude_refunds": "Totals only positive rows"})
def agg_total(s, f):
    return {"total": round(sum(r["amount"] for r in s["segmented"] if not (f("exclude_refunds") and r["amount"] < 0)), 2)}


@P.node("anomaly_month", after=["agg_month"], prefixed=False,
        faults={"mean_not_median": "Compares months with 1.5x the mean instead of 1.5x the median"})
def anomaly_month(s, f):
    vals = sorted(s["by_month"].values())
    base = sum(vals) / len(vals) if f("mean_not_median") else vals[len(vals) // 2]
    return {"anomalies": [f"{m} ({v / base:.2f}x {'mean' if f('mean_not_median') else 'median'})"
                          for m, v in s["by_month"].items() if v > 1.5 * base]}


@P.node("anomaly_concentration", after=["join_segments"], prefixed=False, harmless=["share_30"],
        faults={"share_30": "Concentration alert at 30% instead of 40% (alert text is not part of the checked report)"})
def anomaly_concentration(s, f):
    per = {}
    for r in s["segmented"]:
        per[r["customer"]] = per.get(r["customer"], 0.0) + r["amount"]
    top = max(per, key=lambda c: per[c])
    return {"top_customer": f"{top} ({100 * per[top] / sum(per.values()):.1f}%)"}


@P.node("growth_qoq", after="agg_total", prefixed=False, faults={"wrong_prior": "Compares with 7500 (last year's Q3) instead of last quarter"})
def growth_qoq(s, f):
    prior = 7500.0 if f("wrong_prior") else PRIOR_QUARTER
    return {"growth": round(100 * (s["total"] - prior) / prior, 1)}


@P.node("forecast_next", after="growth_qoq", prefixed=False, faults={"no_dampening": "Extrapolates the full growth rate instead of half"})
def forecast_next(s, f):
    return {"forecast": round(s["total"] * (1 + s["growth"] / 100 * (1 if f("no_dampening") else 0.5)), 2)}


@P.node("quality_gate", after=["anomaly_month", "anomaly_concentration", "forecast_next", "agg_segment", "validate_billing",
                                "validate_crm"], route=lambda s: s["gate"], to={"ok": "clean_pass", "warn": "quality_note"},
        prefixed=False, faults={"always_warn": "A debug override sends every run down the warning path",
                                "drop_limit_5pct": "Warns when more than 5% of rows are dropped (limit should be 20%)"})
def quality_gate(s, f):
    lost = s["rej_crm"] + s["rej_billing"] + s["dropped"] + len(s["merged"]) - len(s["deduped"])
    n = len(s["usd"]) or 1
    bad = f("always_warn") or lost / n > (0.05 if f("drop_limit_5pct") else 0.20)
    return {"gate": "warn" if bad else "ok", "gate_note": f"{lost} rows lost of {n}"}


@P.node("clean_pass", after="quality_gate", prefixed=False)
def clean_pass(s, f):
    return {"prep": "data-quality gate passed"}


@P.node("quality_note", after="quality_gate", prefixed=False, harmless=["wrong_text"], faults={"wrong_text": "Warning text names the wrong source"})
def quality_note(s, f):
    return {"prep": "DATA QUALITY WARNING: " + ("web feed" if f("wrong_text") else s["gate_note"])}


@P.node("narrative_prep", any_of=["clean_pass", "quality_note"], prefixed=False,
        faults={"drop_forecast_fact": "Leaves the forecast out of the facts handed to the narrative"})
def narrative_prep(s, f):
    facts = f"total {s['total']:.2f}; growth {s['growth']:+.1f}%"
    return {"summary_raw": facts if f("drop_forecast_fact") else facts + f"; forecast {s['forecast']:.2f}"}


@P.node("narrative_llm", after="narrative_prep", kind="llm", prefixed=False,
        faults={"terse_instruction": "Prepends a prompt instruction, changing the model request"})
def narrative_llm(s, f):
    return {"summary": ask_llm(("Answer briefly: " if f("terse_instruction") else "") + f"Write an executive summary for {s['period']}")}


@P.node("narrative_check", after="narrative_llm", prefixed=False, faults={"always_fallback": "Replaces every summary with the fallback text"})
def narrative_check(s, f):
    ok = s["period"] in s["summary"] and not f("always_fallback")
    return {"summary": s["summary"] + " | " + s["summary_raw"] if ok else "Summary unavailable."}


@P.node("chart_revenue", after="narrative_check", prefixed=False, faults={"drop_last_bar": "Plots only the first two months"})
def chart_revenue(s, f):
    bars = list(s["by_month"].values())[:2 if f("drop_last_bar") else 3]
    return {"charts_month": f"revenue_by_month({len(bars)} bars)"}


@P.node("chart_segments", after="narrative_check", prefixed=False, harmless=["default_palette"],
        faults={"default_palette": "Uses the default palette (cosmetic)"})
def chart_segments(s, f):
    return {"charts_segment": f"segments({len(s['by_segment'])} slices)"}


@P.node("qa_checks", after=["chart_revenue", "chart_segments"], prefixed=False, harmless=["skip_reconcile"],
        faults={"skip_reconcile": "Skips the month/segment/total reconciliation"})
def qa_checks(s, f):
    month, seg = round(sum(s["by_month"].values()), 2), round(sum(s["by_segment"].values()), 2)
    passed = 3 if f("skip_reconcile") else 1 + (month == s["total"]) + (seg == s["total"])
    return {"qa": f"QA: passed {passed}/3"}


@P.node("format_tables", after="qa_checks", prefixed=False, faults={"locale_comma": "Formats numbers with a decimal comma"})
def format_tables(s, f):
    num = (lambda v: f"{v:.2f}".replace(".", ",")) if f("locale_comma") else (lambda v: f"{v:.2f}")
    return {"tables": "\n".join([
        f"REPORT {s['period']} | Total: {num(s['total'])} USD | QoQ: {s['growth']:+.1f}%",
        "Months: " + ", ".join(f"{m}={num(v)}" for m, v in s["by_month"].items()),
        "Segments: " + ", ".join(f"{k}={num(v)}" for k, v in s["by_segment"].items()),
        f"Top customer: {s['top_customer']}", "Anomalies: " + (", ".join(s["anomalies"]) or "none"),
        f"Forecast next quarter: {num(s['forecast'])} USD", "Summary: " + s["summary"], s["prep"],
        f"Charts: {s['charts_month']}, {s['charts_segment']}", s["qa"]])}


@P.node("publish", after="format_tables", kind="tool", prefixed=False, faults={"dry_run": "Publishes to the draft folder only"})
def publish(s, f):
    return {"final_output": s["tables"] + ("\nPublished: DRAFT" if f("dry_run") else "\nPublished: OK")}


NODES = P.order
FAULTS = P.faults
graph = P.compile()
CHECK = [
    {"type": "contains", "value": "REPORT 2026-Q3 | Total: 8500.00 USD | QoQ: +21.4%"},
    {"type": "contains", "value": "Months: 2026-07=2180.00, 2026-08=2310.00, 2026-09=4010.00"},
    {"type": "contains", "value": "Segments: enterprise=4000.00, mid=3540.00, self-serve=960.00"},
    {"type": "contains", "value": "Anomalies: 2026-09 (1.74x median)"},
    {"type": "contains", "value": "Forecast next quarter: 9409.50 USD"},
    {"type": "contains", "value": "Summary: echo: Write an executive summary for 2026-Q3 | total 8500.00; growth +21.4%; forecast 9409.50"},
    {"type": "contains", "value": "data-quality gate passed"},
    {"type": "contains", "value": "Charts: revenue_by_month(3 bars), segments(3 slices)"},
    {"type": "contains", "value": "QA: passed 3/3"},
    {"type": "contains", "value": "Published: OK"},
]
