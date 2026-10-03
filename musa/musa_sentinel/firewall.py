"""Payment Firewall: no money moves because an agent recommends it.

PAYMENT REQUEST → IDENTITY → GRAPH → FEE → CASE EVIDENCE → CONTRACT → BENEFICIARY → RISK → DECISION
Decisions: PAY (= approved for human sign-off), HOLD, ESCALATE. Human approval is always required.
"""
from .costs import CostItem, ledger
from .risk import score_signals

PAYMENT_CLASSES = {
    "P0": "No payment", "P1": "Official government payment", "P2": "Regulated/authorised service",
    "P3": "Contractual recruitment payment", "P4": "Professional service",
    "P5": "Unverified intermediary payment", "P6": "Suspicious payment",
}

# The §16 questions, each mapped to the request field that answers it.
PAYMENT_QUESTIONS = [
    ("recipient_name", "WHO receives the money?"),
    ("purpose", "WHY / what service is provided?"),
    ("agreement_ref", "Under which agreement?"),
    ("has_invoice", "Is there an invoice?"),
    ("recipient_is_legal_entity", "Is the recipient the legal entity?"),
    ("refund_terms_defined", "Is refundability defined (what if the visa is refused)?"),
]

REQUIRED_CASE_EVIDENCE = ["oep_verified", "employer_verified", "job_verified", "work_auth_verified", "contract_verified"]


def evaluate(request, graph=None, case_evidence=None, large_payment_eur=500):
    """Evaluate a payment request dict. Returns decision, checks and the reasons."""
    checks, signals, hold, escalate = [], set(), [], []
    case_evidence = case_evidence or {}

    def check(name, ok, why, severity="hold"):
        checks.append({"check": name, "pass": bool(ok), "detail": why})
        if not ok:
            (escalate if severity == "escalate" else hold).append(why)

    # 1. §16 questions
    for field, q in PAYMENT_QUESTIONS:
        check("Q: " + q, request.get(field), "Unanswered: " + q)

    # 2. Beneficiary
    personal = request.get("recipient_type") == "individual" and not request.get("personal_account_justified")
    if personal:
        signals.add("personal_bank_account")
    check("Beneficiary is a company / justified", not personal,
          "Payment to an individual's personal account without documented justification", "escalate")

    cash_combo = request.get("cash_only") and not request.get("has_receipt")
    if request.get("cash_only"):
        signals.add("cash_only")
    if not request.get("has_receipt", True):
        signals.add("no_receipt")
    check("Receipt / non-cash trail", not cash_combo, "Cash without receipt", "escalate")

    if request.get("deadline_pressure"):
        signals.add("urgency_pressure")
        checks.append({"check": "Deadline pressure", "pass": False, "detail": "Urgency claimed — does not change verification requirements"})

    # 3. Payment class
    pclass = request.get("payment_class", "P5")
    check("Payment class", pclass in ("P0", "P1", "P2", "P3", "P4"),
          "Class %s (%s) requires escalation" % (pclass, PAYMENT_CLASSES.get(pclass, "?")), "escalate")

    # 4. Fee intelligence
    items = [CostItem.from_dict(c) for c in request.get("cost_items", [])]
    led = ledger(items, quoted_total=request.get("amount"))
    if led["unverified_amount"] > 0:
        signals.add("unexplained_fee")
    check("Fee fully verified", led["unverified_amount"] == 0,
          "€%.0f of the request is unverified: %s" % (led["unverified_amount"], ", ".join(led["unverified_items"])))

    # 5. Case evidence gate
    missing = [e for e in REQUIRED_CASE_EVIDENCE if not case_evidence.get(e)]
    check("Case evidence gate", not missing, "Case not verified: " + ", ".join(missing))
    if request.get("contract_refused"):
        signals.add("refusal_contract")

    # 6. Reputation graph
    graph_hits = graph.lookup(request.get("recipient_identifiers", {})) if graph else []
    risky = [h for h in graph_hits if h["outcomes"].get("complaints") or h["outcomes"].get("refusals")]
    if len(graph_hits) > 1 or risky:
        signals.add("identity_reuse")
    check("Reputation graph", not (len(graph_hits) > 1 or risky),
          "Recipient identifiers appear on %d known entities%s" % (len(graph_hits), " with adverse outcomes" if risky else ""), "escalate")

    risk = score_signals(signals)
    if risk["score"] >= 40:
        escalate.append("Risk %d (%s)" % (risk["score"], risk["band"]))

    if escalate:
        decision = "ESCALATE"
    elif hold:
        decision = "HOLD"
    else:
        decision = "PAY"

    return {
        "payment_id": request.get("payment_id"),
        "amount": request.get("amount"),
        "decision": decision,
        "requires_human_approval": True,
        "large_payment": (request.get("amount") or 0) >= large_payment_eur,
        "reasons": escalate + hold if decision != "PAY" else ["All firewall checks passed — route to human approver"],
        "checks": checks,
        "fee_ledger": led,
        "graph_hits": graph_hits,
        "risk": risk,
    }
