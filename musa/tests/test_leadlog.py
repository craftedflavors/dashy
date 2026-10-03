import base64
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import yaml  # optional: only used to prove the generated page parses
except ImportError:  # pragma: no cover
    yaml = None

from musa_sentinel import leadlog, whatsapp  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples", "leads.jsonl")
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.s = leadlog.summarise(leadlog.load(SAMPLE), now=NOW)
        self.by_id = {p["wa_id"]: p for p in self.s["queue"]}

    def test_statuses(self):
        self.assertEqual(self.s["hot"], 2)            # 0101 and 0606 requested reports
        self.assertEqual(self.s["warm"], 1)           # 0202 asked for prices
        self.assertEqual(self.s["done"], 1)           # 0404 followed up after requesting
        self.assertEqual(self.s["opted_out"], 1)      # 0505
        self.assertEqual(self.s["people"], 6)

    def test_queue_order_hot_first_oldest_first(self):
        self.assertEqual([p["wa_id"][-4:] for p in self.s["queue"]], ["0101", "0606", "0202"])

    def test_opted_out_and_done_not_in_queue(self):
        ids = {p["wa_id"][-4:] for p in self.s["queue"]}
        self.assertFalse(ids & {"0404", "0505"})

    def test_stats(self):
        self.assertEqual(self.s["scans_7d"], 6)
        self.assertEqual(self.s["conversion_pct"], 50)
        self.assertEqual(self.s["top_traps_7d"][0], ("TRAP-001", 3))

    def test_new_request_after_follow_up_reopens(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "l.jsonl")
            with open(SAMPLE, encoding="utf-8") as src, open(p, "w", encoding="utf-8") as dst:
                dst.write(src.read())
                dst.write('{"at": "2026-10-03T11:30:00+00:00", "wa_id": "923000000404", "intent": "report_request"}\n')
            s = leadlog.summarise(leadlog.load(p), now=NOW)
            self.assertEqual(s["hot"], 3)

    def test_missing_and_corrupt_log(self):
        self.assertEqual(leadlog.load("/nonexistent/leads.jsonl"), [])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "l.jsonl")
            with open(p, "w") as f:
                f.write("not json\n{\"wa_id\": \"1\"}\n")
            self.assertEqual(leadlog.load(p), [])


class PageTests(unittest.TestCase):
    def test_public_page_never_contains_full_numbers(self):
        records = leadlog.load(SAMPLE)
        page = leadlog.dashy_page(leadlog.summarise(records, now=NOW), "https://bot/admin/leads", now=NOW)
        for r in records:
            self.assertNotIn(r["wa_id"], page)
        self.assertIn("•••0101", page)
        if yaml is None:
            self.skipTest("PyYAML not installed")
        doc = yaml.safe_load(page)
        self.assertEqual(doc["pageInfo"]["title"], "MUSA Leads")
        self.assertEqual(len(doc["sections"]), 3)

    def test_empty_page_is_valid(self):
        if yaml is None:
            self.skipTest("PyYAML not installed")
        doc = yaml.safe_load(leadlog.dashy_page(leadlog.summarise([], now=NOW), now=NOW))
        self.assertEqual(doc["sections"][1]["items"][0]["title"], "Queue is empty")

    def test_admin_html_escapes_and_links(self):
        html = leadlog.admin_html(leadlog.summarise(leadlog.load(SAMPLE), now=NOW), now=NOW)
        self.assertIn("https://wa.me/923000000101?text=", html)
        self.assertNotIn("923000000505", html)  # opted out
        self.assertIn('name="robots" content="noindex"', html)


class AdminServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.leads = os.path.join(self.tmp.name, "leads.jsonl")
        with open(SAMPLE, encoding="utf-8") as src, open(self.leads, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        bot = whatsapp.Bot(send=lambda *a: None, leads_file=self.leads)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), whatsapp.make_handler(bot, "v", "s", admin_password="pässword"))
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def req(self, path, method="GET", auth=None, headers=None):
        h = dict(headers or {})
        if auth:
            h["Authorization"] = "Basic " + base64.b64encode(auth.encode()).decode()
        r = urllib.request.Request(self.base + path, method=method, headers=h, data=b"" if method == "POST" else None)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(r) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, ""

    def test_requires_auth(self):
        self.assertEqual(self.req("/admin/leads")[0], 401)
        self.assertEqual(self.req("/admin/leads", auth="admin:wrong")[0], 401)
        self.assertEqual(self.req("/admin/leads", auth="root:pässword")[0], 401)

    def test_admin_view_and_mark_done(self):
        code, body = self.req("/admin/leads", auth="admin:pässword")
        self.assertEqual(code, 200)
        self.assertIn("+923000000101", body)
        self.assertEqual(self.req("/admin/leads/923000000101/done", "POST", auth="admin:pässword")[0], 303)
        self.assertEqual(leadlog.summarise(leadlog.load(self.leads), now=NOW)["hot"], 1)

    def test_cross_site_post_blocked(self):
        code, _ = self.req("/admin/leads/923000000101/done", "POST", auth="admin:pässword",
                           headers={"Origin": "https://evil.example"})
        self.assertEqual(code, 403)

    def test_admin_disabled_without_password(self):
        bot = whatsapp.Bot(send=lambda *a: None, leads_file=self.leads)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), whatsapp.make_handler(bot, "v", "s"))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen("http://127.0.0.1:%d/admin/leads" % httpd.server_address[1])
            self.assertEqual(cm.exception.code, 404)
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
