"""Job alerts: workers subscribe to sectors and get a WhatsApp message when a checked opening appears.

Double opt-in: the web form only creates a *pending* subscription with a one-time code. It becomes
active when the person sends "ALERTS <code>" to MUSA's WhatsApp, so every number on the list is one
that wrote to us itself (proof of consent, and it opens the WhatsApp service window). Alerts are
sent by a person from the admin queue, never in bulk by a script.
"""
import re
import secrets

from . import db

CODE_RE = re.compile(r"^\s*alerts?\s+([a-z0-9]{6})\s*$", re.I)
OFF_RE = re.compile(r"^\s*alerts?\s+(off|stop|band)\s*$", re.I)
SENDABLE = ("signal", "verified")   # only official-source or checked openings are pushed to people
WINDOW_DAYS = 14


def _code():
    while True:
        c = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        if not db.q("SELECT 1 FROM alerts WHERE code=?", (c,), one=True):
            return c


def create(sectors, lang="en"):
    sectors = [s for s in sectors if s][:8]
    row = {"token": secrets.token_urlsafe(18), "code": _code(), "sectors": ",".join(sectors),
           "lang": "ur" if lang == "ur" else "en", "created_at": db.now_iso(), "consent_at": db.now_iso()}
    row["id"] = db.insert("alerts", **row)
    db.audit("subject", "alerts.pending", target=row["id"])
    return row


def stop(token):
    n = db.xc("DELETE FROM alerts WHERE token=?", (token,))
    db.x("DELETE FROM alert_sends WHERE alert_id NOT IN (SELECT id FROM alerts)")
    if n:
        db.audit("subject", "alerts.stopped", detail={"via": "web"})
    return n


TEXT = {
    "en": {"on": "✅ Job alerts are on for: {sectors}.\nWe only send openings from official sources or ones a MUSA analyst has checked. "
                 "Reply *ALERTS OFF* at any time to stop.",
           "off": "Job alerts are off. Your alert subscription was deleted.",
           "none": "You have no job alerts. Subscribe at {site}/alerts"},
    "ur": {"on": "✅ In shobon ke liye job alerts on hain: {sectors}.\nHum sirf official ya MUSA ki check ki hui openings bhejte hain. "
                 "Band karne ke liye *ALERTS OFF* likhein.",
           "off": "Job alerts band ho gaye. Aap ki subscription delete kar di gayi.",
           "none": "Aap ke koi job alerts nahi hain. Yahan subscribe karein: {site}/alerts"},
}


def bot_hook(site=""):
    """WhatsApp command handler: ALERTS <code> confirms, ALERTS OFF deletes."""
    def hook(wa_id, body, lang):
        t = TEXT.get(lang, TEXT["en"])
        if OFF_RE.match(body):
            n = db.xc("DELETE FROM alerts WHERE contact=?", (wa_id,))
            db.x("DELETE FROM alert_sends WHERE alert_id NOT IN (SELECT id FROM alerts)")
            if n:
                db.audit("subject", "alerts.stopped", detail={"via": "whatsapp"})
            return t["off"] if n else t["none"].format(site=site or "")
        m = CODE_RE.match(body)
        if not m:
            return None
        a = db.q("SELECT * FROM alerts WHERE code=? AND status='pending'", (m.group(1).upper(),), one=True)
        if not a:
            return None
        # one active subscription per number: the newest confirmed one replaces older ones
        db.x("DELETE FROM alerts WHERE contact=? AND id!=?", (wa_id, a["id"]))
        db.x("UPDATE alerts SET status='active', contact=?, confirmed_at=? WHERE id=?", (wa_id, db.now_iso(), a["id"]))
        db.audit("subject", "alerts.confirmed", target=a["id"])
        return TEXT[a["lang"]]["on"].format(sectors=(a["sectors"] or "all sectors").replace(",", ", "))
    return hook


def message(opp, lang, site, token):
    base = site or ""
    label = {"verified": "checked by MUSA", "signal": "official source"}.get(opp["status"], opp["status"])
    if lang == "ur":
        return ("MUSA job alert ({sector}): {title}\nSource: {label}.\nTafseel: {base}/opportunities/{id}\n"
                "Kisi ko paisa dene se pehle check karein: {base}/check\nAlerts band: {base}/alerts/stop/{token} ya *ALERTS OFF* likhein.").format(
            sector=opp["sector"] or "General", title=opp["title"], label=label, base=base, id=opp["id"], token=token)
    return ("MUSA job alert ({sector}): {title}\nSource: {label}.\nDetails: {base}/opportunities/{id}\n"
            "Before you pay anyone, check the offer: {base}/check\nStop alerts: {base}/alerts/stop/{token} or reply *ALERTS OFF*.").format(
        sector=opp["sector"] or "General", title=opp["title"], label=label, base=base, id=opp["id"], token=token)


def queue(opted_out=()):
    """Recent sendable openings with the active subscribers who have not had them yet."""
    subs = [dict(r) for r in db.q("SELECT * FROM alerts WHERE status='active'") if r["contact"] not in opted_out]
    opps = db.q("SELECT * FROM opportunities WHERE status IN (%s) AND found_at >= ? ORDER BY found_at DESC LIMIT 50" % ",".join("?" * len(SENDABLE)),
                SENDABLE + (db.now_iso(-WINDOW_DAYS),))
    sent = {(r["alert_id"], r["opp_id"]) for r in db.q("SELECT alert_id, opp_id FROM alert_sends")}
    out = []
    for o in opps:
        todo = [s for s in subs if (not s["sectors"] or (o["sector"] or "General") in s["sectors"].split(",")) and (s["id"], o["id"]) not in sent]
        out.append({"opp": o, "todo": todo})
    return out


def mark_sent(alert_id, opp_id):
    db.x("INSERT OR IGNORE INTO alert_sends (alert_id, opp_id, sent_at) VALUES (?,?,?)", (alert_id, opp_id, db.now_iso()))


def stats():
    return {"active": db.count("SELECT COUNT(*) FROM alerts WHERE status='active'"),
            "pending": db.count("SELECT COUNT(*) FROM alerts WHERE status='pending'"),
            "sent_7d": db.count("SELECT COUNT(*) FROM alert_sends WHERE sent_at >= ?", (db.now_iso(-7),))}
