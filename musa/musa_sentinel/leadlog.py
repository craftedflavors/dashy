"""Lead log analytics — turns data/leads.jsonl (written by the WhatsApp bot) into a follow-up queue.

Two outputs, deliberately different:
  * dashy_page()  — PUBLIC-SAFE. Dashy serves user-data/ as static files (and Netlify publishes it),
                    so it gets aggregates and numbers masked to the last 4 digits only.
  * admin_html()  — PRIVATE. Full WhatsApp IDs + one-tap follow-up links; only served by the bot
                    behind HTTP Basic auth (see whatsapp.py /admin/leads).
"""
import html
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from . import DATA_DIR

COLOUR_RANK = {"GREEN": 0, "AMBER": 1, "RED": 2, "BLACK": 3}
# Work queue order: money first (deliver what's paid, verify claimed payments), then sales.
STATUS_ORDER = {"paid": 0, "claimed": 1, "hot": 2, "warm": 3, "cold": 4, "done": 5, "delivered": 6, "opted_out": 7}
QUEUE_STATUSES = ("paid", "claimed", "hot", "warm")


def default_path():
    return os.environ.get("MUSA_LEADS_FILE") or os.path.join(DATA_DIR, "leads.jsonl")


def _ts(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def load(path=None):
    path = path or default_path()
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("wa_id") and _ts(rec.get("at")):
                    out.append(rec)
    except OSError:
        pass
    return out


def mask(wa_id):
    return "•••" + str(wa_id)[-4:]


def summarise(records, now=None):
    """Per-sender rollup + corridor stats."""
    now = now or datetime.now(timezone.utc)
    people = {}
    for r in sorted(records, key=lambda r: r["at"]):
        p = people.setdefault(r["wa_id"], {
            "wa_id": r["wa_id"], "first_seen": r["at"], "last_seen": r["at"], "scans": 0, "worst": None,
            "traps": Counter(), "price_asked": None, "report_requested": None, "followed_up": None,
            "opted_out": False, "lang": r.get("lang", "en"), "reference": None, "product": None,
            "payment_claimed": None, "paid": None, "paid_amount": None, "delivered": None})
        p["last_seen"] = r["at"]
        p["lang"] = r.get("lang", p["lang"])
        intent = r.get("intent")
        if intent == "scan":
            p["scans"] += 1
            c = r.get("colour")
            if c and (p["worst"] is None or COLOUR_RANK.get(c, 0) > COLOUR_RANK.get(p["worst"], 0)):
                p["worst"] = c
            p["traps"].update(r.get("traps") or [])
        elif intent == "price":
            p["price_asked"] = r["at"]
        elif intent == "report_request":
            p["report_requested"] = r["at"]
            p["reference"] = r.get("reference") or p["reference"]
            p["product"] = r.get("product") or p["product"]
            p["paid"] = p["payment_claimed"] = p["delivered"] = None  # a new request is a new order
        elif intent == "payment_claimed":
            p["payment_claimed"] = r["at"]
        elif intent == "paid":
            p["paid"] = r["at"]
            p["paid_amount"] = "%s %s" % (r.get("currency", ""), r.get("amount", ""))
        elif intent == "delivered":
            p["delivered"] = r["at"]
        elif intent == "followed_up":
            p["followed_up"] = r["at"]
        elif intent == "opt_out":
            p["opted_out"] = True
        elif intent == "opt_in":
            p["opted_out"] = False

    for p in people.values():
        last_ask = max(filter(None, [p["report_requested"], p["price_asked"]]), default=None)
        if p["opted_out"]:
            p["status"] = "opted_out"
        elif p["delivered"]:
            p["status"] = "delivered"
        elif p["paid"]:
            p["status"] = "paid"
        elif p["payment_claimed"]:
            p["status"] = "claimed"
        elif p["followed_up"] and (not last_ask or p["followed_up"] >= last_ask):
            p["status"] = "done"
        elif p["report_requested"]:
            p["status"] = "hot"
        elif p["price_asked"] or p["worst"] == "RED":
            p["status"] = "warm"
        else:
            p["status"] = "cold"
        p["top_traps"] = [t for t, _ in p["traps"].most_common(3)]

    week_ago = now - timedelta(days=7)
    day_ago = now - timedelta(days=1)
    scans = [r for r in records if r.get("intent") == "scan"]
    scans_7d = [r for r in scans if _ts(r["at"]) >= week_ago]
    reports = [p for p in people.values() if p["report_requested"]]
    trap_counts = Counter(t for r in scans_7d for t in (r.get("traps") or []))
    queue = sorted((p for p in people.values() if p["status"] in QUEUE_STATUSES),
                   key=lambda p: (STATUS_ORDER[p["status"]], p["paid"] or p["payment_claimed"] or p["report_requested"] or p["last_seen"]))
    paid_7d = [r for r in records if r.get("intent") == "paid" and _ts(r["at"]) >= week_ago]
    revenue_7d = {}
    for r in paid_7d:
        cur = r.get("currency") or "?"
        revenue_7d[cur] = revenue_7d.get(cur, 0) + (r.get("amount") or 0)
    return {
        "people": len(people),
        "scans_total": len(scans),
        "scans_24h": sum(1 for r in scans if _ts(r["at"]) >= day_ago),
        "scans_7d": len(scans_7d),
        "red_share_7d": round(100 * sum(1 for r in scans_7d if r.get("colour") == "RED") / len(scans_7d)) if scans_7d else 0,
        "report_requests": len(reports),
        "hot": sum(1 for p in people.values() if p["status"] == "hot"),
        "warm": sum(1 for p in people.values() if p["status"] == "warm"),
        "done": sum(1 for p in people.values() if p["status"] == "done"),
        "opted_out": sum(1 for p in people.values() if p["status"] == "opted_out"),
        "conversion_pct": round(100 * len(reports) / len(people)) if people else 0,
        "to_deliver": sum(1 for p in people.values() if p["status"] == "paid"),
        "to_verify": sum(1 for p in people.values() if p["status"] == "claimed"),
        "paid_7d": len(paid_7d),
        "revenue_7d": revenue_7d,
        "delivered": sum(1 for p in people.values() if p["status"] == "delivered"),
        "top_traps_7d": trap_counts.most_common(5),
        "queue": queue,
    }


def _ago(iso, now):
    t = _ts(iso)
    if not t:
        return "?"
    mins = int((now - t).total_seconds() // 60)
    if mins < 60:
        return "%dm ago" % max(mins, 0)
    if mins < 60 * 48:
        return "%dh ago" % (mins // 60)
    return "%dd ago" % (mins // 1440)


def _y(s):
    return json.dumps(str(s), ensure_ascii=False)


def _trap_names():
    try:
        from .traps import load_traps
        return {t["id"]: t["name"] for t in load_traps()}
    except Exception:
        return {}


def dashy_page(summary, admin_url="", now=None):
    """PUBLIC-SAFE Dashy sub-page YAML: aggregates + masked numbers only."""
    now = now or datetime.now(timezone.utc)
    names = _trap_names()
    s = summary

    def item(title, desc, icon, url=""):
        out = "  - title: %s\n    description: %s\n    icon: %s\n" % (_y(title), _y(desc), icon)
        if url:
            out += "    url: %s\n    target: newtab\n" % _y(url)
        return out.rstrip()

    y = ["---",
         "# GENERATED by `python -m musa_sentinel leads-page` — public-safe: aggregates and masked numbers only.",
         "# Full numbers live only in the bot's password-protected /admin/leads view.",
         "pageInfo:",
         "  title: MUSA Leads",
         "  description: %s" % _y("Follow-up queue · generated %s UTC" % now.strftime("%Y-%m-%d %H:%M")),
         "sections:",
         "- name: Today's numbers\n  icon: fas fa-tachometer-alt\n  displayData:\n    cols: 3\n  items:"]
    revenue = " + ".join("%s %s" % (c, format(round(v), ",")) for c, v in sorted(s["revenue_7d"].items())) or "0"
    y.append(item("💰 %d paid report(s) to deliver" % s["to_deliver"], "Paid — deliver within the promised time", "fas fa-money-bill-wave", admin_url))
    y.append(item("🧾 %d payment claim(s) to verify" % s["to_verify"], "Customer says PAID — confirm it reached the business account", "fas fa-receipt", admin_url))
    y.append(item("Revenue (7 days): %s" % revenue, "%d paid report(s) this week · %d delivered in total" % (s["paid_7d"], s["delivered"]), "fas fa-coins"))
    y.append(item("🔥 %d report request(s) waiting" % s["hot"], "Paid-report intent, not yet followed up — contact today", "fas fa-fire", admin_url))
    y.append(item("%d warm lead(s)" % s["warm"], "Asked for prices or got a RED scan — nudge with the REPORT offer", "fas fa-thermometer-half", admin_url))
    y.append(item("Scans: %d today · %d this week" % (s["scans_24h"], s["scans_7d"]), "%d%% of this week's scans were RED" % s["red_share_7d"], "fas fa-shield-alt"))
    y.append(item("People reached: %d" % s["people"], "%d requested a report (%d%% conversion) · %d followed up" % (s["report_requests"], s["conversion_pct"], s["done"]), "fas fa-users"))
    y.append(item("Opt-outs: %d" % s["opted_out"], "Never message these numbers again", "fas fa-user-slash"))
    y.append(item("Open private admin" if admin_url else "Admin view not configured",
                  "Full numbers + one-tap WhatsApp follow-up (password protected)" if admin_url
                  else "Set MUSA_ADMIN_URL and MUSA_ADMIN_PASSWORD on the bot server", "fas fa-lock", admin_url))

    y.append("- name: Follow-up queue\n  icon: fas fa-list-ol\n  items:")
    if s["queue"]:
        for p in s["queue"][:25]:
            what = {
                "paid": "PAID %s — deliver report" % _ago(p["paid"], now),
                "claimed": "says PAID %s — verify" % _ago(p["payment_claimed"], now),
                "hot": "REPORT requested %s" % _ago(p["report_requested"], now),
            }.get(p["status"]) or ("Price asked %s" % _ago(p["price_asked"], now) if p["price_asked"] else "RED scan %s" % _ago(p["last_seen"], now))
            flags = ", ".join(names.get(t, t) for t in p["top_traps"]) or "no flags"
            icon = {"paid": "💰", "claimed": "🧾", "hot": "🔥"}.get(p["status"], "•")
            y.append(item("%s %s — %s" % (icon, mask(p["wa_id"]), what),
                          "%d scan(s) · worst %s · %s · lang %s" % (p["scans"], p["worst"] or "—", flags, p["lang"]),
                          "fas fa-user", admin_url))
    else:
        y.append(item("Queue is empty", "No open report requests or warm leads. Post a Scam Shield reel to bring new scans in.", "fas fa-check"))

    y.append("- name: Top scam patterns this week (content ideas)\n  icon: fas fa-bullhorn\n  items:")
    if s["top_traps_7d"]:
        for tid, n in s["top_traps_7d"]:
            y.append(item("%s — %d" % (names.get(tid, tid), n), "%s · make an Urdu reel warning about this" % tid, "fas fa-exclamation-triangle"))
    else:
        y.append(item("No scans yet this week", "Patterns appear here once the WhatsApp bot is live", "fas fa-hourglass-half"))
    return "\n".join(y) + "\n"


def admin_html(summary, now=None, price_pkr=4500):
    """PRIVATE page: full numbers + wa.me links. Only ever served behind auth."""
    now = now or datetime.now(timezone.utc)
    names = _trap_names()
    s = summary
    follow_text = {
        "hot": "Assalam o alaikum! MUSA Scam Shield here — you requested a Verify-Before-You-Pay report (Rs %d). Please send the agent/company name, OEP licence no. and BEOE permission no. if you have them." % price_pkr,
        "warm": "Assalam o alaikum! MUSA Scam Shield here. Before you pay any agent, we can check the offer against official records (Rs %d, 48h). Reply REPORT to start." % price_pkr,
    }
    follow_text["claimed"] = "Assalam o alaikum! MUSA here — we're checking your payment for reference %s and will confirm shortly."
    follow_text["paid"] = "Assalam o alaikum! MUSA here — your report for reference %s is ready:"
    label = {"paid": "💰 paid", "claimed": "🧾 claimed", "hot": "🔥 hot", "warm": "warm"}
    rows = []
    for p in s["queue"]:
        text = follow_text[p["status"]]
        if "%s" in text:
            text = text % (p["reference"] or "")
        link = "https://wa.me/%s?text=%s" % (quote(p["wa_id"]), quote(text))
        wid = html.escape(quote(p["wa_id"]))
        ref = html.escape(p["reference"] or "")
        if p["status"] == "paid":
            action = "<form method='post' action='/admin/leads/%s/delivered'><button>Delivered</button></form>" % wid
        elif p["status"] in ("claimed", "hot") and p["reference"]:
            action = ("<form method='post' action='/admin/leads/%s/paid'><input type='hidden' name='reference' value='%s'>"
                      "<select name='method'><option>jazzcash</option><option>easypaisa</option><option>bank</option><option>card</option></select> "
                      "<button>Mark paid</button></form>" % (wid, ref))
        else:
            action = "<form method='post' action='/admin/leads/%s/done'><button>Done</button></form>" % wid
        flags = ", ".join(names.get(t, t) for t in p["top_traps"]) or "—"
        when = p["paid"] or p["payment_claimed"] or p["report_requested"] or p["price_asked"] or p["last_seen"]
        rows.append(
            "<tr><td>%s</td><td>+%s</td><td class='nw'>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td>"
            "<td><a class='btn' href='%s' target='_blank' rel='noopener'>WhatsApp</a></td><td>%s</td></tr>" % (
                label[p["status"]], html.escape(p["wa_id"]), ref or "—", html.escape(_ago(when, now)),
                p["scans"], html.escape(p["worst"] or "—"), html.escape(flags), html.escape(link), action))
    body = "\n".join(rows) or "<tr><td colspan='9'>Queue is empty.</td></tr>"
    return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>MUSA Leads Admin</title><style>
:root{--bg:#f6f5f1;--ink:#14212b;--muted:#5b6770;--line:#dcdcd4;--card:#fff;--brand:#0b3d5c;--go:#2d7d5a}
@media (prefers-color-scheme:dark){:root{--bg:#0f171d;--ink:#e8edf0;--muted:#9aa8b2;--line:#2a3843;--card:#17222b;--brand:#5fa8d3;--go:#4fbf8b}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:16px}h1{font-size:22px;margin:8px 0}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}.kpi b{font-size:24px;display:block}
.tbl{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%%;min-width:720px}th,td{text-align:left;padding:8px 10px;border-top:1px solid var(--line)}
th{color:var(--muted);font-weight:600;border-top:0}.btn{background:var(--go);color:#fff;padding:5px 10px;border-radius:6px;text-decoration:none}
button{font:inherit;padding:4px 10px;border-radius:6px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
.muted{color:var(--muted);font-size:13px}.nw{white-space:nowrap;font-family:ui-monospace,monospace;font-size:13px}</style></head><body><div class="wrap">
<h1>MUSA Leads — follow-up queue</h1><div class="muted">Private · generated %s UTC · do not share or screenshot</div>
<div class="kpis"><div class="kpi"><b>%d</b>paid — deliver</div><div class="kpi"><b>%d</b>payments to verify</div>
<div class="kpi"><b>%s</b>revenue (7 days)</div><div class="kpi"><b>%d</b>report requests waiting</div><div class="kpi"><b>%d</b>warm leads</div>
<div class="kpi"><b>%d</b>scans this week (%d%% RED)</div><div class="kpi"><b>%d%%</b>scan → report conversion</div>
<div class="kpi"><b>%d</b>opt-outs</div></div>
<div class="tbl"><table><thead><tr><th>Status</th><th>WhatsApp</th><th>Reference</th><th>When</th><th>Scans</th><th>Worst</th><th>Flags</th><th></th><th></th></tr></thead>
<tbody>%s</tbody></table></div>
<p class="muted">Messages you start outside 24h of the person's last message need a Meta-approved template. Opted-out numbers are never shown here.</p>
</div></body></html>""" % (now.strftime("%Y-%m-%d %H:%M"), s["to_deliver"], s["to_verify"],
       html.escape(" + ".join("%s %s" % (c, format(round(v), ",")) for c, v in sorted(s["revenue_7d"].items())) or "0"), s["hot"], s["warm"], s["scans_7d"], s["red_share_7d"],
                          s["conversion_pct"], s["opted_out"], body)


def mark(wa_id, intent, path=None, **extra):
    path = path or default_path()
    rec = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "wa_id": wa_id, "intent": intent}
    rec.update(extra)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def mark_followed_up(wa_id, path=None):
    mark(wa_id, "followed_up", path)
