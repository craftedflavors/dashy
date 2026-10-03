"""Payments for paid reports: configurable methods, per-request reference codes, Stripe webhook verification.

Card links are Stripe Payment Links; the reference rides along as `client_reference_id`, so the
Stripe webhook can tell us exactly which lead paid. Wallet / bank payments are confirmed by a
human in the admin view (the bot never treats a customer's "PAID" message as proof).
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from . import DATA_DIR

PRODUCT_CODES = {"verify_basic": "B", "verify_deep": "D"}
STRIPE_TOLERANCE_S = 300


def load_config(path=None):
    path = path or os.environ.get("MUSA_PAYMENTS_FILE") or os.path.join(DATA_DIR, "payments.json")
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    override = os.environ.get("MUSA_REPORT_PRICE_PKR")
    if override:
        cfg["products"]["verify_basic"]["pkr"] = int(override)
    return cfg


def new_reference(wa_id, product):
    """e.g. MUSA-B-4567-7F3A — product, last 4 of the number, random suffix. Safe for Stripe client_reference_id."""
    return "MUSA-%s-%s-%s" % (PRODUCT_CODES.get(product, "X"), str(wa_id)[-4:], secrets.token_hex(2).upper())


def _with_param(url, key, value):
    u = urlparse(url)
    q = dict(parse_qsl(u.query))
    q[key] = value
    return urlunparse(u._replace(query=urlencode(q)))


def active_methods(cfg, product):
    """Only methods with enough details filled in to actually pay."""
    out = []
    for m in cfg.get("methods", []):
        if m["type"] == "link" and (m.get("urls") or {}).get(product):
            out.append(m)
        elif m["type"] == "wallet" and m.get("account") and m.get("account_title"):
            out.append(m)
        elif m["type"] == "bank" and m.get("account_title") and (m.get("iban") or m.get("raast_id")):
            out.append(m)
    return out


def instructions(cfg, product, reference, lang="en"):
    """WhatsApp-formatted payment block. Returns '' when nothing is configured."""
    p = cfg["products"][product]
    lines = []
    for m in active_methods(cfg, product):
        if m["type"] == "link":
            url = m["urls"][product]
            if m.get("reference_param"):
                url = _with_param(url, m["reference_param"], reference)
            lines.append("• *%s* (€%s): %s" % (m["label"], p["eur"], url))
        elif m["type"] == "wallet":
            lines.append("• *%s*: %s — %s" % (m["label"], m["account"], m["account_title"]))
        else:
            parts = [m.get("bank"), ("IBAN " + m["iban"]) if m.get("iban") else "", ("Raast " + m["raast_id"]) if m.get("raast_id") else ""]
            lines.append("• *%s*: %s — %s" % (m["label"], " · ".join(x for x in parts if x), m["account_title"]))
    if not lines:
        return ""
    head = "*Payment (Rs %s)* — reference: *%s*" % (format(p["pkr"], ","), reference)
    if lang == "ur":
        note = "Payment note mein reference zaroor likhein."
        tail = ("Payment ke baad *PAID %s* likhein. Hum sirf upar diye gaye company accounts mein paisa lete hain — "
                "agar koi aur account bataye to payment na karein." % reference)
    else:
        note = "Put the reference in the payment note."
        tail = ("After paying, reply *PAID %s*. We only ever take payment into the business accounts above — "
                "if anyone gives you a different account, do not pay." % reference)
    return "\n".join([head] + lines + ["", note, tail])


def config_warnings(cfg):
    warn = []
    for product in cfg.get("products", {}):
        if not active_methods(cfg, product):
            warn.append("No payment method configured for %s — REPORT replies will ask the customer to wait for details." % product)
    for m in cfg.get("methods", []):
        if m["type"] == "link":
            for product, url in (m.get("urls") or {}).items():
                if url and urlparse(url).scheme != "https":
                    warn.append("%s link for %s is not https" % (m["id"], product))
    return warn


# ---------------- Stripe ----------------

def verify_stripe_signature(secret, body, header, now=None, tolerance=STRIPE_TOLERANCE_S):
    """Stripe-Signature: t=<ts>,v1=<hex>[,v1=...]; signed payload is '<ts>.<raw body>'."""
    if not secret or not header:
        return False
    parts = {}
    sigs = []
    for item in header.split(","):
        k, _, v = item.strip().partition("=")
        if k == "v1":
            sigs.append(v)
        else:
            parts[k] = v
    try:
        ts = int(parts.get("t", ""))
    except ValueError:
        return False
    if abs((now or time.time()) - ts) > tolerance:
        return False
    expected = hmac.new(secret.encode(), ("%d." % ts).encode() + body, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, s) for s in sigs)


def parse_stripe_event(event):
    """Return {'reference', 'amount', 'currency', 'event_id'} for a paid checkout, else None."""
    if event.get("type") not in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        return None
    obj = (event.get("data") or {}).get("object") or {}
    if obj.get("payment_status") != "paid" or not obj.get("client_reference_id"):
        return None
    return {"reference": obj["client_reference_id"], "amount": (obj.get("amount_total") or 0) / 100,
            "currency": (obj.get("currency") or "").upper(), "event_id": event.get("id"), "subscription": obj.get("subscription")}


def parse_subscription_end(event):
    """Subscription id when a Stripe subscription ends (cancelled or unpaid), else None."""
    if event.get("type") != "customer.subscription.deleted":
        return None
    return ((event.get("data") or {}).get("object") or {}).get("id")
