import base64
import json
import os
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = tempfile.mkdtemp()
os.environ["MUSA_DB"] = os.path.join(TMP, "test.db")
os.environ["MUSA_LEADS_FILE"] = os.path.join(TMP, "leads.jsonl")
os.environ["MUSA_CONCIERGE_AI"] = "auto"
os.environ.pop("ANTHROPIC_API_KEY", None)

from musa_platform import agents, compliance, db, scout, web  # noqa: E402
from musa_sentinel import whatsapp  # noqa: E402

AUTH = {"Authorization": "Basic " + base64.b64encode(b"admin:pw").decode()}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Server:
    def __init__(self):
        state = web.State()
        scout.seed()
        bot = whatsapp.Bot(leads_file=os.environ["MUSA_LEADS_FILE"])
        self.state = state
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), web.make_handler(state, bot, "vt", "as", "pw", "whsec_test"))
        self.httpd.RequestHandlerClass.log_message = lambda *a: None
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def req(self, path, data=None, headers=None, method=None):
        body = data if isinstance(data, bytes) or data is None else urllib.parse.urlencode(data).encode()
        r = urllib.request.Request(self.base + path, data=body, headers=headers or {}, method=method)
        try:
            with urllib.request.build_opener(NoRedirect).open(r) as resp:
                return resp.status, resp.read().decode(), dict(resp.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace"), dict(e.headers)


import urllib.parse  # noqa: E402

SRV = None


def setUpModule():
    global SRV
    SRV = Server()


def tearDownModule():
    SRV.httpd.shutdown()
    SRV.httpd.server_close()


class PublicPages(unittest.TestCase):
    def test_all_public_pages_render(self):
        for path in ["/", "/check", "/check?example=1", "/opportunities", "/opportunities?visa=1&sector=Hospitality", "/opportunities/1",
                     "/match", "/ask", "/pricing", "/report", "/report?opp=1", "/business", "/business/partners",
                     "/business/employers", "/agents", "/privacy", "/privacy/request", "/terms", "/static/site.css"]:
            code, body, _ = SRV.req(path)
            self.assertEqual(code, 200, path)
        self.assertEqual(SRV.req("/opportunities/99999")[0], 404)
        self.assertEqual(SRV.req("/static/../web.py")[0], 404)

    def test_security_headers(self):
        _, _, h = SRV.req("/")
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")

    def test_home_shows_seeded_opportunities_and_mrz(self):
        _, body, _ = SRV.req("/")
        self.assertIn("P&lt;PAK&lt;&lt;CYP", body)
        self.assertIn("Visa sponsorship mentioned", body)

    def test_output_is_escaped(self):
        _, body, _ = SRV.req("/check", {"text": "<script>alert(1)</script> visa 100% guarantee"})
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)


class Flows(unittest.TestCase):
    def test_scan_is_counted_but_text_not_stored(self):
        before = db.count("SELECT COUNT(*) FROM scans")
        code, body, _ = SRV.req("/check", {"text": "Pay today to my personal account, visa 100% guarantee"})
        self.assertEqual(code, 200)
        self.assertIn("Stop", body)
        self.assertEqual(db.count("SELECT COUNT(*) FROM scans"), before + 1)
        dump = json.dumps([dict(r) for r in db.q("SELECT * FROM scans")])
        self.assertNotIn("personal account", dump)

    def test_api_scan(self):
        code, body, _ = SRV.req("/api/scan", json.dumps({"text": "come on a tourist visa and convert to work permit"}).encode(),
                                {"Content-Type": "application/json"})
        self.assertEqual(json.loads(body)["decision"]["colour"], "RED")

    def test_order_lifecycle(self):
        self.assertEqual(SRV.req("/report", {"name": "A", "contact": "1", "details": "x"})[0], 400)  # no consent
        code, _, h = SRV.req("/report", {"product": "verify_deep", "name": "Ali", "contact": "+92 300 1112223", "details": "OEP 123", "consent": "on"})
        self.assertEqual(code, 303)
        ref = h["Location"].rsplit("/", 1)[1]
        self.assertRegex(ref, r"^MUSA-D-\d{4}-[0-9A-F]{4}$")
        self.assertIn("22,500", SRV.req("/order/" + ref)[1])
        self.assertEqual(SRV.req("/order/%s/paid" % ref, b"")[0], 303)
        self.assertEqual(db.q("SELECT status FROM orders WHERE ref=?", (ref,), one=True)["status"], "claimed")
        self.assertEqual(SRV.req("/admin/orders/%s/paid" % ref, {"method": "bank"}, AUTH)[0], 303)
        self.assertEqual(SRV.req("/admin/orders/%s/delivered" % ref, b"", AUTH)[0], 303)
        self.assertEqual(db.q("SELECT status FROM orders WHERE ref=?", (ref,), one=True)["status"], "delivered")

    def test_match_creates_private_cv_and_delete(self):
        code, body, _ = SRV.req("/match", {"name": "Bilal", "skills": "mason, shuttering", "years": "6", "languages": "en:A2", "consent": "on"})
        self.assertEqual(code, 200)
        self.assertIn("Mason / block layer", body)
        token = re.search(r'/cv/([A-Za-z0-9_-]+)"', body).group(1)
        self.assertIn("Bilal", SRV.req("/cv/" + token)[1])
        self.assertEqual(SRV.req("/cv/%s/delete" % token, b"")[0], 303)
        self.assertEqual(SRV.req("/cv/" + token)[0], 404)

    def test_match_requires_consent(self):
        self.assertEqual(SRV.req("/match", {"name": "X", "skills": "cook"})[0], 400)

    def test_partner_kyb_and_badge(self):
        SRV.req("/business/partners", {"org_name": "Lahore Overseas Ltd", "org_type": "oep", "country": "Pakistan", "contact_name": "A",
                                       "email": "a@example.com", "licence_no": "OEP-1234", "consent": "on"})
        pid = db.q("SELECT id FROM partners WHERE org_name='Lahore Overseas Ltd'", one=True)["id"]
        self.assertEqual(SRV.req("/partners/lahore-overseas-ltd")[0], 404)  # not approved yet
        SRV.req("/admin/partners/%d/approve" % pid, b"", AUTH)
        self.assertEqual(SRV.req("/partners/lahore-overseas-ltd")[0], 404)  # approved but not paid
        ref = db.q("SELECT billing_ref FROM partners WHERE id=?", (pid,), one=True)["billing_ref"]
        self.assertIn("Waiting for payment", SRV.req("/partner/billing/" + ref)[1])
        self.assertEqual(SRV.req("/partner/billing/%s/paid" % ref, b"")[0], 303)
        self.assertEqual(db.q("SELECT billing_status FROM partners WHERE id=?", (pid,), one=True)["billing_status"], "claimed")
        SRV.req("/admin/partners/%d/paid" % pid, b"", AUTH)
        code, body, _ = SRV.req("/partners/lahore-overseas-ltd")
        self.assertEqual(code, 200)
        self.assertIn("OEP-1234", body)
        SRV.req("/admin/partners/%d/revoke" % pid, b"", AUTH)
        self.assertEqual(SRV.req("/partners/lahore-overseas-ltd")[0], 404)

    def test_employer_request(self):
        code, body, _ = SRV.req("/business/employers", {"company": "Limassol Build", "roles": "4 masons", "contact_name": "C", "email": "c@x.cy", "headcount": "4", "consent": "on"})
        self.assertEqual(code, 200)
        self.assertEqual(db.count("SELECT COUNT(*) FROM employer_requests WHERE company='Limassol Build'"), 1)


class Admin(unittest.TestCase):
    def test_admin_requires_auth(self):
        self.assertEqual(SRV.req("/admin")[0], 401)
        for path in ["/admin", "/admin/opportunities", "/admin/orders", "/admin/partners", "/admin/employers", "/admin/scout",
                     "/admin/compliance", "/admin/revenue", "/admin/leads"]:
            self.assertEqual(SRV.req(path, headers=AUTH)[0], 200, path)

    def test_cross_site_admin_post_blocked(self):
        h = dict(AUTH, Origin="https://evil.example")
        self.assertEqual(SRV.req("/admin/opportunities/1/flag", b"", h)[0], 403)

    def test_verify_and_add_opportunity(self):
        SRV.req("/admin/opportunities/add", {"title": "Hotel cooks for Paphos resort (employer direct)", "source": "Employer email", "tier": "1"}, AUTH)
        o = db.q("SELECT * FROM opportunities WHERE title LIKE 'Hotel cooks for Paphos%'", one=True)
        self.assertEqual(o["sector"], "Hospitality")
        SRV.req("/admin/opportunities/%d/verify" % o["id"], b"", AUTH)
        self.assertEqual(db.q("SELECT status FROM opportunities WHERE id=?", (o["id"],), one=True)["status"], "verified")


class Compliance(unittest.TestCase):
    def test_dsar_export_and_erase(self):
        db.insert("profiles", token="tok-erase-test-0001", name="Zara", contact="+92 333 4445556", data="{}", created_at=db.now_iso(), consent_at=db.now_iso())
        db.insert("orders", ref="MUSA-B-0001-AAAA", product="verify_basic", name="Zara", contact="03334445556", details="x", amount_pkr=4500,
                  status="paid", created_at=db.now_iso())
        SRV.req("/privacy/request", {"contact": "0333 4445556", "kind": "erase"})
        d = db.q("SELECT * FROM dsar ORDER BY id DESC LIMIT 1", one=True)
        code, body, _ = SRV.req("/admin/compliance/dsar/%d/export" % d["id"], b"", AUTH)
        self.assertIn("tok-erase-test-0001", body)
        SRV.req("/admin/compliance/dsar/%d/erase" % d["id"], b"", AUTH)
        self.assertIsNone(db.q("SELECT * FROM profiles WHERE token='tok-erase-test-0001'", one=True))
        order = db.q("SELECT * FROM orders WHERE ref='MUSA-B-0001-AAAA'", one=True)
        self.assertEqual(order["contact"], "[erased]")  # kept for accounting, anonymised
        self.assertNotIn("4445556", db.q("SELECT contact FROM dsar WHERE id=?", (d["id"],), one=True)["contact"])

    def test_retention_deletes_old_profiles(self):
        db.insert("profiles", token="tok-old-profile-0001", name="Old", contact="", data="{}", created_at="2020-01-01T00:00:00+00:00")
        compliance.run_retention()
        self.assertIsNone(db.q("SELECT * FROM profiles WHERE token='tok-old-profile-0001'", one=True))


class Concierge(unittest.TestCase):
    def test_rules_answer_cites_source(self):
        r = agents.ask("Can a Pakistani get a work visa for Cyprus?")
        self.assertEqual(r["mode"], "rules")
        self.assertIn("[K2]", r["answer"])
        self.assertTrue(r["sources"])

    def test_unknown_question_refuses(self):
        r = agents.ask("What is the best pizza in Naples?")
        self.assertEqual(r["sources"], [])
        self.assertIn("don't have a sourced answer", r["answer"])

    def _fake(self, text, stop="end_turn"):
        calls = []

        class Msgs:
            def create(self, **kw):
                calls.append(kw)
                return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])
        return SimpleNamespace(beta=SimpleNamespace(messages=Msgs())), calls

    def test_ai_answer_with_citation(self):
        client, calls = self._fake("Yes, through a real employer whose permit is approved [K2].")
        r = agents.ask("can pakistani get cyprus work visa", client=client)
        self.assertEqual(r["mode"], "ai")
        self.assertEqual(calls[0]["model"], "claude-opus-5-5")
        self.assertEqual(calls[0]["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", calls[0]["betas"])

    def test_uncited_or_refused_ai_falls_back_to_rules(self):
        client, _ = self._fake("Sure, it costs 500 euro.")
        self.assertEqual(agents.ask("can pakistani get cyprus work visa", client=client)["mode"], "rules")
        client, _ = self._fake("", stop="refusal")
        self.assertEqual(agents.ask("can pakistani get cyprus work visa", client=client)["mode"], "rules")


class ScoutTests(unittest.TestCase):
    RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Jobs</title>
<item><title>Construction workers needed in Limassol - visa sponsorship</title><link>https://jobs.example/1</link><description>Masons and steel fixers, work permit provided.</description></item>
<item><title>Hotel receptionist, Paphos</title><link>https://jobs.example/2</link><description>English B2.</description></item>
</channel></rss>"""

    def test_parse_feed_and_atom(self):
        items = scout.parse_feed(self.RSS)
        self.assertEqual(len(items), 2)
        atom = '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Warehouse picker Larnaca</title><link href="https://x.example/a"/><summary>non-EU welcome</summary></entry></feed>'
        self.assertEqual(scout.parse_feed(atom)[0]["url"], "https://x.example/a")

    def test_classify(self):
        self.assertEqual(scout.classify("Steel fixer needed, work permit sponsorship, Cyprus"), ("Construction", True, "Cyprus"))

    def test_html_links(self):
        html = '<a href="/job/1">Construction labourer - Cyprus</a><a href="/about">About us</a><a href="/job/2">Hotel chef in Cyprus resort</a>'
        items = scout.parse_html_links(html, "https://b.example/list", must_contain=["cyprus"])
        self.assertEqual([i["url"] for i in items], ["https://b.example/job/1", "https://b.example/job/2"])

    def test_run_against_local_feed_respects_robots_and_dedupes(self):
        rss = self.RSS

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = {"/robots.txt": "User-agent: *\nDisallow: /private\n", "/feed.xml": rss}.get(self.path)
                self.send_response(200 if body else 404)
                self.end_headers()
                if body:
                    self.wfile.write(body.encode())

            def log_message(self, *a):
                pass
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % httpd.server_address[1]
        old_delay, scout.HOST_DELAY_S = scout.HOST_DELAY_S, 0
        try:
            src = {"id": "t", "name": "Test feed", "type": "rss", "url": base + "/feed.xml", "tier": 2, "enabled": True}
            r1 = scout.run_all([src])[0]
            self.assertEqual((r1["fetched"], r1["added"], r1["error"]), (2, 2, ""))
            self.assertEqual(scout.run_all([src])[0]["added"], 0)  # dedupe
            o = db.q("SELECT * FROM opportunities WHERE url=?", ("https://jobs.example/1",), one=True)
            self.assertEqual((o["sector"], o["visa_signal"], o["status"], o["source_tier"]), ("Construction", 1, "lead", 2))
            blocked = scout.run_all([dict(src, id="p", url=base + "/private/feed.xml")])[0]
            self.assertIn("robots.txt", blocked["error"])
            self.assertEqual(scout.run_all([dict(src, enabled=False)]), [])
        finally:
            scout.HOST_DELAY_S = old_delay
            httpd.shutdown()
            httpd.server_close()

    def test_expire_stale(self):
        db.insert("opportunities", hash="stale-test-hash", title="Old listing", status="lead", source="x", expires_at="2020-01-01T00:00:00+00:00")
        scout.expire_stale()
        self.assertEqual(db.q("SELECT status FROM opportunities WHERE hash='stale-test-hash'", one=True)["status"], "expired")


class RateLimit(unittest.TestCase):
    def test_post_rate_limit(self):
        st = web.State()
        self.assertTrue(all(st.rate_ok("1.2.3.4", now=1000) for _ in range(web.POST_LIMIT[0])))
        self.assertFalse(st.rate_ok("1.2.3.4", now=1001))
        self.assertTrue(st.rate_ok("1.2.3.4", now=1000 + web.POST_LIMIT[1] + 1))


if __name__ == "__main__":
    unittest.main()


class Growth(unittest.TestCase):
    def test_guides_and_sector_pages(self):
        code, body, _ = SRV.req("/guides")
        self.assertEqual(code, 200)
        for g in SRV.state.guides:
            code, body, _ = SRV.req("/guides/" + g["slug"])
            self.assertEqual(code, 200, g["slug"])
            self.assertIn('"@type": "FAQPage"', body)
            self.assertIn("Sources:", body)
        code, body, _ = SRV.req("/jobs/construction")
        self.assertEqual(code, 200)
        self.assertIn("Construction worker", body)
        self.assertEqual(SRV.req("/jobs/not-a-sector")[0], 404)

    def test_guides_only_cite_knowledge_base(self):
        ids = {k["id"] for k in SRV.state.knowledge}
        for g in SRV.state.guides:
            self.assertTrue(g["faq"], g["slug"])
            for q, a, srcs in g["faq"]:
                self.assertTrue(srcs, q)
                self.assertIn(a, [k["a"] for k in SRV.state.knowledge])
        self.assertTrue(ids)

    def test_robots_and_sitemap_follow_site_url(self):
        os.environ.pop("MUSA_SITE_URL", None)
        self.assertEqual(SRV.req("/sitemap.xml")[0], 404)
        self.assertIn("Disallow: /admin", SRV.req("/robots.txt")[1])
        os.environ["MUSA_SITE_URL"] = "https://musa.example.com"
        try:
            code, xml, h = SRV.req("/sitemap.xml")
            self.assertEqual(code, 200)
            self.assertIn("<loc>https://musa.example.com/guides/cyprus-visa-scams</loc>", xml)
            self.assertIn("Sitemap: https://musa.example.com/sitemap.xml", SRV.req("/robots.txt")[1])
            self.assertIn('rel="canonical" href="https://musa.example.com/check"', SRV.req("/check")[1])
        finally:
            os.environ.pop("MUSA_SITE_URL", None)

    def test_whatsapp_links_when_configured(self):
        self.assertNotIn("wa.me/", SRV.req("/")[1])
        os.environ["MUSA_WHATSAPP"] = "+357 94 031786"
        try:
            self.assertIn("https://wa.me/35794031786?text=", SRV.req("/")[1])
            self.assertIn("ask us on WhatsApp", SRV.req("/check", {"text": "visa 100% guarantee"})[1])
        finally:
            os.environ.pop("MUSA_WHATSAPP", None)


class Shortlists(unittest.TestCase):
    def test_employer_shortlist_loop(self):
        # two candidates, only one opts in to CV sharing
        SRV.req("/match", {"name": "Sharer Mason", "skills": "mason, shuttering", "years": "7", "languages": "en:A2", "consent": "on", "share_ok": "on"})
        SRV.req("/match", {"name": "Private Mason", "skills": "mason", "years": "9", "languages": "en:B1", "consent": "on"})
        SRV.req("/business/employers", {"company": "Paphos Builders", "sector": "Construction", "roles": "3 masons", "contact_name": "D",
                                        "email": "d@pb.cy", "headcount": "3", "consent": "on"})
        rid = db.q("SELECT id FROM employer_requests WHERE company='Paphos Builders'", one=True)["id"]
        code, page, _ = SRV.req("/admin/employers/%d" % rid, headers=AUTH)
        self.assertEqual(code, 200)
        self.assertIn("Sharer Mason", page)
        self.assertNotIn("Private Mason", page)  # never shown without consent
        tok = db.q("SELECT token FROM profiles WHERE name='Sharer Mason'", one=True)["token"]
        self.assertEqual(SRV.req("/admin/employers/%d/shortlist" % rid, {"profile": tok, "role": "Mason / block layer", "score": "95"}, AUTH)[0], 303)
        sl = db.q("SELECT * FROM shortlists WHERE request_id=?", (rid,), one=True)
        code, body, _ = SRV.req("/shortlist/" + sl["token"])
        self.assertEqual(code, 200)
        self.assertIn("Sharer Mason", body)
        self.assertIn('content="noindex"', body)
        self.assertNotIn("Private Mason", body)
        SRV.req("/admin/shortlists/%d/status" % sl["id"], {"status": "hired"}, AUTH)
        self.assertIn("Placement fees (1 hires)", SRV.req("/admin/revenue", headers=AUTH)[1])
        # candidate deletes their profile -> disappears from the employer link
        SRV.req("/cv/%s/delete" % tok, b"")
        self.assertEqual(SRV.req("/shortlist/" + sl["token"])[0], 404)

    def test_shortlist_requires_admin_and_valid_token(self):
        self.assertEqual(SRV.req("/admin/employers/1")[0], 401)
        self.assertEqual(SRV.req("/shortlist/" + "x" * 24)[0], 404)


class RomanUrdu(unittest.TestCase):
    def test_urdu_pages(self):
        code, body, _ = SRV.req("/ur")
        self.assertEqual(code, 200)
        self.assertIn('lang="ur-Latn"', body)
        self.assertIn("Agent ko paisa dene se pehle", body)
        code, body, _ = SRV.req("/ur/check", {"text": "Visa 100% guarantee hai, aaj hi mere account mein paisa bhejo"})
        self.assertEqual(code, 200)
        self.assertIn("Ruk jayein", body)
        self.assertIn("zaati", body)  # Urdu reply from the trap library
        self.assertIn('href="/check"', SRV.req("/ur/check")[1])


def _stripe_post(event):
    import hashlib, hmac, time as _t
    body = json.dumps(event).encode()
    ts = int(_t.time())
    sig = "t=%d,v1=%s" % (ts, hmac.new(b"whsec_test", ("%d." % ts).encode() + body, hashlib.sha256).hexdigest())
    return SRV.req("/stripe/webhook", body, {"Stripe-Signature": sig, "Content-Type": "application/json"})


def _checkout(ref, eid, sub=None):
    return {"id": eid, "type": "checkout.session.completed", "data": {"object": {
        "client_reference_id": ref, "payment_status": "paid", "amount_total": 9900, "currency": "eur", "subscription": sub}}}


class StripeRouting(unittest.TestCase):
    def test_web_order_card_payment(self):
        code, _, h = SRV.req("/report", {"name": "Card Payer", "contact": "c@x.pk", "details": "OEP 9", "consent": "on"})
        ref = h["Location"].rsplit("/", 1)[1]
        self.assertEqual(_stripe_post(_checkout(ref, "evt_order_1"))[0], 200)
        o = db.q("SELECT status, method FROM orders WHERE ref=?", (ref,), one=True)
        self.assertEqual((o["status"], o["method"]), ("paid", "card"))

    def test_partner_subscription_lifecycle(self):
        SRV.req("/business/partners", {"org_name": "Karachi Careers", "org_type": "oep", "country": "Pakistan", "contact_name": "K",
                                       "email": "k@kc.pk", "tier": "badge", "consent": "on"})
        pid = db.q("SELECT id FROM partners WHERE org_name='Karachi Careers'", one=True)["id"]
        SRV.req("/admin/partners/%d/approve" % pid, b"", AUTH)
        ref = db.q("SELECT billing_ref FROM partners WHERE id=?", (pid,), one=True)["billing_ref"]
        self.assertEqual(_stripe_post(_checkout(ref, "evt_sub_1", sub="sub_123"))[0], 200)
        self.assertEqual(SRV.req("/partners/karachi-careers")[0], 200)
        _stripe_post(_checkout(ref, "evt_sub_1", sub="sub_123"))  # duplicate delivery is ignored
        self.assertEqual(db.count("SELECT COUNT(*) FROM audit WHERE action='stripe.event' AND target='evt_sub_1'"), 1)
        _stripe_post({"id": "evt_end", "type": "customer.subscription.deleted", "data": {"object": {"id": "sub_123"}}})
        self.assertEqual(SRV.req("/partners/karachi-careers")[0], 404)

    def test_bad_signature(self):
        body = json.dumps(_checkout("x", "e")).encode()
        self.assertEqual(SRV.req("/stripe/webhook", body, {"Stripe-Signature": "t=1,v1=00"})[0], 400)
