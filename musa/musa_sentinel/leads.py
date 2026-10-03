"""Lead pipeline: scores the contact register and builds today's outreach queue.

Replaces the broken scoring in the original cyprus_job_hunter.py (missing self, __init__,
__post_init__, min(len(...)) bug) with a source-tier-aware model.
"""
import json
import os

from . import DATA_DIR

ROLE_VALUE = {"b2b_partner": 3, "legal": 2, "channel": 1, "authority": 0}


def load_contacts(path=None):
    with open(path or os.path.join(DATA_DIR, "contacts.json"), encoding="utf-8") as f:
        return json.load(f)["contacts"]


def contactability(methods):
    m = set(methods or {})
    return 2 * bool(m & {"email", "phone", "whatsapp"}) + bool(m & {"website", "telegram"})


def score_contact(c):
    """0-10 commercial priority. Higher = contact sooner. Tier-5 sources are capped."""
    s = ROLE_VALUE.get(c.get("role"), 0)
    s += contactability(c.get("methods"))
    s += 2 if c.get("claimed_licence") else 0
    s += {1: 2, 2: 1}.get(c.get("priority"), 0)
    s += 1 if c.get("country") == "CY" else 0
    if c.get("source_tier", 5) >= 5:
        s = min(s, 5)
    return min(s, 10)


NEXT_STEP = {
    "b2b_partner": "Verify licence on Department of Labour register → send partner pitch (template: partner_cy_agency)",
    "legal": "Send referral-partnership intro (template: partner_lawyer)",
    "channel": "Verify who the licensed Cyprus/Pakistan party is before sending any candidate",
    "authority": "Bookmark as Tier-0 source; re-check fees/rules monthly",
}


def outreach_queue(contacts=None, include_authorities=False):
    contacts = contacts if contacts is not None else load_contacts()
    q = []
    for c in contacts:
        if c.get("role") == "authority" and not include_authorities:
            continue
        q.append({"name": c["name"], "score": score_contact(c), "role": c.get("role"), "status": c.get("status", "unverified"),
                  "source_tier": c.get("source_tier"), "methods": c.get("methods", {}), "next_step": NEXT_STEP.get(c.get("role"), "")})
    return sorted(q, key=lambda x: (-x["score"], x["name"]))
