"""Cost engine (spec §13-14) and quote-collision detector (§40)."""
from dataclasses import dataclass

CATEGORIES = {
    "A": "Official government fees",
    "B": "Pakistan compliance (medical, protector, attestation, insurance)",
    "C": "Recruitment / OEP / consultancy",
    "D": "Travel",
    "E": "Arrival costs (residence, registration)",
    "F": "Unknown / unverified",
}

# Statuses that count toward the VERIFIED total.
VERIFIED_STATUSES = {"OFFICIAL", "EMPLOYER_CONFIRMED", "CONTRACTUAL"}
STATUSES = VERIFIED_STATUSES | {"RECRUITER_CLAIMED", "UNKNOWN"}


@dataclass
class CostItem:
    label: str
    amount: float
    category: str = "F"
    status: str = "UNKNOWN"
    recipient: str = ""
    source: str = ""
    checked_on: str = ""

    def __post_init__(self):
        if self.category not in CATEGORIES:
            raise ValueError("Unknown cost category %r" % self.category)
        if self.status not in STATUSES:
            raise ValueError("Unknown cost status %r" % self.status)
        # An 'official' figure without a source is just a claim.
        if self.status == "OFFICIAL" and not self.source:
            self.status = "RECRUITER_CLAIMED"

    @property
    def verified(self):
        return self.status in VERIFIED_STATUSES

    @classmethod
    def from_dict(cls, d):
        return cls(**{k: d[k] for k in ("label", "amount", "category", "status", "recipient", "source", "checked_on") if k in d})


def ledger(items, quoted_total=None):
    """Build the §14 response. Unverified money is never folded into the verified total."""
    by_cat = {c: 0.0 for c in CATEGORIES}
    verified = unverified = 0.0
    for it in items:
        by_cat[it.category] += it.amount
        if it.verified:
            verified += it.amount
        else:
            unverified += it.amount
    itemised = verified + unverified
    gap = (quoted_total - itemised) if quoted_total is not None else 0.0
    if gap > 0:
        by_cat["F"] += gap
        unverified += gap
    return {
        "by_category": {"%s — %s" % (c, CATEGORIES[c]): round(v, 2) for c, v in by_cat.items()},
        "verified_minimum": round(verified, 2),
        "unverified_amount": round(unverified, 2),
        "expected_total": round(verified + unverified, 2),
        "maximum_known_exposure": round(max(verified + unverified, quoted_total or 0), 2),
        "unitemised_gap": round(max(gap, 0), 2),
        "unverified_items": [it.label for it in items if not it.verified] + (["Unitemised remainder of quote"] if gap > 0 else []),
    }


def quote_collision(quotes, field="government_fee", tolerance=0.15):
    """Compare what several agents claim for the same line. Never average — flag divergence.

    quotes: {"Agent A": {"total": 2500, "government_fee": 1500}, ...}
    """
    values = {k: v[field] for k, v in quotes.items() if v.get(field) is not None}
    if len(values) < 2:
        return {"field": field, "collision": False, "values": values}
    lo, hi = min(values.values()), max(values.values())
    collision = lo == 0 or (hi - lo) / lo > tolerance
    return {
        "field": field, "values": values, "collision": collision,
        "spread": hi - lo,
        "action": ("Claims disagree — verify %s from the official source; do not average." % field) if collision else "Consistent (still verify against official source).",
    }
