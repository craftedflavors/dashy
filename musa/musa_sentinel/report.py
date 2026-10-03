"""Case summary in the §54 output format."""
from .costs import CostItem, ledger
from .risk import decide

PAYMENT_STATUS = {"GREEN": "APPROVED FOR HUMAN REVIEW", "AMBER": "BLOCKED", "RED": "BLOCKED", "BLACK": "BLOCKED"}


def case_summary(case, cost_items=(), quoted_total=None, markers=()):
    items = [c if isinstance(c, CostItem) else CostItem.from_dict(c) for c in cost_items]
    led = ledger(items, quoted_total)
    d = decide(case.signals, case.evidence, markers)
    verified = [c.claim for c in case.claims if c.status == "VERIFIED"]
    unverified = [c.claim for c in case.claims if c.status in ("UNVERIFIED", "PARTIALLY_VERIFIED", "UNKNOWN")]
    contradicted = [c.claim for c in case.claims if c.status == "CONTRADICTED"]
    flags = ["%s (+%d)" % (k, v) for k, v in d["risk"]["breakdown"].items()]
    next_actions = [r.replace("Not yet verified: ", "Verify: ") for r in d["reasons"]][:5]

    def bullets(xs):
        return "\n".join("• " + x for x in xs) if xs else "• —"

    return f"""CASE ID: {case.case_id}
COUNTRY: {case.country}
JOB: {case.job or 'UNVERIFIED'}
EMPLOYER: {case.employer or 'UNVERIFIED'}
OEP: {case.oep or 'UNVERIFIED'}
STATE: {case.state}
CANDIDATES: {case.candidates}
TOTAL QUOTED COST: €{quoted_total if quoted_total is not None else led['expected_total']:,.0f}
VERIFIED COST: €{led['verified_minimum']:,.0f}
UNKNOWN COST: €{led['unverified_amount']:,.0f}
RISK: {d['risk']['band']} ({d['risk']['score']})
DECISION: {d['colour']} → {d['action']}

VERIFIED:
{bullets(verified)}
UNVERIFIED:
{bullets(unverified)}
CONTRADICTIONS:
{bullets(contradicted)}
RED FLAGS:
{bullets(flags)}
MISSING DOCUMENTS:
{bullets(case.missing_documents)}
NEXT ACTIONS:
{bullets(next_actions)}
PAYMENT STATUS: {PAYMENT_STATUS[d['colour']]}
HUMAN DECISION REQUIRED: YES"""
