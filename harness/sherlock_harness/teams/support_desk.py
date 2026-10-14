"""Large demo team #5 - support desk, a customer-support escalation pipeline (33 nodes, spec FR-E1).

intake -> text clean-up -> [language || PII redaction || intent || sentiment] with [customer || order] lookups in
parallel -> urgency -> priority router (conditional: P1 escalation or P2 standard SLA) -> queue -> three retrieval
chains in parallel (FAQ / product docs / past tickets) beside a duplicate-charge check -> merge + rerank -> policy
-> refund calculator -> LLM draft -> tone -> compliance -> disclaimer -> approval gate -> audit -> send.
Built with `_kit.Pipeline`. The only model call is `draft_reply` (echo stub, STUB_URL).

Loaded by path by ``langgraph dev``; reaches `_kit.py` through sys.path.
"""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _kit import Context, Pipeline, ask_llm  # noqa: E402,F401

INPUT = {"ticket_id": "T-9001", "customer_id": "C-1042",
         "ticket": "Order A-5531 arrived damaged and I was charged 120.00 EUR twice. Please refund me urgently. "
                   "Email ana.ruiz@example.com, card 4111 1111 1111 1111."}
CUSTOMERS = {"C-1042": {"name": "Ana", "tier": "gold", "region": "EU", "currency": "EUR"},
             "C-2001": {"name": "Bo", "tier": "standard", "region": "US", "currency": "USD"}}
ORDERS = {"A-5531": {"customer": "C-1042", "total": 120.0, "currency": "EUR", "charges": 2, "days": 12}}
STOPWORDS = {"en": {"the", "and", "was", "me", "please", "i", "my", "arrived"}, "es": {"el", "la", "y", "mi", "por"},
             "fr": {"le", "et", "mon", "pour", "je"}}
INTENTS = {"refund": {"refund", "charged", "money"}, "shipping": {"delivery", "tracking", "shipping"},
           "technical": {"error", "crash", "login"}}
NEG = {"damaged", "twice", "urgently", "angry", "broken"}
ONCALL = {"EU": "eu-oncall", "US": "us-oncall"}
FAQ = {"FAQ-17": {"refund", "charged", "damaged"}, "FAQ-02": {"delivery", "tracking"}, "FAQ-31": {"login", "password"},
       "FAQ-09": {"invoice", "vat"},
       "FAQ-21": {"card", "email"}, "FAQ-33": {"charged", "twice"}}
DOCS = {"KB-8": {"damaged", "return", "refund"}, "KB-3": {"invoice", "billing"}, "KB-5": {"warranty", "repair"}}
PAST = {"T-7710": {"customer": "C-1042", "intent": "refund", "days": 30}, "T-5512": {"customer": "C-2001",
        "intent": "refund", "days": 5}, "T-4001": {"customer": "C-1042", "intent": "shipping", "days": 90}}
AUTO_LIMIT = {"gold": 200.0, "standard": 100.0}
DISCLAIMER = {"EU": "Statutory rights under EU Directive 2011/83 apply.", "US": "Offer valid under US consumer law."}

P = Pipeline("ticket_id customer_id ticket order_ref claimed clean lang redacted pii_count intent sentiment customer "
             "order score priority route_reason sla_hours oncall queue faq_hits faq_scored doc_hits doc_scored "
             "past_hits past_scored merged top_ids policy dup_amount refund refund_text draft body compliance "
             "disclaimer approval audit report")


@P.node("intake", faults={"ref_lowercase": "Lower-cases the order reference, so the order lookup misses"})
def intake(s, f):
    ref = re.search(r"[A-Z]-\d{4}", s["ticket"]).group(0)
    amount = float(re.search(r"(\d+\.\d{2}) [A-Z]{3}", s["ticket"]).group(1))
    return {"order_ref": ref.lower() if f("ref_lowercase") else ref, "claimed": amount}


@P.node("normalize_text", after="intake", harmless=["keep_case"],
        faults={"keep_case": "Leaves the original capitalisation (every matcher lower-cases anyway)"})
def normalize_text(s, f):
    text = re.sub(r"\s+", " ", s["ticket"]).strip()
    return {"clean": text if f("keep_case") else text.lower()}


@P.node("lang_detect", after="normalize_text", faults={"swap_codes": "Reports Spanish for English text"})
def lang_detect(s, f):
    tokens = set(re.findall(r"[a-z]+", s["clean"].lower()))
    best = max(STOPWORDS, key=lambda k: (len(tokens & STOPWORDS[k]), k == "en"))
    return {"lang": "es" if f("swap_codes") and best == "en" else best}


@P.node("pii_redact", after="normalize_text", harmless=["miss_card"],
        faults={"miss_card": "Only masks dash-separated card numbers, so a spaced card number survives"})
def pii_redact(s, f):
    text = re.sub(r"[\w.]+@[\w.]+", "[EMAIL]", s["ticket"])
    pattern = r"\b(?:\d{4}-){3}\d{4}\b" if f("miss_card") else r"\b(?:\d{4}[ -]?){3}\d{4}\b"
    text, n = re.subn(pattern, "[CARD]", text)
    return {"redacted": text, "pii_count": n + len(re.findall(r"[\w.]+@[\w.]+", s["ticket"]))}


@P.node("intent_classify", after="normalize_text",
        faults={"bias_shipping": "Counts the word 'order' as a shipping keyword, so refunds read as shipping"})
def intent_classify(s, f):
    tokens = set(re.findall(r"[a-z]+", s["clean"].lower()))
    scores = {k: len(tokens & v) for k, v in INTENTS.items()}
    if f("bias_shipping") and "order" in tokens:
        scores["shipping"] += 3
    return {"intent": max(scores, key=lambda k: (scores[k], k == "refund"))}


@P.node("sentiment", after="normalize_text", faults={"inverted_scale": "Flips the sign of the sentiment score"})
def sentiment(s, f):
    tokens = re.findall(r"[a-z]+", s["clean"].lower())
    score = -sum(t in NEG for t in tokens)
    return {"sentiment": -score if f("inverted_scale") else score}


@P.node("customer_lookup", after="intake", kind="tool",
        faults={"stale_cache": "Serves a cached profile from before the customer's upgrade (tier standard)"})
def customer_lookup(s, f):
    c = dict(CUSTOMERS[s["customer_id"]])
    if f("stale_cache"):
        c["tier"] = "standard"
    return {"customer": c}


@P.node("order_lookup", after="intake", kind="tool",
        faults={"timeout": "The orders API times out and the node raises",
                "wrong_currency": "Reads the order in the wrong currency (USD)"})
def order_lookup(s, f):
    if f("timeout"):
        raise TimeoutError("orders-api: read timed out after 5s")
    o = dict(ORDERS[s["order_ref"]])
    if f("wrong_currency"):
        o["currency"] = "USD"
    return {"order": o}


@P.node("urgency", after=["sentiment", "customer_lookup"],
        faults={"threshold_off": "Escalation threshold set to 6 instead of 4"})
def urgency(s, f):
    score = 2 * (s["sentiment"] < 0) + {"gold": 2, "standard": 0}[s["customer"]["tier"]] + ("urgent" in s["clean"].lower())
    return {"score": score, "priority": "p1" if score >= (6 if f("threshold_off") else 4) else "p2"}


@P.node("priority_router", after="urgency", route=lambda s: s["priority"],
        to={"p1": "escalate", "p2": "sla_standard"},
        faults={"stuck_p2": "A feature flag forces every ticket onto the standard queue"})
def priority_router(s, f):
    return {"priority": "p2" if f("stuck_p2") else s["priority"], "route_reason": f"score={s['score']}"}


@P.node("escalate", after="priority_router", faults={"wrong_oncall": "Pages the US rota whatever the region"})
def escalate(s, f):
    return {"sla_hours": 1, "oncall": ONCALL["US" if f("wrong_oncall") else s["customer"]["region"]]}


@P.node("sla_standard", after="priority_router", harmless=["hours_typo"], faults={"hours_typo": "SLA typed as 36 hours instead of 24"})
def sla_standard(s, f):
    return {"sla_hours": 36 if f("hours_typo") else 24, "oncall": "none"}


@P.node("queue_assign", any_of=["escalate", "sla_standard"],
        faults={"drop_region": "Builds the queue name without the region suffix"})
def queue_assign(s, f):
    region = "" if f("drop_region") else "-" + s["customer"]["region"]
    return {"queue": s["priority"].upper() + region}


def _terms(s):
    return set(re.findall(r"[a-z]+", s["clean"].lower()))


@P.node("faq_search", after="queue_assign", kind="tool", faults={"stale_index": "Searches an index that predates FAQ-17"})
def faq_search(s, f):
    pool = {k: v for k, v in FAQ.items() if not (f("stale_index") and k == "FAQ-17")}
    return {"faq_hits": sorted(((k, len(v & _terms(s))) for k, v in pool.items() if v & _terms(s)))}


@P.node("faq_score", after="faq_search", faults={"no_normalise": "Skips score normalisation, so FAQ scores swamp the others"})
def faq_score(s, f):
    top = max((n for _, n in s["faq_hits"]), default=1)
    return {"faq_scored": [(k, float(n) if f("no_normalise") else round(n / top, 2)) for k, n in s["faq_hits"]]}


@P.node("docs_search", after="queue_assign", kind="tool",
        faults={"wrong_product_line": "Filters on the billing product line instead of returns"})
def docs_search(s, f):
    pool = {k: v for k, v in DOCS.items() if (k == "KB-3") == f("wrong_product_line")}
    return {"doc_hits": sorted(((k, len(v & _terms(s))) for k, v in pool.items() if v & _terms(s)))}


@P.node("docs_score", after="docs_search", faults={"skip_boost": "Forgets the damage-claim boost"})
def docs_score(s, f):
    boost = 0.0 if f("skip_boost") else 0.5
    return {"doc_scored": [(k, round(n / 3 + boost * ("damaged" in s["clean"].lower()), 2)) for k, n in s["doc_hits"]]}


@P.node("history_search", after="queue_assign", kind="tool",
        faults={"other_customer": "Filters past tickets by the wrong customer id"})
def history_search(s, f):
    who = "C-2001" if f("other_customer") else s["customer_id"]
    return {"past_hits": [(k, v["days"]) for k, v in sorted(PAST.items()) if v["customer"] == who and v["intent"] == s["intent"]]}


@P.node("history_score", after="history_search", faults={"inverted_decay": "Prefers the oldest tickets instead of the newest"})
def history_score(s, f):
    return {"past_scored": [(k, round(1 - (d if not f("inverted_decay") else 100 - d) / 100, 2)) for k, d in s["past_hits"]]}


@P.node("merge_results", after=["faq_score", "docs_score", "history_score"],
        faults={"drop_history": "Leaves the past-ticket results out of the merge"})
def merge_results(s, f):
    parts = s["faq_scored"] + s["doc_scored"] + ([] if f("drop_history") else s["past_scored"])
    return {"merged": [list(p) for p in parts]}


@P.node("rerank", after="merge_results", faults={"ascending": "Sorts ascending, so the weakest three survive"})
def rerank(s, f):
    ranked = sorted(s["merged"], key=lambda p: (p[1] if f("ascending") else -p[1], p[0]))
    return {"top_ids": list(dict.fromkeys(p[0] for p in ranked))[:3]}


@P.node("policy_check", after=["rerank", "order_lookup"],
        faults={"short_window": "Refund window set to 7 days instead of 30"})
def policy_check(s, f):
    window = 7 if f("short_window") else (45 if s["customer"]["tier"] == "gold" else 30)
    return {"policy": {"eligible": s["order"]["days"] <= window, "window": window}}


@P.node("dup_charge_check", after="queue_assign", kind="tool",
        faults={"ignore_second_charge": "Counts only one charge, so no duplicate is found"})
def dup_charge_check(s, f):
    extra = 0 if f("ignore_second_charge") else s["order"]["charges"] - 1
    return {"dup_amount": round(s["order"]["total"] * extra, 2)}


@P.node("refund_calc", after=["policy_check", "dup_charge_check"],
        faults={"cap_off": "Caps refunds at 100 instead of the tier limit", "truncate": "Truncates the refund to whole units"})
def refund_calc(s, f):
    if not s["policy"]["eligible"]:
        return {"refund": 0.0}
    amount = s["dup_amount"] + (4.5 if "damaged" in s["clean"].lower() and s["dup_amount"] else 0.0)
    amount = min(amount, 100.0 if f("cap_off") else 1000.0)
    return {"refund": float(int(amount)) if f("truncate") else round(amount, 2)}


@P.node("refund_format", after="refund_calc", faults={"wrong_symbol": "Prints the refund in USD whatever the order currency"})
def refund_format(s, f):
    return {"refund_text": f"{s['refund']:.2f} {'USD' if f('wrong_symbol') else s['order']['currency']}"}


@P.node("draft_reply", after=["refund_format", "lang_detect"], kind="llm",
        faults={"terse_instruction": "Prepends a prompt instruction, changing the model request"})
def draft_reply(s, f):
    tone = "empathetic" if s["sentiment"] < 0 else "neutral"
    prompt = f"[{s['lang']}] Write a {tone} reply about {s['intent']}"
    return {"draft": ask_llm(("Answer briefly: " if f("terse_instruction") else "") + prompt)}


@P.node("tone_check", after="draft_reply", faults={"skip_greeting": "Forgets to add the greeting"})
def tone_check(s, f):
    greeting = "" if f("skip_greeting") else f"Dear {s['customer']['name']},\n"
    return {"body": greeting + s["draft"] + "\n> " + s["redacted"]}


@P.node("compliance_check", after=["tone_check", "pii_redact"], harmless=["skip_pii_scan"],
        faults={"skip_pii_scan": "Skips the last-line card-number scan of the outgoing text"})
def compliance_check(s, f):
    body = s["body"] if f("skip_pii_scan") else re.sub(r"\b(?:\d{4}[ -]?){3}\d{4}\b", "[CARD]", s["body"])
    return {"compliance": "ok", "body": body}


@P.node("disclaimer_add", after="compliance_check", faults={"wrong_region_text": "Appends the US disclaimer to every region"})
def disclaimer_add(s, f):
    return {"disclaimer": DISCLAIMER["US" if f("wrong_region_text") else s["customer"]["region"]]}


@P.node("approval_gate", after=["disclaimer_add", "refund_calc"],
        faults={"limit_off": "Uses the standard-tier auto-approval limit for gold customers"})
def approval_gate(s, f):
    limit = AUTO_LIMIT["standard" if f("limit_off") else s["customer"]["tier"]]
    return {"approval": "auto" if s["refund"] <= limit else "manager"}


@P.node("audit_log", after="approval_gate", faults={"drops_ticket_id": "Writes the audit line without the ticket id"})
def audit_log(s, f):
    return {"audit": f"AUDIT|{'' if f('drops_ticket_id') else s['ticket_id']}|{s['intent']}|{s['refund_text']}|{s['approval']}"}


@P.node("assemble", after="audit_log", faults={"drops_sources": "Leaves the cited sources out of the message"})
def assemble(s, f):
    lines = [f"Ticket {s['ticket_id']} | Queue: {s['queue']} | On-call: {s['oncall']} | SLA: {s['sla_hours']}h",
             f"Lang: {s['lang']} | Intent: {s['intent']} | PII masked: {s['pii_count']}"]
    if not f("drops_sources"):
        lines.append("Sources: " + ", ".join(sorted(s["top_ids"])))
    lines += [f"Refund: {s['refund_text']} | Approval: {s['approval']}", s["body"], s["disclaimer"], s["audit"]]
    return {"report": "\n".join(lines)}


@P.node("send", after="assemble", kind="tool", faults={"dry_run": "Runs in dry-run mode and never sends"})
def send(s, f):
    return {"final_output": s["report"] + ("\nStatus: DRY-RUN" if f("dry_run") else "\nStatus: SENT")}


NODES = P.order
FAULTS = P.faults
graph = P.compile()
CHECK = [
    {"type": "contains", "value": "Ticket T-9001 | Queue: P1-EU | On-call: eu-oncall | SLA: 1h"},
    {"type": "contains", "value": "Lang: en | Intent: refund | PII masked:"},
    {"type": "contains", "value": "Sources: FAQ-17, KB-8, T-7710"},
    {"type": "contains", "value": "Refund: 124.50 EUR | Approval: auto"},
    {"type": "contains", "value": "Dear Ana,\necho: [en] Write a empathetic reply about refund"},
    {"type": "contains", "value": "EU Directive 2011/83"},
    {"type": "contains", "value": "AUDIT|T-9001|refund|124.50 EUR|auto"},
    {"type": "contains", "value": "Status: SENT"},
    {"type": "not-contains", "value": "4111"},
]
