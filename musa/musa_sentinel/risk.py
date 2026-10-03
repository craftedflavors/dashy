"""Risk scoring (spec §46), hard stops (§47) and the final decision matrix (§61)."""

RISK_WEIGHTS = {
    "unverifiable_recruiter": 10,
    "missing_oep_licence": 10,
    "oep_mismatch": 15,
    "employer_unverifiable": 15,
    "work_auth_unverifiable": 20,
    "unexplained_fee": 10,
    "cash_only": 15,
    "personal_bank_account": 20,
    "no_receipt": 15,
    "urgency_pressure": 10,
    "guaranteed_visa": 20,
    "document_fabrication": 25,
    "tourist_to_work_workaround": 20,
    "salary_discrepancy": 15,
    "employer_discrepancy": 15,
    "job_title_discrepancy": 15,
    "appointment_manipulation": 10,
    "refusal_contract": 10,
    "refusal_fee_breakdown": 15,
    # Signals added by the trap library / graph that the original table did not name.
    "authority_claim": 10,
    "refund_undefined": 5,
    "social_proof": 3,
    "country_switch": 15,
    "visa_route_inconsistent": 15,
    "identity_reuse": 20,
}

BANDS = [(80, "CRITICAL"), (60, "VERY HIGH"), (40, "HIGH"), (20, "MODERATE"), (0, "LOW")]

# Any of these forces RED regardless of score (§47).
HARD_STOPS = {
    "document_fabrication": "Fake documents offered or requested",
    "tourist_to_work_workaround": "Illegal entry/work strategy proposed",
    "country_switch": "Destination country changed unexpectedly",
    "employer_discrepancy": "Employer changed unexpectedly",
    "personal_bank_account": "Personal-account payment demanded without justification",
    "oep_mismatch": "Recruiter identity does not match the registered OEP",
}

# Confirmed-fraud markers (set by a human reviewer, never by pattern matching) → BLACK.
BLACK_MARKERS = {"confirmed_forgery", "confirmed_impersonation", "confirmed_illegal_payment_scheme"}

# Everything that must be TRUE for GREEN (§61).
GREEN_REQUIREMENTS = [
    "identity_verified", "oep_verified", "employer_verified", "job_verified",
    "work_auth_verified", "visa_route_verified", "costs_itemised", "contract_verified",
]


def band(score):
    for floor, name in BANDS:
        if score >= floor:
            return name
    return "LOW"


def score_signals(signals):
    """Return (score, band, breakdown). Unknown signals are ignored but reported."""
    breakdown, unknown = {}, []
    for s in sorted(set(signals)):
        if s in RISK_WEIGHTS:
            breakdown[s] = RISK_WEIGHTS[s]
        else:
            unknown.append(s)
    score = sum(breakdown.values())
    return {"score": score, "band": band(score), "breakdown": breakdown, "unknown_signals": unknown}


def decide(signals, verified=None, markers=None):
    """Final decision matrix. Returns colour, action and the reasons behind it.

    signals  — iterable of risk-signal keys
    verified — dict of GREEN_REQUIREMENTS -> bool
    markers  — human-set confirmed-fraud markers
    """
    signals = set(signals)
    verified = verified or {}
    markers = set(markers or [])
    risk = score_signals(signals)

    if markers & BLACK_MARKERS:
        return {"colour": "BLACK", "action": "STOP · PRESERVE EVIDENCE · DO NOT PAY · ESCALATE TO AUTHORITY/PROFESSIONAL",
                "reasons": sorted(markers & BLACK_MARKERS), "risk": risk}

    hard = [HARD_STOPS[s] for s in sorted(signals) if s in HARD_STOPS]
    if hard or risk["score"] >= 60:
        reasons = hard or ["Risk score %d (%s)" % (risk["score"], risk["band"])]
        return {"colour": "RED", "action": "STOP + ESCALATE", "reasons": reasons, "risk": risk}

    missing = [r for r in GREEN_REQUIREMENTS if not verified.get(r)]
    if missing or signals:
        reasons = ["Not yet verified: " + ", ".join(missing)] if missing else []
        reasons += ["Open signal: %s" % s for s in sorted(signals)]
        return {"colour": "AMBER", "action": "HOLD", "reasons": reasons, "risk": risk}

    return {"colour": "GREEN", "action": "HUMAN REVIEW FOR PAYMENT", "reasons": ["All verification gates passed"], "risk": risk}
