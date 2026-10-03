"""Case state machine (spec §49) with evidence gates and an audit trail (§50)."""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .risk import decide

STATES = [
    "LEAD", "IDENTIFIED", "INITIAL_SCREEN", "OEP_VERIFIED", "EMPLOYER_VERIFIED", "JOB_VERIFIED",
    "WORK_AUTH_VERIFIED", "VISA_ROUTE_VERIFIED", "COST_VERIFIED", "CONTRACT_VERIFIED", "DOCUMENT_READY",
    "PAYMENT_APPROVED", "APPLICATION_SUBMITTED", "APPOINTMENT", "DECISION", "TRAVEL", "ARRIVAL",
    "EMPLOYMENT_CONFIRMED", "CASE_CLOSED",
]
SIDE_STATES = {"HOLD", "ESCALATE"}

# Evidence flag that must be set before entering the state.
GATES = {
    "OEP_VERIFIED": "oep_verified",
    "EMPLOYER_VERIFIED": "employer_verified",
    "JOB_VERIFIED": "job_verified",
    "WORK_AUTH_VERIFIED": "work_auth_verified",
    "VISA_ROUTE_VERIFIED": "visa_route_verified",
    "COST_VERIFIED": "costs_itemised",
    "CONTRACT_VERIFIED": "contract_verified",
}
# Irreversible / money / legal steps — never without a named human approver (§48).
HUMAN_GATES = {"PAYMENT_APPROVED", "APPLICATION_SUBMITTED", "TRAVEL"}

CLAIM_STATUSES = {"UNVERIFIED", "PARTIALLY_VERIFIED", "VERIFIED", "CONTRADICTED", "FRAUD_INDICATOR", "UNKNOWN"}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class GateError(Exception):
    pass


@dataclass
class Claim:
    claim: str
    source: str
    source_tier: int = 5
    status: str = "UNVERIFIED"
    source_url: str = ""
    date_observed: str = field(default_factory=_now)
    verification_method: str = ""
    contradictions: list = field(default_factory=list)


@dataclass
class Case:
    case_id: str
    country: str
    job: str = ""
    employer: str = ""
    oep: str = ""
    candidates: int = 1
    state: str = "LEAD"
    evidence: dict = field(default_factory=dict)
    signals: set = field(default_factory=set)
    claims: list = field(default_factory=list)
    timeline: list = field(default_factory=list)
    missing_documents: list = field(default_factory=list)
    _resume_state: str = ""

    def log(self, event, actor="system"):
        self.timeline.append({"at": _now(), "actor": actor, "event": event})

    def add_claim(self, claim):
        if claim.status not in CLAIM_STATUSES:
            raise ValueError(claim.status)
        # Tier-5 evidence can generate a lead; it cannot verify anything (§2).
        if claim.source_tier >= 5 and claim.status == "VERIFIED":
            claim.status = "PARTIALLY_VERIFIED"
        self.claims.append(claim)
        self.log("claim recorded: %s [%s]" % (claim.claim, claim.status))
        return claim

    def verify(self, flag, actor, method):
        self.evidence[flag] = True
        self.log("verified %s via %s" % (flag, method), actor)

    def advance(self, to=None, approver=None):
        if self.state in SIDE_STATES:
            raise GateError("Case is %s — resolve before advancing" % self.state)
        idx = STATES.index(self.state)
        target = to or STATES[idx + 1]
        if target in SIDE_STATES:
            self._resume_state = self.state
            self.state = target
            self.log("moved to " + target, approver or "system")
            return self
        if STATES.index(target) != idx + 1:
            raise GateError("Cannot skip from %s to %s" % (self.state, target))
        if target in GATES and not self.evidence.get(GATES[target]):
            self.state, self._resume_state = "HOLD", self.state
            self.log("gate failed: %s missing → HOLD" % GATES[target])
            raise GateError("%s requires evidence '%s'" % (target, GATES[target]))
        if target in HUMAN_GATES and not approver:
            raise GateError("%s requires a named human approver" % target)
        if target == "PAYMENT_APPROVED" and decide(self.signals, self.evidence)["colour"] != "GREEN":
            raise GateError("Decision matrix is not GREEN — payment cannot be approved")
        self.state = target
        self.log("advanced to " + target, approver or "system")
        return self

    def resume(self, actor):
        if self.state not in SIDE_STATES:
            return self
        self.state = self._resume_state or "LEAD"
        self.log("resumed from hold/escalation", actor)
        return self
