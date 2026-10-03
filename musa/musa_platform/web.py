"""HTTP server: public site, business portal, admin console, JSON API, WhatsApp bot — one process.

Run:  python -m musa_platform serve        (PORT, default 8080)
"""
import json
import mimetypes
import urllib.parse
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from musa_sentinel import matching, payments, revenue, traps as traps_mod, whatsapp, leadlog

from . import DATA_DIR, STATIC_DIR, admin_ui, agents, compliance, db, scout, seo, ui

FLASH = {
    "verified": ("ok", "Marked verified."), "flagged": ("ok", "Flagged."), "expired": ("ok", "Expired."), "added": ("ok", "Opportunity added."),
    "paid": ("ok", "Payment confirmed."), "delivered": ("ok", "Marked delivered."), "approved": ("ok", "Partner approved; badge page is live."),
    "rejected": ("ok", "Application rejected."), "revoked": ("ok", "Badge revoked."), "contacted": ("ok", "Marked contacted."),
    "scout": ("ok", "Scout finished."), "retention": ("ok", "Retention policy applied."), "closed": ("ok", "Request closed."),
    "erased": ("ok", "Personal data erased and logged."), "applied": ("ok", "Application received. We will email you within 2 working days."),
    "requested": ("ok", "Request received. We will reply within 1 working day."), "deleted": ("ok", "Your profile was deleted."),
    "claimed": ("ok", "Thank you. We will confirm your payment and start your report."),
}
EXAMPLE_SCAM = ("Assalam o alaikum brother. Cyprus construction visa 100% guarantee hai. Total package 9 lakh rupees. "
                "Embassy appointment not available, we arrange it. Pay today, only 3 seats left. Send to my personal account, contract after payment.")
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
                               "img-src 'self' data:; form-action 'self' https:; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "strict-origin-when-cross-origin", "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}
POST_LIMIT = (30, 600)  # 30 form posts per IP per 10 minutes


class State:
    def __init__(self):
        self.traps = traps_mod.load_traps()
        self.knowledge = agents.load_knowledge()
        self.payments = payments.load_config()
        self.pricing = revenue.load_pricing()
        with open(os.path.join(DATA_DIR, "roles.json"), encoding="utf-8") as f:
            self.roles = json.load(f)["roles"]
        self.guides = seo.guides(self.knowledge, self.traps)
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def rate_ok(self, ip, now=None):
        now = now or time.time()
        limit, window = POST_LIMIT
        with self.lock:
            q = self.hits[ip]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


def web_ref(product):
    return "MUSA-%s-%04d-%s" % (payments.PRODUCT_CODES.get(product, "X"), secrets.randbelow(10000), secrets.token_hex(2).upper())


def stats():
    return {
        "opps": db.count("SELECT COUNT(*) FROM opportunities WHERE status IN ('lead','signal','verified')"),
        "visa": db.count("SELECT COUNT(*) FROM opportunities WHERE visa_signal=1 AND status IN ('lead','signal','verified')"),
        "scans_7d": db.count("SELECT COUNT(*) FROM scans WHERE created_at > ?", (db.now_iso(-7),)),
        "partners": db.count("SELECT COUNT(*) FROM partners WHERE status='approved'"),
    }


def admin_kpis(bot):
    last = db.q("SELECT started_at FROM scout_runs ORDER BY id DESC LIMIT 1", one=True)
    return {
        "orders_claimed": db.count("SELECT COUNT(*) FROM orders WHERE status='claimed'"),
        "orders_paid": db.count("SELECT COUNT(*) FROM orders WHERE status='paid'"),
        "partners_pending": db.count("SELECT COUNT(*) FROM partners WHERE status='pending'"),
        "employers_new": db.count("SELECT COUNT(*) FROM employer_requests WHERE status='new'"),
        "dsar_open": db.count("SELECT COUNT(*) FROM dsar WHERE status='open'"),
        "revenue_pkr": db.count("SELECT COALESCE(SUM(amount_pkr),0) FROM orders WHERE status IN ('paid','delivered')"),
        "opps_live": db.count("SELECT COUNT(*) FROM opportunities WHERE status IN ('lead','signal','verified')"),
        "opps_verified": db.count("SELECT COUNT(*) FROM opportunities WHERE status='verified'"),
        "scans_7d": db.count("SELECT COUNT(*) FROM scans WHERE created_at > ?", (db.now_iso(-7),)),
        "questions_7d": db.count("SELECT COUNT(*) FROM questions WHERE created_at > ?", (db.now_iso(-7),)),
        "partners_live": db.count("SELECT COUNT(*) FROM partners WHERE status='approved'"),
        "last_scout": last["started_at"][:16].replace("T", " ") if last else "never",
        "sources_on": sum(1 for x in scout.load_sources() if x.get("enabled") and x.get("url")),
        "wa": leadlog.summarise(leadlog.load(bot.leads_file)),
    }


def admin_queue(k):
    q = []
    if k["orders_paid"]:
        q.append(("/admin/orders", "Deliver %d paid report(s)" % k["orders_paid"]))
    if k["orders_claimed"]:
        q.append(("/admin/orders", "Confirm %d payment(s) customers reported" % k["orders_claimed"]))
    wa = k["wa"]
    if wa["to_deliver"] or wa["to_verify"] or wa["hot"]:
        q.append(("/admin/leads", "WhatsApp: %d to deliver, %d payments to verify, %d report requests" % (wa["to_deliver"], wa["to_verify"], wa["hot"])))
    if k["dsar_open"]:
        q.append(("/admin/compliance", "Answer %d data request(s) (legal deadline: 1 month)" % k["dsar_open"]))
    if k["employers_new"]:
        q.append(("/admin/employers", "Call back %d employer(s)" % k["employers_new"]))
    if k["partners_pending"]:
        q.append(("/admin/partners", "Run KYB on %d partner application(s)" % k["partners_pending"]))
    return q


def opportunity_filters(qs):
    where, args = ["status IN ('lead','signal','verified')"], []
    if qs.get("sector"):
        where.append("sector=?"); args.append(qs["sector"])
    if qs.get("visa") == "1":
        where.append("visa_signal=1")
    if qs.get("tier") in ("0", "2"):
        where.append("source_tier<=?"); args.append(int(qs["tier"]))
    if qs.get("q"):
        where.append("(title LIKE ? OR summary LIKE ? OR employer LIKE ? OR location LIKE ?)")
        args += ["%" + qs["q"][:60] + "%"] * 4
    return " AND ".join(where), args


def make_handler(state, bot, verify_token=None, app_secret=None, admin_password=None, stripe_secret=None):
    Base = whatsapp.make_handler(bot, verify_token, app_secret, admin_password, stripe_secret)
    BOT_GET = {"/webhook", "/admin/leads"}

    class Handler(Base):
        server_version = "MUSA-Corridor/1.0"

        def log_message(self, fmt, *args):  # path only: no query strings (they can hold questions) and no IPs
            print("[musa] %s %s" % (self.command, urlparse(self.path).path), flush=True)

        # ---------- plumbing ----------
        def end_headers(self):
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            super().end_headers()

        def html(self, body, code=200):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def text(self, body, ctype):
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(data)

        def json_out(self, obj, code=200):
            data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def redirect(self, to):
            self.send_response(303)
            self.send_header("Location", to)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def form(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64_000:
                return None
            raw = self.rfile.read(n).decode("utf-8", "replace")
            ctype = self.headers.get("Content-Type", "")
            if "json" in ctype:
                try:
                    data = json.loads(raw or "{}")
                    return data if isinstance(data, dict) else {}
                except ValueError:
                    return {}
            return {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}

        def ip(self):
            return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

        def flash(self, qs):
            return FLASH.get(qs.get("m", ""))

        def same_origin(self):
            origin = self.headers.get("Origin")
            return not origin or urlparse(origin).netloc == self.headers.get("Host")

        # ---------- GET ----------
        def do_GET(self):
            u = urlparse(self.path)
            path, qs = u.path.rstrip("/") or "/", {k: v[0] for k, v in parse_qs(u.query).items()}
            if path in BOT_GET or path == "/health":
                return super().do_GET()
            if path.startswith("/static/"):
                return self.static(path[len("/static/"):])
            if path.startswith("/admin"):
                if not self._admin_ok():
                    return
                return self.admin_get(path, qs)
            route = self.public_get(path, qs)
            if route is None:
                self.html(ui.not_found(), 404)

        def static(self, name):
            if not re.fullmatch(r"[a-z0-9_-]+\.(css|js|svg|png|ico)", name):
                return self._send(404)
            fp = os.path.join(STATIC_DIR, name)
            if not os.path.isfile(fp):
                return self._send(404)
            with open(fp, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(fp)[0] or "application/octet-stream")
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def public_get(self, path, qs):
            if path == "/":
                latest = db.q("SELECT * FROM opportunities WHERE status IN ('lead','signal','verified') ORDER BY (status='verified') DESC, source_tier ASC, found_at DESC LIMIT 6")
                return self.html(ui.home(stats(), latest)) or True
            if path == "/check":
                return self.html(ui.check_page(EXAMPLE_SCAM, self.scan(EXAMPLE_SCAM, "web-example")) if qs.get("example") else ui.check_page()) or True
            if path == "/opportunities":
                where, args = opportunity_filters(qs)
                rows = db.q("SELECT * FROM opportunities WHERE %s ORDER BY (status='verified') DESC, source_tier ASC, found_at DESC LIMIT 100" % where, args)
                total = db.count("SELECT COUNT(*) FROM opportunities WHERE %s" % where, args)
                sectors = [r[0] for r in db.q("SELECT DISTINCT sector FROM opportunities WHERE sector != '' ORDER BY sector")]
                return self.html(ui.opportunities_page(rows, sectors, qs, total)) or True
            m = re.fullmatch(r"/opportunities/(\d+)", path)
            if m:
                o = db.q("SELECT * FROM opportunities WHERE id=?", (int(m.group(1)),), one=True)
                return (self.html(ui.opportunity_detail(o)) or True) if o else None
            if path == "/match":
                return self.html(ui.match_page(flash=self.flash(qs))) or True
            m = re.fullmatch(r"/cv/([A-Za-z0-9_-]{16,64})", path)
            if m:
                p = db.q("SELECT * FROM profiles WHERE token=?", (m.group(1),), one=True)
                return (self.html(ui.cv_page(json.loads(p["data"]), p["token"])) or True) if p else None
            if path == "/ask":
                question = qs.get("q", "")
                result = agents.ask(question, state.knowledge) if question.strip() else None
                return self.html(ui.ask_page(question, result, [e["q"] for e in state.knowledge[:5]])) or True
            if path == "/pricing":
                return self.html(ui.pricing_page(state.pricing["products"])) or True
            if path == "/report":
                opp = None
                if (qs.get("opp") or "").isdigit():
                    opp = db.q("SELECT * FROM opportunities WHERE id=?", (int(qs["opp"]),), one=True)
                product = qs.get("product") if qs.get("product") in state.payments["products"] else "verify_basic"
                return self.html(ui.report_page(state.payments, product, opp)) or True
            m = re.fullmatch(r"/order/(MUSA-[A-Z]-\d{4}-[0-9A-F]{4})", path)
            if m:
                o = db.q("SELECT * FROM orders WHERE ref=?", (m.group(1),), one=True)
                if not o:
                    return None
                return self.html(ui.order_page(o, state.payments, payments.active_methods(state.payments, o["product"]), self.flash(qs))) or True
            if path == "/business":
                return self.html(ui.business_page(state.pricing["products"])) or True
            if path == "/business/partners":
                return self.html(ui.partner_apply_page()) or True
            if path == "/business/employers":
                return self.html(ui.employer_page()) or True
            m = re.fullmatch(r"/partners/([a-z0-9-]{3,80})", path)
            if m:
                p = db.q("SELECT * FROM partners WHERE slug=? AND status='approved'", (m.group(1),), one=True)
                return (self.html(ui.partner_badge(p)) or True) if p else None
            if path == "/guides":
                return self.html(seo.guides_index(state.guides)) or True
            m = re.fullmatch(r"/guides/([a-z0-9-]+)", path)
            if m:
                g = next((g for g in state.guides if g["slug"] == m.group(1)), None)
                return (self.html(seo.guide_page(g, state.traps)) or True) if g else None
            m = re.fullmatch(r"/jobs/([a-z0-9-]+)", path)
            if m:
                sector = next((x for x in seo.SECTOR_INTRO if seo.slugify(x) == m.group(1)), None)
                if not sector:
                    return None
                live = "sector=? AND status IN ('lead','signal','verified')"
                rows = db.q("SELECT * FROM opportunities WHERE %s ORDER BY (status='verified') DESC, source_tier, found_at DESC LIMIT 50" % live, (sector,))
                return self.html(seo.sector_page(sector, rows, db.count("SELECT COUNT(*) FROM opportunities WHERE " + live, (sector,)),
                                                 db.count("SELECT COUNT(*) FROM opportunities WHERE visa_signal=1 AND " + live, (sector,)))) or True
            if path == "/sitemap.xml":
                xml = seo.sitemap(state.guides, [x for x in seo.SECTOR_INTRO if x != "General"])
                return (self.text(xml, "application/xml") or True) if xml else None
            if path == "/robots.txt":
                return self.text(seo.robots(), "text/plain") or True
            m = re.fullmatch(r"/shortlist/([A-Za-z0-9_-]{16,64})", path)
            if m:
                rows = db.q("SELECT s.*, p.data FROM shortlists s JOIN profiles p ON p.token=s.profile_token WHERE s.token=? AND s.status!='rejected' ORDER BY s.score DESC", (m.group(1),))
                if not rows:
                    return None
                req = db.q("SELECT * FROM employer_requests WHERE id=?", (rows[0]["request_id"],), one=True)
                items = [dict(r, profile=json.loads(r["data"])) for r in rows if json.loads(r["data"]).get("share_ok")]
                db.audit("employer", "shortlist.viewed", target=rows[0]["request_id"])
                return self.html(ui.shortlist_page(req, items)) or True
            if path == "/agents":
                return self.html(ui.agents_page(agents.REGISTRY)) or True
            if path == "/privacy":
                return self.html(ui.privacy_page()) or True
            if path == "/privacy/request":
                return self.html(ui.privacy_request_page(done=qs.get("m") == "requested")) or True
            if path == "/terms":
                return self.html(ui.terms_page()) or True
            if path == "/api/opportunities":
                where, args = opportunity_filters(qs)
                rows = db.q("SELECT id,title,sector,country,location,employer,url,source,source_tier,visa_signal,status,found_at FROM opportunities WHERE %s ORDER BY found_at DESC LIMIT 200" % where, args)
                return self.json_out({"count": len(rows), "items": [dict(r) for r in rows]}) or True
            if path == "/api/stats":
                return self.json_out(stats()) or True
            return None

        # ---------- POST ----------
        def do_POST(self):
            u = urlparse(self.path)
            path = u.path.rstrip("/") or "/"
            if path in ("/webhook", "/stripe/webhook") or path.startswith("/admin/leads/"):
                return super().do_POST()
            if path.startswith("/admin"):
                if not self._admin_ok():
                    return
                if not self.same_origin():
                    return self._send(403)
                return self.admin_post(path)
            if not state.rate_ok(self.ip()):
                return self.html(ui.layout("Slow down", '<section><div class="wrap"><h1>Too many requests</h1><p>Please wait a few minutes and try again.</p></div></section>'), 429)
            f = self.form()
            if f is None:
                return self._send(413)
            if path == "/check":
                text = (f.get("text") or "")[:6000]
                return self.html(ui.check_page(text, self.scan(text, "web") if text.strip() else None))
            if path == "/api/scan":
                text = (f.get("text") or "")[:6000]
                res = self.scan(text, "api")
                return self.json_out({"decision": res["decision"], "hits": [{k: h[k] for k in ("id", "name", "severity", "response", "response_ur")} for h in res["hits"]]})
            if path == "/match":
                return self.post_match(f)
            m = re.fullmatch(r"/cv/([A-Za-z0-9_-]{16,64})/delete", path)
            if m:
                db.x("DELETE FROM profiles WHERE token=?", (m.group(1),))
                db.audit("subject", "profile.deleted", target=m.group(1)[:6] + "…")
                return self.redirect("/match?m=deleted")
            if path == "/report":
                return self.post_report(f)
            m = re.fullmatch(r"/order/(MUSA-[A-Z]-\d{4}-[0-9A-F]{4})/paid", path)
            if m:
                db.x("UPDATE orders SET status='claimed', claimed_at=? WHERE ref=? AND status='requested'", (db.now_iso(), m.group(1)))
                return self.redirect("/order/%s?m=claimed" % m.group(1))
            if path == "/business/partners":
                return self.post_partner(f)
            if path == "/business/employers":
                return self.post_employer(f)
            if path == "/privacy/request":
                contact = (f.get("contact") or "").strip()[:120]
                if contact:
                    db.insert("dsar", at=db.now_iso(), contact=contact, kind="erase" if f.get("kind") == "erase" else "export")
                    db.audit("subject", "dsar.received", target=compliance._mask(contact))
                return self.redirect("/privacy/request?m=requested")
            self.html(ui.not_found(), 404)

        def scan(self, text, channel):
            res = traps_mod.assess_message(text, state.traps)
            db.insert("scans", created_at=db.now_iso(), colour=res["decision"]["colour"], score=res["decision"]["risk"]["score"],
                      traps=",".join(h["id"] for h in res["hits"]), channel=channel)
            return res

        def post_match(self, f):
            if not f.get("consent"):
                return self.html(ui.match_page(profile=agents.parse_profile_form(f)), 400)
            profile = agents.parse_profile_form(f)
            if not profile["name"] or not profile["skills"]:
                return self.html(ui.match_page(profile=profile), 400)
            token = secrets.token_urlsafe(18)
            db.insert("profiles", token=token, name=profile["name"], contact=(f.get("contact") or "").strip()[:80],
                      data=json.dumps(profile, ensure_ascii=False), created_at=db.now_iso(), consent_at=db.now_iso())
            results = matching.rank(profile, state.roles)
            top_sector = next((r["sector"] for r in state.roles if r["title"] == results[0]["job"]), None) if results else None
            live = db.q("SELECT * FROM opportunities WHERE sector=? AND status IN ('lead','signal','verified') ORDER BY source_tier, found_at DESC LIMIT 4", (top_sector,)) if top_sector else []
            return self.html(ui.match_page(results, profile, token, live))

        def post_report(self, f):
            product = f.get("product") if f.get("product") in state.payments["products"] else "verify_basic"
            name, contact, details = (f.get("name") or "").strip()[:80], (f.get("contact") or "").strip()[:80], (f.get("details") or "").strip()[:3000]
            if not (name and contact and details and f.get("consent")):
                return self.html(ui.report_page(state.payments, product, error="Please fill in every field and tick the consent box."), 400)
            ref = web_ref(product)
            db.insert("orders", ref=ref, product=product, name=name, contact=contact, details=details,
                      amount_pkr=state.payments["products"][product]["pkr"], created_at=db.now_iso(), consent_at=db.now_iso())
            db.audit("customer", "order.created", target=ref)
            return self.redirect("/order/" + ref)

        def post_partner(self, f):
            required = ("org_name", "org_type", "country", "contact_name", "email")
            if not all((f.get(k) or "").strip() for k in required) or not f.get("consent"):
                return self.html(ui.partner_apply_page("Please complete the required fields and tick the confirmation box."), 400)
            clean = {k: (f.get(k) or "").strip()[:2000 if k == "message" else 160] for k in
                     ("org_name", "org_type", "country", "licence_no", "registry_no", "contact_name", "email", "phone", "website", "tier", "message")}
            pid = db.insert("partners", created_at=db.now_iso(), consent_at=db.now_iso(), **clean)
            db.audit("applicant", "partner.applied", target=pid)
            return self.html(ui.layout("Application received", '<section><div class="wrap stack" style="max-width:720px"><span class="stamp amber">Received</span><h1>Thank you, %s</h1><p>We will check your licence and registration and email <b>%s</b> within 2 working days to book the verification call.</p><a class="btn" href="/business">Back</a></div></section>' % (ui.e(clean["org_name"]), ui.e(clean["email"]))))

        def post_employer(self, f):
            if not all((f.get(k) or "").strip() for k in ("company", "roles", "contact_name", "email")) or not f.get("consent"):
                return self.html(ui.employer_page("Please complete the required fields and tick the consent box."), 400)
            try:
                head = max(1, min(500, int(f.get("headcount") or 1)))
            except ValueError:
                head = 1
            clean = {k: (f.get(k) or "").strip()[:2000] for k in ("company", "country", "sector", "roles", "contact_name", "email", "phone", "message")}
            rid = db.insert("employer_requests", headcount=head, created_at=db.now_iso(), consent_at=db.now_iso(), **clean)
            db.audit("employer", "employer.requested", target=rid)
            return self.html(ui.layout("Request received", '<section><div class="wrap stack" style="max-width:720px"><span class="stamp green">Received</span><h1>Thank you</h1><p>We will contact %s within 1 working day to confirm roles, timing and the licensed agency that will handle the permits.</p><a class="btn" href="/business">Back</a></div></section>' % ui.e(clean["contact_name"])))

        def shortlist_token(self, rid):
            row = db.q("SELECT token FROM shortlists WHERE request_id=? LIMIT 1", (rid,), one=True)
            return row["token"] if row else secrets.token_urlsafe(18)

        def employer_detail(self, rid, qs, fl):
            req = db.q("SELECT * FROM employer_requests WHERE id=?", (rid,), one=True)
            if not req:
                return self.html(ui.not_found(), 404)
            roles = [r for r in state.roles if r["sector"] == req["sector"]] or state.roles
            role = qs.get("role") if any(r["title"] == qs.get("role") for r in roles) else roles[0]["title"]
            tpl = next(r for r in roles if r["title"] == role)
            cands = []
            for p in db.q("SELECT token, data FROM profiles ORDER BY created_at DESC LIMIT 2000"):
                prof = json.loads(p["data"])
                if prof.get("share_ok"):
                    cands.append({"token": p["token"], "profile": prof, "match": matching.match(prof, tpl)})
            cands.sort(key=lambda c: -c["match"]["overall"])
            shortlist = [dict(r, name=json.loads(r["data"]).get("name") if r["data"] else "[deleted]") for r in db.q(
                "SELECT s.*, p.data FROM shortlists s LEFT JOIN profiles p ON p.token=s.profile_token WHERE s.request_id=? ORDER BY s.score DESC", (rid,))]
            token = shortlist[0]["token"] if shortlist else None
            base = ui.site_url() or ("http://" + (self.headers.get("Host") or "localhost"))
            share = (base + "/shortlist/" + token) if token else "(add a candidate to create the link)"
            fee = next((p["price"] for p in state.pricing["products"] if p["id"] == "employer_sourcing"), 400)
            return self.html(admin_ui.employer_detail(req, roles, role, cands[:50], shortlist, share, fee, fl))

        # ---------- admin ----------
        def admin_get(self, path, qs):
            fl = self.flash(qs)
            if path == "/admin":
                k = admin_kpis(bot)
                return self.html(admin_ui.overview(k, admin_queue(k), fl))
            if path == "/admin/opportunities":
                status = qs.get("status") if qs.get("status") in ("lead", "signal", "verified", "flagged", "expired") else "lead"
                return self.html(admin_ui.opportunities(db.q("SELECT * FROM opportunities WHERE status=? ORDER BY source_tier, found_at DESC LIMIT 300", (status,)), status, fl))
            if path == "/admin/orders":
                return self.html(admin_ui.orders(db.q("SELECT * FROM orders ORDER BY CASE status WHEN 'paid' THEN 0 WHEN 'claimed' THEN 1 WHEN 'requested' THEN 2 ELSE 3 END, created_at DESC LIMIT 300"), fl))
            if path == "/admin/partners":
                return self.html(admin_ui.partners(db.q("SELECT * FROM partners ORDER BY status='pending' DESC, created_at DESC"), fl))
            if path == "/admin/employers":
                return self.html(admin_ui.employers(db.q("SELECT * FROM employer_requests ORDER BY status='new' DESC, created_at DESC"), fl))
            m = re.fullmatch(r"/admin/employers/(\d+)", path)
            if m:
                return self.employer_detail(int(m.group(1)), qs, fl)
            if path == "/admin/scout":
                return self.html(admin_ui.scout(scout.load_sources(), db.q("SELECT * FROM scout_runs ORDER BY id DESC LIMIT 50"), fl))
            if path == "/admin/compliance":
                return self.html(admin_ui.compliance(db.q("SELECT * FROM dsar ORDER BY status='open' DESC, at DESC"), db.q("SELECT * FROM audit ORDER BY id DESC LIMIT 100"), flash=fl))
            if path == "/admin/revenue":
                actual = db.q("SELECT COALESCE(SUM(amount_pkr),0) pkr, COUNT(*) count FROM orders WHERE status IN ('paid','delivered')", one=True)
                actual = dict(actual)
                actual["placements"] = db.count("SELECT COUNT(*) FROM shortlists WHERE status='hired'")
                actual["placement_eur"] = actual["placements"] * next((p["price"] for p in state.pricing["products"] if p["id"] == "employer_sourcing"), 400)
                return self.html(admin_ui.revenue(revenue.forecast(12, "base", state.pricing), actual, fl))
            self.html(ui.not_found(), 404)

        def admin_post(self, path):
            f = self.form() or {}
            m = re.fullmatch(r"/admin/opportunities/(\d+)/(verify|flag|expire)", path)
            if m:
                new = {"verify": "verified", "flag": "flagged", "expire": "expired"}[m.group(2)]
                db.x("UPDATE opportunities SET status=?, updated_at=? WHERE id=?", (new, db.now_iso(), int(m.group(1))))
                db.audit("admin", "opportunity." + new, target=m.group(1))
                return self.redirect("/admin/opportunities?status=%s&m=%s" % (new, new))
            if path == "/admin/opportunities/add":
                if (f.get("title") or "").strip() and (f.get("source") or "").strip():
                    tier = int(f.get("tier") or 4) if (f.get("tier") or "4").isdigit() else 4
                    scout.ingest([{"title": f["title"].strip(), "url": (f.get("url") or "").strip(), "summary": (f.get("summary") or "").strip(),
                                   "employer": (f.get("employer") or "").strip(), "country": (f.get("country") or "").strip()}],
                                 {"name": f["source"].strip()[:120], "tier": tier})
                    db.audit("admin", "opportunity.added", detail={"title": f["title"][:80]})
                return self.redirect("/admin/opportunities?m=added")
            m = re.fullmatch(r"/admin/orders/(MUSA-[A-Z]-\d{4}-[0-9A-F]{4})/(paid|delivered)", path)
            if m:
                ref, act = m.groups()
                if act == "paid":
                    db.x("UPDATE orders SET status='paid', paid_at=?, method=? WHERE ref=? AND status IN ('requested','claimed')",
                         (db.now_iso(), (f.get("method") or "manual")[:20], ref))
                else:
                    db.x("UPDATE orders SET status='delivered', delivered_at=? WHERE ref=? AND status='paid'", (db.now_iso(), ref))
                db.audit("admin", "order." + act, target=ref)
                return self.redirect("/admin/orders?m=" + act)
            m = re.fullmatch(r"/admin/partners/(\d+)/(approve|reject|revoke)", path)
            if m:
                pid, act = int(m.group(1)), m.group(2)
                p = db.q("SELECT * FROM partners WHERE id=?", (pid,), one=True)
                if p:
                    if act == "approve":
                        slug = re.sub(r"[^a-z0-9]+", "-", p["org_name"].lower()).strip("-")[:60] or "partner"
                        if db.q("SELECT 1 FROM partners WHERE slug=? AND id!=?", (slug, pid), one=True):
                            slug = "%s-%d" % (slug, pid)
                        db.x("UPDATE partners SET status='approved', slug=?, decided_at=? WHERE id=?", (slug, db.now_iso(), pid))
                    else:
                        db.x("UPDATE partners SET status=?, decided_at=? WHERE id=?", ("rejected" if act == "reject" else "revoked", db.now_iso(), pid))
                    db.audit("admin", "partner." + act, target=pid)
                return self.redirect("/admin/partners?m=%s" % {"approve": "approved", "reject": "rejected", "revoke": "revoked"}[act])
            m = re.fullmatch(r"/admin/employers/(\d+)/shortlist", path)
            if m:
                rid = int(m.group(1))
                prof = db.q("SELECT token FROM profiles WHERE token=?", ((f.get("profile") or "")[:64],), one=True)
                req = db.q("SELECT * FROM employer_requests WHERE id=?", (rid,), one=True)
                if prof and req:
                    token = self.shortlist_token(rid)
                    try:
                        score = max(0, min(100, int(f.get("score") or 0)))
                    except ValueError:
                        score = 0
                    db.x("INSERT OR IGNORE INTO shortlists (request_id, token, role, profile_token, score, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                         (rid, token, (f.get("role") or "")[:120], prof["token"], score, db.now_iso(), db.now_iso()))
                    db.audit("admin", "shortlist.add", target=rid)
                return self.redirect("/admin/employers/%d?m=added&role=%s" % (rid, urllib.parse.quote(f.get("role") or "")))
            m = re.fullmatch(r"/admin/shortlists/(\d+)/status", path)
            if m:
                st = f.get("status") if f.get("status") in admin_ui.PIPE else "proposed"
                row = db.q("SELECT request_id FROM shortlists WHERE id=?", (int(m.group(1)),), one=True)
                if row:
                    db.x("UPDATE shortlists SET status=?, updated_at=? WHERE id=?", (st, db.now_iso(), int(m.group(1))))
                    db.audit("admin", "shortlist." + st, target=m.group(1))
                    return self.redirect("/admin/employers/%d" % row["request_id"])
                return self.redirect("/admin/employers")
            m = re.fullmatch(r"/admin/employers/(\d+)/contacted", path)
            if m:
                db.x("UPDATE employer_requests SET status='contacted' WHERE id=?", (int(m.group(1)),))
                db.audit("admin", "employer.contacted", target=m.group(1))
                return self.redirect("/admin/employers?m=contacted")
            if path == "/admin/scout/run":
                scout.run_all()
                return self.redirect("/admin/scout?m=scout")
            if path == "/admin/compliance/retention":
                compliance.run_retention()
                scout.expire_stale()
                return self.redirect("/admin/compliance?m=retention")
            m = re.fullmatch(r"/admin/compliance/dsar/(\d+)/(export|erase|close)", path)
            if m:
                d = db.q("SELECT * FROM dsar WHERE id=?", (int(m.group(1)),), one=True)
                if not d:
                    return self.redirect("/admin/compliance")
                if m.group(2) == "export":
                    data = compliance.export(d["contact"])
                    return self.html(admin_ui.compliance(db.q("SELECT * FROM dsar ORDER BY status='open' DESC, at DESC"), db.q("SELECT * FROM audit ORDER BY id DESC LIMIT 100"), data))
                if m.group(2) == "erase":
                    done = compliance.erase(d["contact"])
                    db.x("UPDATE dsar SET status='done', resolved_at=?, note=?, contact=? WHERE id=?",
                         (db.now_iso(), json.dumps(done), compliance._mask(d["contact"]), d["id"]))
                    return self.redirect("/admin/compliance?m=erased")
                db.x("UPDATE dsar SET status='done', resolved_at=? WHERE id=?", (db.now_iso(), d["id"]))
                return self.redirect("/admin/compliance?m=closed")
            self.html(ui.not_found(), 404)

    return Handler


# ---------------- background agents ----------------

def scheduler(stop, scout_hours=None, retention_hours=24):
    scout_every = float(scout_hours or os.environ.get("MUSA_SCOUT_HOURS", 6)) * 3600
    retention_every = retention_hours * 3600
    next_scout = time.time() + 60
    next_ret = time.time() + 300
    while not stop.wait(30):
        try:
            if time.time() >= next_scout:
                scout.run_all()
                next_scout = time.time() + scout_every
            if time.time() >= next_ret:
                compliance.run_retention()
                scout.expire_stale()
                next_ret = time.time() + retention_every
        except Exception as e:
            db.audit("system", "scheduler.error", detail={"error": "%s: %s" % (type(e).__name__, e)})


def build_server(port=None, host="0.0.0.0"):
    state = State()
    scout.seed()
    bot = whatsapp.Bot()
    handler = make_handler(state, bot, os.environ.get("WA_VERIFY_TOKEN"), os.environ.get("WA_APP_SECRET"),
                           os.environ.get("MUSA_ADMIN_PASSWORD"), os.environ.get("STRIPE_WEBHOOK_SECRET"))
    return ThreadingHTTPServer((host, int(port or os.environ.get("PORT", 8080))), handler)


def serve(port=None):
    httpd = build_server(port)
    stop = threading.Event()
    threading.Thread(target=scheduler, args=(stop,), daemon=True).start()
    print("[musa] MUSA Corridor on http://%s:%d  (admin %s)" % (httpd.server_address[0], httpd.server_address[1],
          "enabled" if os.environ.get("MUSA_ADMIN_PASSWORD") else "disabled — set MUSA_ADMIN_PASSWORD"), flush=True)
    try:
        httpd.serve_forever()
    finally:
        stop.set()
