"""Admin console pages (behind HTTP Basic auth). Dense tables, actions as small POST forms."""
from .ui import e, fmt_int, layout, status_chip, tier_chip


def _form(action, label, extra=""):
    return '<form method="post" action="%s" class="inline-form">%s<button class="btn small" type="submit">%s</button></form>' % (e(action), extra, e(label))


def _table(headers, rows, empty="Nothing here yet."):
    head = "".join('<th%s>%s</th>' % (' class="num"' if h.startswith("#") else "", e(h.lstrip("#"))) for h in headers)
    body = "".join(rows) or '<tr><td colspan="%d" class="muted">%s</td></tr>' % (len(headers), e(empty))
    return '<div class="table-wrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (head, body)


def overview(k, queues, flash=None):
    tiles = [
        ("Orders to confirm", k["orders_claimed"], True), ("Paid, to deliver", k["orders_paid"], True),
        ("Partner applications", k["partners_pending"], True), ("Employer requests", k["employers_new"], True),
        ("Data requests open", k["dsar_open"], True), ("Revenue (paid, PKR)", fmt_int(k["revenue_pkr"]), False),
        ("Live opportunities", k["opps_live"], False), ("Verified opportunities", k["opps_verified"], False),
        ("Scans (7 days)", k["scans_7d"], False), ("Questions (7 days)", k["questions_7d"], False),
        ("Verified partners", k["partners_live"], False), ("Scout sources on", k["sources_on"], False),
    ]
    kp = "".join('<div class="kpi%s"><b>%s</b><span>%s</span></div>' % (" alert" if alert and str(v) not in ("0",) else "", e(v), e(t)) for t, v, alert in tiles)
    q = "".join('<li><a href="%s">%s</a></li>' % (e(h), e(t)) for h, t in queues) or "<li class='muted'>No open work. Run Scout or check WhatsApp leads.</li>"
    return layout("Admin", """<section><div class="wrap stack"><h1>Operations</h1><div class="kpis">%s</div>
<div class="split"><div class="card"><h3>Today's queue (money first)</h3><ol style="margin:0;padding-left:18px">%s</ol></div>
<div class="card stack"><h3>Run</h3><small class="muted">Last Scout run: %s</small>%s%s<a class="btn small" href="/admin/leads">Open WhatsApp leads</a></div></div></div></section>""" % (
        kp, q, e(k["last_scout"]), _form("/admin/scout/run", "Run Scout now"), _form("/admin/compliance/retention", "Apply retention policy")), active="/admin", admin=True, flash=flash)


def opportunities(rows, status, flash=None):
    tabs = "".join('<a class="chip%s" href="/admin/opportunities?status=%s">%s</a>' % (" ok" if s == status else "", s, s) for s in ("lead", "signal", "verified", "flagged", "expired"))
    trs = []
    for o in rows:
        acts = "".join(_form("/admin/opportunities/%d/%s" % (o["id"], a), lbl) for a, lbl in (("verify", "Verify"), ("flag", "Flag"), ("expire", "Expire")) if a != {"verified": "verify", "flagged": "flag", "expired": "expire"}.get(o["status"]))
        trs.append("<tr><td>%d</td><td><a href=\"/opportunities/%d\">%s</a><br><small class=\"muted\">%s</small></td><td>%s</td><td>%s</td><td>%s</td><td><div class=\"row\">%s</div></td></tr>" % (
            o["id"], o["id"], e(o["title"]), e(o["source"]), tier_chip(o["source_tier"]), e(o["sector"]), status_chip(o["status"]), acts))
    return layout("Admin · Opportunities", """<section><div class="wrap stack"><h1>Opportunities</h1><div class="row">%s</div>
<p class="muted">Verify only after you have confirmed the employer (registry) and the recruiter's licence. Flag anything with a hard-stop pattern.</p>%s
<details class="card"><summary><b>Add an opportunity by hand</b></summary><form method="post" action="/admin/opportunities/add" class="form-grid" style="margin-top:14px">
<label>Title<input name="title" required></label><label>Source<input name="source" required placeholder="e.g. BEOE permission 4349941"></label>
<label>Tier<select name="tier"><option value="0">0 Government</option><option value="1">1 Employer</option><option value="2">2 Licensed agency</option><option value="4" selected>4 Job board</option><option value="5">5 Social</option></select></label>
<label>URL<input name="url"></label><label>Country<input name="country" value="Cyprus"></label><label>Employer<input name="employer"></label>
<label>Summary<textarea name="summary"></textarea></label><div style="align-self:end"><button class="btn primary" type="submit">Add</button></div></form></details></div></section>""" % (
        tabs, _table(["#ID", "Title", "Source tier", "Sector", "Status", "Actions"], trs)), active="/admin/opportunities", admin=True, flash=flash)


def orders(rows, flash=None):
    trs = []
    for o in rows:
        if o["status"] in ("requested", "claimed"):
            act = _form("/admin/orders/%s/paid" % o["ref"], "Mark paid", '<select name="method"><option>jazzcash</option><option>easypaisa</option><option>bank</option><option>card</option></select>')
        elif o["status"] == "paid":
            act = _form("/admin/orders/%s/delivered" % o["ref"], "Mark delivered")
        else:
            act = ""
        trs.append("<tr><td class=\"mono\"><a href=\"/order/%s\">%s</a></td><td>%s<br><small class=\"muted\">%s</small></td><td>%s</td><td class=\"num\">%s</td><td>%s</td><td><small>%s</small></td><td>%s</td></tr>" % (
            e(o["ref"]), e(o["ref"]), e(o["name"]), e(o["contact"]), e(o["product"]), fmt_int(o["amount_pkr"]), e(o["status"]), e((o["details"] or "")[:160]), act))
    return layout("Admin · Orders", '<section><div class="wrap stack"><h1>Report orders</h1><p class="muted">"claimed" means the customer clicked "I have paid". Check the money reached the business account before marking it paid.</p>%s</div></section>' % _table(
        ["Ref", "Customer", "Product", "#PKR", "Status", "Details", "Action"], trs), active="/admin/orders", admin=True, flash=flash)


def partners(rows, flash=None):
    trs = []
    for p in rows:
        act = ""
        if p["status"] in ("pending", "in_review"):
            act = _form("/admin/partners/%d/approve" % p["id"], "Approve") + _form("/admin/partners/%d/reject" % p["id"], "Reject")
        elif p["status"] == "approved":
            act = ('<a href="/partner/billing/%s">Billing link</a> ' % e(p["billing_ref"])) + _form("/admin/partners/%d/paid" % p["id"], "Mark paid +1 month") + \
                (('<a href="/partners/%s">Badge</a> ' % e(p["slug"])) if p["billing_status"] == "active" else "") + _form("/admin/partners/%d/revoke" % p["id"], "Revoke")
        trs.append("<tr><td>%s<br><small class=\"muted\">%s · %s</small></td><td>%s</td><td class=\"mono\">%s<br>%s</td><td>%s<br><small>%s %s</small></td><td>%s</td><td><div class=\"row\">%s</div></td></tr>" % (
            e(p["org_name"]), e(p["org_type"]), e(p["country"]), e(p["tier"]), e(p["licence_no"] or "—"), e(p["registry_no"] or "—"),
            e(p["contact_name"]), e(p["email"]), e(p["phone"] or ""), e(p["status"]) + "<br><small class=\"muted\">billing: %s%s</small>" % (
                e(p["billing_status"] or "none"), (" until " + e(p["paid_until"][:10])) if p["paid_until"] else ""), act))
    return layout("Admin · Partners", """<section><div class="wrap stack"><h1>Partner applications (KYB)</h1>
<p class="note">After approval, send the partner their billing link; the public badge goes live only once billing is active. Approve only after: licence confirmed on the official register (BEOE / Cyprus Department of Labour), company registration confirmed, official contact details match, owner video call done.</p>%s</div></section>""" % _table(
        ["Organisation", "Plan", "Licence / registry", "Contact", "Status", "Action"], trs), active="/admin/partners", admin=True, flash=flash)


def employers(rows, flash=None):
    trs = "".join("<tr><td>%s<br><small class=\"muted\">%s · %s</small></td><td class=\"num\">%s</td><td><small>%s</small></td><td>%s<br><small>%s %s</small></td><td>%s</td><td>%s</td></tr>" % (
        e(r["company"]), e(r["sector"]), e(r["country"]), e(r["headcount"]), e(r["roles"]), e(r["contact_name"]), e(r["email"]), e(r["phone"] or ""), e(r["status"]),
        ('<a class="btn small" href="/admin/employers/%d">Build shortlist</a> ' % r["id"]) + (_form("/admin/employers/%d/contacted" % r["id"], "Mark contacted") if r["status"] == "new" else "")) for r in rows)
    return layout("Admin · Employers", '<section><div class="wrap stack"><h1>Employer requests</h1>%s</div></section>' % _table(
        ["Company", "#Headcount", "Roles", "Contact", "Status", "Action"], [trs] if trs else []), active="/admin/employers", admin=True, flash=flash)


def scout(sources, runs, flash=None):
    src = "".join("<tr><td><b>%s</b><br><small class=\"muted\">%s</small></td><td>%s</td><td>%s</td><td>%s</td><td><small>%s</small></td></tr>" % (
        e(s["name"]), e(s.get("url") or "(no URL)"), e(s["type"]), tier_chip(s.get("tier", 4)), "on" if s.get("enabled") and s.get("url") else "off", e(s.get("note", ""))) for s in sources)
    rr = "".join("<tr><td class=\"mono\">%s</td><td>%s</td><td class=\"num\">%s</td><td class=\"num\">%s</td><td><small>%s</small></td></tr>" % (
        e((r["started_at"] or "")[:16]), e(r["source"]), r["fetched"], r["added"], e(r["error"] or "ok")) for r in runs)
    return layout("Admin · Scout", """<section><div class="wrap stack"><h1>Scout</h1><div class="row">%s<small class="muted">Runs automatically every MUSA_SCOUT_HOURS (default 6). Enable sources in data/sources.json after checking each site's terms.</small></div>
<h2>Sources</h2>%s<h2>Recent runs</h2>%s</div></section>""" % (
        _form("/admin/scout/run", "Run Scout now"), _table(["Source", "Type", "Tier", "State", "Note"], [src] if src else []),
        _table(["Started", "Source", "#Fetched", "#New", "Result"], [rr] if rr else [], "No runs yet.")), active="/admin/scout", admin=True, flash=flash)


def compliance(dsars, audit_rows, export_json=None, flash=None):
    trs = "".join("<tr><td class=\"mono\">%s</td><td>%s</td><td>%s</td><td>%s</td><td><div class=\"row\">%s</div></td></tr>" % (
        e(d["at"][:16]), e(d["contact"]), e(d["kind"]), e(d["status"]),
        (_form("/admin/compliance/dsar/%d/export" % d["id"], "Export") + _form("/admin/compliance/dsar/%d/erase" % d["id"], "Erase") +
         _form("/admin/compliance/dsar/%d/close" % d["id"], "Close")) if d["status"] == "open" else "") for d in dsars)
    au = "".join("<tr><td class=\"mono\">%s</td><td>%s</td><td>%s</td><td>%s</td><td><small class=\"mono\">%s</small></td></tr>" % (
        e(a["at"][:19]), e(a["actor"]), e(a["action"]), e(a["target"]), e((a["detail"] or "")[:160])) for a in audit_rows)
    exp = ('<h2>Export</h2><p class="muted">Send this to the person only after confirming their identity.</p><pre class="card" style="overflow-x:auto;font-size:.8rem">%s</pre>' % e(export_json)) if export_json else ""
    return layout("Admin · Compliance", """<section><div class="wrap stack"><h1>Compliance</h1>
<p class="note">Confirm the requester's identity (reply from the same email/number) before exporting or erasing. GDPR deadline: one month from the request date.</p>
<h2>Data subject requests</h2>%s%s<div class="row">%s</div><h2>Audit log (latest 100)</h2>%s</div></section>""" % (
        _table(["Received", "Contact", "Kind", "Status", "Action"], [trs] if trs else [], "No requests."), exp,
        _form("/admin/compliance/retention", "Apply retention policy now"), _table(["At", "Actor", "Action", "Target", "Detail"], [au] if au else [])),
        active="/admin/compliance", admin=True, flash=flash)


def revenue(fc, actual, flash=None):
    placements = actual.get("placements", 0)
    rows = "".join("<tr><td>%d</td><td class=\"num\">%s</td><td class=\"num\">%s</td><td class=\"num\">%s</td><td class=\"num\">%s</td></tr>" % (
        r["month"], fmt_int(r["revenue"]), fmt_int(r["mrr"]), fmt_int(r["profit"]), fmt_int(r["cumulative_profit"])) for r in fc["rows"])
    return layout("Admin · Revenue", """<section><div class="wrap stack"><h1>Revenue</h1>
<div class="kpis"><div class="kpi"><b>%s</b><span>Paid orders, PKR (all time)</span></div><div class="kpi"><b>%s</b><span>Paid orders</span></div>
<div class="kpi"><b>€%s</b><span>Placement fees (%d hires)</span></div><div class="kpi"><b>€%s</b><span>Forecast · 12 months (base)</span></div><div class="kpi"><b>€%s</b><span>Forecast · MRR month 12</span></div></div>
<p class="muted">Forecast assumptions live in data/pricing.json. Replace them with real conversion data as soon as you have it.</p>%s</div></section>""" % (
        fmt_int(actual["pkr"]), fmt_int(actual["count"]), fmt_int(actual.get("placement_eur", 0)), placements, fmt_int(fc["total_revenue"]), fmt_int(fc["ending_mrr"]),
        _table(["Month", "#Revenue €", "#MRR €", "#Profit €", "#Cumulative €"], [rows])), active="/admin/revenue", admin=True, flash=flash)


PIPE = ("proposed", "sent", "interviewing", "hired", "rejected")


def employer_detail(req, roles, role, candidates, shortlist, share_url, fee_eur, flash=None):
    role_opts = "".join('<option%s>%s</option>' % (" selected" if r["title"] == role else "", e(r["title"])) for r in roles)
    in_list = {s["profile_token"] for s in shortlist}
    cand_rows = "".join("<tr><td>%s<br><small class=\"muted\">%s</small></td><td class=\"num\">%d%%</td><td><small>%s</small></td><td><small>%s</small></td><td>%s</td></tr>" % (
        e(c["profile"]["name"]), e(", ".join(c["profile"].get("skills", [])[:6])), c["match"]["overall"], e(c["match"]["verdict"].lower()),
        e("; ".join(c["match"]["gaps"][:2]) or "—"),
        "in shortlist" if c["token"] in in_list else _form("/admin/employers/%d/shortlist" % req["id"], "Add",
            '<input type="hidden" name="profile" value="%s"><input type="hidden" name="role" value="%s"><input type="hidden" name="score" value="%d">' % (e(c["token"]), e(role), c["match"]["overall"])))
        for c in candidates)
    sl_rows = "".join("<tr><td>%s</td><td><small>%s</small></td><td class=\"num\">%s%%</td><td>%s</td><td>%s</td></tr>" % (
        e(s["name"]), e(s["role"]), e(s["score"]), e(s["status"]),
        _form("/admin/shortlists/%d/status" % s["id"], "Update", '<select name="status">%s</select>' % "".join(
            '<option%s>%s</option>' % (" selected" if st == s["status"] else "", st) for st in PIPE))) for s in shortlist)
    hired = sum(1 for s in shortlist if s["status"] == "hired")
    return layout("Admin · " + req["company"], """<section><div class="wrap stack"><a href="/admin/employers">← Employer requests</a>
<h1>%s</h1><p class="muted">%s · %s · wants %s · contact %s, %s %s</p><div class="card"><b>Roles requested</b><p style="white-space:pre-line;margin:6px 0 0">%s</p></div>
<div class="kpis"><div class="kpi"><b>%d</b><span>In shortlist</span></div><div class="kpi"><b>%d</b><span>Hired</span></div><div class="kpi"><b>€%s</b><span>Placement fees earned (€%s each)</span></div></div>
<h2>Shortlist</h2>%s<div class="row"><span class="muted">Employer link (private):</span><a class="mono" href="%s" target="_blank" rel="noopener">%s</a></div>
<h2>Find candidates</h2><form method="get" class="row"><label style="min-width:260px">Role template<select name="role">%s</select></label><button class="btn small" type="submit">Rank candidates</button></form>
<p class="muted">Only candidates who opted in to sharing their CV are listed. Scores support your judgement; you choose who goes on the shortlist.</p>%s</div></section>""" % (
        e(req["company"]), e(req["sector"]), e(req["country"]), e(req["headcount"]), e(req["contact_name"]), e(req["email"]), e(req["phone"] or ""), e(req["roles"]),
        len(shortlist), hired, format(hired * fee_eur, ","), fee_eur,
        _table(["Candidate", "Role", "#Score", "Status", "Update"], [sl_rows] if sl_rows else [], "No candidates added yet."), e(share_url), e(share_url), role_opts,
        _table(["Candidate", "#Match", "Verdict", "Gaps", ""], [cand_rows] if cand_rows else [], "No opted-in candidates yet. They appear when people complete /match and tick the sharing box.")),
        active="/admin/employers", admin=True, flash=flash)
