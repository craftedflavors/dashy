"""Guardian — GDPR mechanics: consent records, retention, data-subject access & erasure, audit.

Retention periods are the defaults in RETENTION_DAYS. Change them only together with the
privacy notice text (ui.privacy_page), which states the same numbers.
"""
import json

from . import db

RETENTION_DAYS = {
    "profiles": 365,           # CV / match profiles: 12 months after creation
    "employer_requests": 730,  # business enquiries: 24 months
    "orders": 2190,            # paid orders: 6 years (accounting records)
    "scans": 730,              # anonymous counters
    "questions": 730,          # anonymous counters
    "dsar": 1095,              # proof that requests were handled: 3 years
    "audit": 1095,
}
_DATE_COL = {"profiles": "created_at", "employer_requests": "created_at", "orders": "created_at",
             "scans": "created_at", "questions": "created_at", "dsar": "at", "audit": "at"}

# Where personal data lives, and which column identifies the person.
PERSONAL = {"orders": ["contact"], "profiles": ["contact"], "partners": ["email", "phone"],
            "employer_requests": ["email", "phone"]}

CONSENT_TEXT = {
    "order": "I agree that MUSA processes the details I give here to prepare my report and contact me about it (GDPR Art. 6(1)(b)). Retention: 6 years for accounting records.",
    "profile": "I agree that MUSA stores my profile to generate my CV and job matches (GDPR Art. 6(1)(a)). I can delete it at any time; otherwise it is deleted after 12 months.",
    "share": "Optional: MUSA may share my CV (without my contact details) with verified employers in Cyprus for roles I match. MUSA arranges any interview. I can withdraw this at any time by deleting my profile.",
    "partner": "I confirm I may share these business details for partner verification (KYB) and agree to be contacted about the partnership.",
    "employer": "I agree that MUSA uses these details to respond to our hiring request. Retention: 24 months.",
}


def run_retention():
    removed = {}
    for table, days in RETENTION_DAYS.items():
        cutoff = db.now_iso(-days)
        removed[table] = db.xc("DELETE FROM %s WHERE %s < ?" % (table, _DATE_COL[table]), (cutoff,))
    db.audit("agent:guardian", "retention.run", detail={"policy_days": RETENTION_DAYS})
    return removed


def _norm_contact(s):
    s = (s or "").strip().lower()
    digits = "".join(ch for ch in s if ch.isdigit())
    return s if "@" in s else digits[-10:]


def _matches(stored, contact):
    return bool(stored) and _norm_contact(stored) == _norm_contact(contact)


def find_personal(contact):
    """All records tied to an email address or phone number."""
    out = {}
    for table, cols in PERSONAL.items():
        rows = [dict(r) for r in db.q("SELECT * FROM %s" % table)]
        hits = [r for r in rows if any(_matches(r.get(c), contact) for c in cols)]
        if hits:
            out[table] = hits
    return out


def export(contact):
    data = find_personal(contact)
    db.audit("admin", "dsar.export", target=_mask(contact), detail={t: len(v) for t, v in data.items()})
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def erase(contact):
    """Delete personal records. Paid orders are kept for the legal accounting period but anonymised."""
    data = find_personal(contact)
    done = {}
    for table, rows in data.items():
        for r in rows:
            if table == "orders" and r.get("status") in ("paid", "delivered"):
                db.x("UPDATE orders SET name='[erased]', contact='[erased]', details='[erased]' WHERE id=?", (r["id"],))
            else:
                db.x("DELETE FROM %s WHERE id=?" % table, (r["id"],))
            done[table] = done.get(table, 0) + 1
    db.audit("admin", "dsar.erase", target=_mask(contact), detail=done)
    return done


def _mask(contact):
    c = _norm_contact(contact)
    return ("•••" + c[-4:]) if c else ""
