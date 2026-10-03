import hashlib
import hmac
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from musa_sentinel import leadlog, payments, whatsapp  # noqa: E402

CFG = {
    "products": {
        "verify_basic": {"name": "Verify-Before-You-Pay report", "pkr": 4500, "eur": 15, "delivery": "48h"},
        "verify_deep": {"name": "Deep due-diligence case file", "pkr": 22500, "eur": 79, "delivery": "5 working days"},
    },
    "methods": [
        {"id": "card", "type": "link", "label": "Card", "urls": {"verify_basic": "https://buy.stripe.com/test_abc?locale=en", "verify_deep": ""},
         "reference_param": "client_reference_id"},
        {"id": "jazzcash", "type": "wallet", "label": "JazzCash merchant", "account_title": "MUSA Consulting (Pvt) Ltd", "account": "0300-0000000"},
        {"id": "easypaisa", "type": "wallet", "label": "Easypaisa merchant", "account_title": "", "account": "0345-0000000"},
        {"id": "bank", "type": "bank", "label": "Bank / Raast", "account_title": "MUSA Consulting (Pvt) Ltd", "bank": "Meezan", "iban": "PK00MEZN0000000000000000", "raast_id": ""},
    ],
}
WA = "923001234567"


def msg(text, mid):
    return {"entry": [{"changes": [{"value": {"messages": [{"from": WA, "id": mid, "type": "text", "text": {"body": text}}]}}]}]}


def stripe_sig(secret, body, ts=None):
    ts = ts or int(time.time())
    return "t=%d,v1=%s" % (ts, hmac.new(secret.encode(), ("%d." % ts).encode() + body, hashlib.sha256).hexdigest())


def checkout_event(ref, eid="evt_1", status="paid"):
    return {"id": eid, "type": "checkout.session.completed",
            "data": {"object": {"client_reference_id": ref, "payment_status": status, "amount_total": 1500, "currency": "eur"}}}


class PaymentConfigTests(unittest.TestCase):
    def test_reference_format(self):
        ref = payments.new_reference(WA, "verify_deep")
        self.assertRegex(ref, r"^MUSA-D-4567-[0-9A-F]{4}$")
        self.assertTrue(whatsapp.REF_RE.fullmatch(ref))

    def test_only_complete_methods_are_offered(self):
        ids = [m["id"] for m in payments.active_methods(CFG, "verify_basic")]
        self.assertEqual(ids, ["card", "jazzcash", "bank"])  # easypaisa has no account title
        self.assertEqual([m["id"] for m in payments.active_methods(CFG, "verify_deep")], ["jazzcash", "bank"])

    def test_instructions_carry_reference_into_card_link(self):
        text = payments.instructions(CFG, "verify_basic", "MUSA-B-4567-ABCD")
        self.assertIn("https://buy.stripe.com/test_abc?locale=en&client_reference_id=MUSA-B-4567-ABCD", text)
        self.assertIn("MUSA Consulting (Pvt) Ltd", text)
        self.assertIn("PAID MUSA-B-4567-ABCD", text)
        self.assertIn("do not pay", text)

    def test_shipped_config_is_empty_and_warns(self):
        cfg = payments.load_config()
        self.assertEqual(payments.active_methods(cfg, "verify_basic"), [])
        self.assertEqual(len(payments.config_warnings(cfg)), 2)

    def test_stripe_signature(self):
        body = b'{"id":"evt"}'
        self.assertTrue(payments.verify_stripe_signature("whsec", body, stripe_sig("whsec", body)))
        self.assertFalse(payments.verify_stripe_signature("whsec", body + b" ", stripe_sig("whsec", body)))
        old = int(time.time()) - 3600
        self.assertFalse(payments.verify_stripe_signature("whsec", body, stripe_sig("whsec", body, old)))
        self.assertFalse(payments.verify_stripe_signature("whsec", body, "garbage"))

    def test_parse_event_only_paid(self):
        self.assertEqual(payments.parse_stripe_event(checkout_event("R"))["amount"], 15)
        self.assertIsNone(payments.parse_stripe_event(checkout_event("R", status="unpaid")))
        self.assertIsNone(payments.parse_stripe_event({"type": "invoice.paid"}))


class BotPaymentFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.leads = os.path.join(self.tmp.name, "leads.jsonl")
        self.sent = []
        self.bot = whatsapp.Bot(send=lambda to, text: self.sent.append((to, text)), leads_file=self.leads, payments_config=CFG)

    def tearDown(self):
        self.tmp.cleanup()

    def ref(self):
        return next(r["reference"] for r in leadlog.load(self.leads) if r["intent"] == "report_request")

    def status(self):
        s = leadlog.summarise(leadlog.load(self.leads))
        return next((p["status"] for p in s["queue"]), "none"), s

    def test_report_reply_has_payment_options(self):
        text = self.bot.handle(msg("REPORT", "1"))[0]["text"]
        self.assertIn("client_reference_id=" + self.ref(), text)
        self.assertIn("JazzCash", text)

    def test_deep_uses_deep_product(self):
        text = self.bot.handle(msg("deep", "1"))[0]["text"]
        self.assertIn("Deep due-diligence", text)
        self.assertIn("22,500", text)
        self.assertNotIn("buy.stripe.com", text)  # no deep card link configured

    def test_full_lifecycle(self):
        self.bot.handle(msg("REPORT", "1"))
        ref = self.ref()
        self.assertEqual(self.status()[0], "hot")
        self.bot.handle(msg("paid " + ref.lower(), "2"))
        self.assertEqual(self.status()[0], "claimed")
        self.assertEqual(self.bot.confirm_payment(ref, "jazzcash", confirmed_by="admin"), WA)
        st, s = self.status()
        self.assertEqual(st, "paid")
        self.assertEqual(s["revenue_7d"], {"PKR": 4500})
        self.assertIn("Payment received", self.sent[-1][1])
        leadlog.mark(WA, "delivered", self.leads)
        self.assertEqual(self.status()[0], "none")

    def test_paid_claim_without_reference(self):
        self.assertIn("followed by your reference", self.bot.handle(msg("PAID", "1"))[0]["text"])

    def test_claim_is_not_proof(self):
        self.bot.handle(msg("REPORT", "1"))
        self.bot.handle(msg("PAID " + self.ref(), "2"))
        self.assertEqual(self.status()[1]["paid_7d"], 0)

    def test_confirm_unknown_or_duplicate(self):
        self.assertIsNone(self.bot.confirm_payment("MUSA-B-0000-0000", "card"))
        self.bot.handle(msg("REPORT", "1"))
        ref = self.ref()
        self.assertEqual(self.bot.confirm_payment(ref, "card", 15.0, "EUR", "evt_1"), WA)
        self.assertIn("EUR 15)", self.sent[-1][1])
        self.assertIsNone(self.bot.confirm_payment(ref, "card", 15.0, "EUR", "evt_1"))
        self.assertIsNone(self.bot.confirm_payment(ref, "bank"))

    def test_new_request_after_delivery_is_a_new_order(self):
        self.bot.handle(msg("REPORT", "1"))
        self.bot.confirm_payment(self.ref(), "bank")
        leadlog.mark(WA, "delivered", self.leads)
        self.bot.handle(msg("REPORT", "2"))
        self.assertEqual(self.status()[0], "hot")


class StripeAndAdminServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.leads = os.path.join(self.tmp.name, "leads.jsonl")
        self.sent = []
        self.bot = whatsapp.Bot(send=lambda to, text: self.sent.append((to, text)), leads_file=self.leads, payments_config=CFG)
        self.bot.handle(msg("REPORT", "1"))
        self.ref = next(r["reference"] for r in leadlog.load(self.leads) if r["intent"] == "report_request")
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), whatsapp.make_handler(self.bot, "v", "s", "pw", "whsec"))
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def post(self, path, body, headers):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        r = urllib.request.Request(self.base + path, data=body, method="POST", headers=headers)
        try:
            with urllib.request.build_opener(NoRedirect).open(r) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code

    def paid(self):
        return [r for r in leadlog.load(self.leads) if r["intent"] == "paid"]

    def test_stripe_webhook_confirms_once(self):
        body = json.dumps(checkout_event(self.ref)).encode()
        self.assertEqual(self.post("/stripe/webhook", body, {"Stripe-Signature": stripe_sig("whsec", body)}), 200)
        self.assertEqual(self.post("/stripe/webhook", body, {"Stripe-Signature": stripe_sig("whsec", body)}), 200)
        self.assertEqual(len(self.paid()), 1)
        self.assertEqual(self.paid()[0]["method"], "card")

    def test_stripe_bad_signature(self):
        body = json.dumps(checkout_event(self.ref)).encode()
        self.assertEqual(self.post("/stripe/webhook", body, {"Stripe-Signature": stripe_sig("nope", body)}), 400)
        self.assertEqual(self.paid(), [])

    def test_admin_mark_paid(self):
        auth = {"Authorization": "Basic " + __import__("base64").b64encode(b"admin:pw").decode(),
                "Content-Type": "application/x-www-form-urlencoded"}
        body = ("reference=%s&method=easypaisa" % self.ref).encode()
        self.assertEqual(self.post("/admin/leads/%s/paid" % WA, body, auth), 303)
        self.assertEqual(self.paid()[0]["method"], "easypaisa")
        self.assertEqual(self.paid()[0]["confirmed_by"], "admin")
        self.assertEqual(self.post("/admin/leads/%s/paid" % WA, b"reference=bogus", auth), 400)
        self.assertEqual(self.post("/admin/leads/%s/delivered" % WA, b"", auth), 303)


if __name__ == "__main__":
    unittest.main()
