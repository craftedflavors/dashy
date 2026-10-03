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

from musa_sentinel import whatsapp  # noqa: E402

EMPTY_PAYMENTS = {"products": {
    "verify_basic": {"name": "Verify-Before-You-Pay report", "pkr": 4500, "eur": 15, "delivery": "48h"},
    "verify_deep": {"name": "Deep due-diligence case file", "pkr": 22500, "eur": 79, "delivery": "5 working days"}},
    "methods": []}
SCAM = "Cyprus visa 100% guarantee. Pay today to my personal account, contract after payment."


def payload(text=None, msg_id="m1", wa_id="923001234567", mtype="text", forwarded=False):
    msg = {"from": wa_id, "id": msg_id, "type": mtype}
    if mtype == "text":
        msg["text"] = {"body": text}
    if forwarded:
        msg["context"] = {"forwarded": True}
    return {"object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": {"messages": [msg]}}]}]}


class BotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.leads = os.path.join(self.tmp.name, "leads.jsonl")
        self.sent = []
        self.bot = whatsapp.Bot(send=lambda to, text: self.sent.append((to, text)), leads_file=self.leads,
                                payments_config=EMPTY_PAYMENTS)

    def tearDown(self):
        self.tmp.cleanup()

    def leads_log(self):
        with open(self.leads, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_scam_message_gets_stop_reply_and_lead(self):
        out = self.bot.handle(payload(SCAM, forwarded=True))
        self.assertEqual(len(out), 1)
        self.assertIn("STOP", out[0]["text"])
        self.assertIn("REPORT", out[0]["text"])
        rec = self.leads_log()[0]
        self.assertEqual(rec["intent"], "scan")
        self.assertEqual(rec["colour"], "RED")
        self.assertTrue(rec["forwarded"])
        self.assertIn("TRAP-001", rec["traps"])

    def test_message_text_never_stored(self):
        self.bot.handle(payload(SCAM))
        with open(self.leads, encoding="utf-8") as f:
            self.assertNotIn("personal account", f.read())

    def test_clean_message_is_not_called_safe(self):
        out = self.bot.handle(payload("Please find the employment contract attached."))
        self.assertIn("does NOT mean the offer is genuine", out[0]["text"])

    def test_duplicate_delivery_ignored(self):
        self.bot.handle(payload(SCAM, msg_id="dup"))
        self.bot.handle(payload(SCAM, msg_id="dup"))
        self.assertEqual(len(self.sent), 1)

    def test_commands_and_language(self):
        self.bot.handle(payload("URDU", msg_id="a"))
        self.bot.handle(payload("price", msg_id="b"))
        self.bot.handle(payload("Report!", msg_id="c"))
        self.assertIn("Roman Urdu", self.sent[0][1])
        self.assertIn("muft", self.sent[1][1])
        self.assertIn("ki darkhwast mil gayi", self.sent[2][1])
        self.assertEqual([r["intent"] for r in self.leads_log()], ["price", "report_request"])

    def test_report_without_payment_methods_gives_reference(self):
        text = self.bot.handle(payload("REPORT"))[0]["text"]
        self.assertRegex(text, r"MUSA-B-4567-[0-9A-F]{4}")
        self.assertIn("payment details shortly", text)

    def test_media_gets_text_request(self):
        out = self.bot.handle(payload(mtype="image"))
        self.assertIn("only check text", out[0]["text"])

    def test_opt_out_is_respected_and_survives_restart(self):
        self.bot.handle(payload("STOP", msg_id="s"))
        self.bot.handle(payload(SCAM, msg_id="t"))
        self.assertEqual(len(self.sent), 1)  # only the opt-out confirmation
        restarted = whatsapp.Bot(send=lambda *a: self.sent.append(a), leads_file=self.leads)
        self.assertEqual(restarted.handle(payload(SCAM, msg_id="u")), [])
        self.assertTrue(restarted.handle(payload("help", msg_id="v")))  # HELP opts back in
        self.assertTrue(restarted.handle(payload(SCAM, msg_id="w")))

    def test_rate_limit(self):
        limit = whatsapp.RATE_LIMIT[0]
        for i in range(limit + 1):
            self.bot.handle(payload(SCAM, msg_id="r%d" % i))
        self.assertIn("many checks", self.sent[-1][1])

    def test_too_long(self):
        out = self.bot.handle(payload("x" * (whatsapp.MAX_INBOUND_CHARS + 1)))
        self.assertIn("too long", out[0]["text"])

    def test_status_updates_ignored(self):
        p = {"entry": [{"changes": [{"value": {"statuses": [{"id": "x", "status": "delivered"}]}}]}]}
        self.assertEqual(self.bot.handle(p), [])


class SignatureTests(unittest.TestCase):
    def test_signature(self):
        body = b'{"a":1}'
        sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        self.assertTrue(whatsapp.verify_signature("secret", body, sig))
        self.assertFalse(whatsapp.verify_signature("secret", body + b" ", sig))
        self.assertFalse(whatsapp.verify_signature("secret", body, None))
        self.assertFalse(whatsapp.verify_signature("", body, sig))


class ServerTests(unittest.TestCase):
    """Real HTTP round-trip against the webhook handler on an ephemeral port."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sent = []
        self.bot = whatsapp.Bot(send=lambda to, text: self.sent.append((to, text)),
                                leads_file=os.path.join(self.tmp.name, "leads.jsonl"))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), whatsapp.make_handler(self.bot, "vtok", "asecret"))
        self.base = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, ""

    def post(self, body, secret="asecret"):
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        req = urllib.request.Request(self.base + "/webhook", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_verification_handshake(self):
        self.assertEqual(self.get("/webhook?hub.mode=subscribe&hub.verify_token=vtok&hub.challenge=123"), (200, "123"))
        self.assertEqual(self.get("/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=123")[0], 403)
        self.assertEqual(self.get("/health"), (200, "ok"))

    def test_signed_post_is_processed(self):
        self.assertEqual(self.post(json.dumps(payload(SCAM)).encode()), 200)
        for _ in range(50):
            if self.sent:
                break
            time.sleep(0.02)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("STOP", self.sent[0][1])

    def test_bad_signature_rejected(self):
        self.assertEqual(self.post(json.dumps(payload(SCAM)).encode(), secret="nope"), 401)
        time.sleep(0.1)
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
