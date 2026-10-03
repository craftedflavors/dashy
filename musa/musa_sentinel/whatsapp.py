"""WhatsApp Scam Shield bot — Meta WhatsApp Cloud API webhook, standard library only.

Flow: worker forwards/pastes a recruiter message → bot scans it with the trap library →
replies with STOP/HOLD + flags → offers the paid Verify-Before-You-Pay report → logs a lead.

Environment:
  WA_VERIFY_TOKEN       any secret string; paste the same value into the Meta webhook settings
  WA_APP_SECRET         Meta app secret — used to check X-Hub-Signature-256 on every POST
  WA_TOKEN              permanent system-user access token
  WA_PHONE_NUMBER_ID    WhatsApp Business phone-number ID (not the phone number)
  WA_GRAPH_VERSION      Graph API version, default v23.0 — keep in step with your Meta app
  MUSA_LEADS_FILE       JSONL lead log, default musa/data/leads.jsonl
  MUSA_REPORT_PRICE_PKR price quoted for the report, default 4500
  MUSA_PAYMENT_LINK     optional payment link (JazzCash / Stripe) appended to REPORT replies
  MUSA_ADMIN_PASSWORD   enables the private /admin/leads follow-up view (HTTP Basic auth, user "admin")
  PORT                  listen port, default 8088

Privacy: message text is never written to disk. The lead log keeps the sender's WhatsApp ID
(needed to deliver the report), timestamps, the trap IDs found and the intent.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.request
from collections import OrderedDict, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import DATA_DIR, leadlog
from .traps import assess_message, load_traps

MAX_INBOUND_CHARS = 4000      # ignore anything longer — WhatsApp text caps at 4096 anyway
MAX_REPLY_CHARS = 4000
RATE_LIMIT = (10, 3600)       # at most 10 scans per sender per hour

COMMANDS = {
    "report": "report", "verify": "report", "rpt": "report",
    "price": "price", "prices": "price", "fee": "price", "qeemat": "price",
    "help": "help", "menu": "help", "hi": "help", "hello": "help", "salam": "help",
    "assalam o alaikum": "help", "assalamualaikum": "help", "aoa": "help", "start": "help",
    "urdu": "lang_ur", "english": "lang_en",
    "stop": "stop", "unsubscribe": "stop",
}

TEXT = {
    "en": {
        "help": ("*MUSA Scam Shield* 🛡️\n\nForward or paste the agent's message, ad or offer letter here. "
                 "I'll check it for known scam warning signs in seconds.\n\n"
                 "Commands: *PRICE* · *REPORT* · *URDU*\n\n"
                 "_I flag warning signs; I can't prove an offer is genuine. Only official records can._"),
        "price": ("*Services*\n• Scam check — free (this chat)\n• Verify-Before-You-Pay report — Rs {price}\n"
                  "  OEP licence + BEOE permission + employer registry + fee breakdown, 48h\n"
                  "• Deep due-diligence file — Rs {deep}\n\nWe never charge workers a placement fee.\nReply *REPORT* to start."),
        "report": ("✅ Report request received.\n\nPlease send:\n1. Agent / company name\n2. OEP licence number (if given)\n"
                   "3. BEOE permission number (if given)\n4. Amount they asked for\n\nWe'll confirm the fee (Rs {price}) and start within 24h.{pay}"),
        "stop": "You won't receive further messages. Send *HELP* any time to use Scam Shield again.",
        "lang": "Language set to English.",
        "media": "I can only check text. Please paste or forward the agent's message as text (not a photo or voice note).",
        "too_long": "That message is too long. Please send the main part of the offer (under 4,000 characters).",
        "rate": "You've sent many checks in the last hour. Please try again later, or reply *REPORT* for a full manual check.",
        "red": "🛑 *STOP — do not pay*",
        "amber_flags": "⚠️ *HOLD — verify before paying*",
        "clean": "ℹ️ *No known scam pattern found*",
        "clean_note": "That does NOT mean the offer is genuine — nothing has been verified yet. Still check the OEP licence, BEOE permission and a written contract.",
        "risk": "Risk {score}/100 ({band}) · {n} warning sign(s)",
        "upsell": "Want it checked against official records before you pay? Reply *REPORT* (Rs {price}).",
    },
    "ur": {
        "help": ("*MUSA Scam Shield* 🛡️\n\nAgent ka message, ad ya offer letter yahan forward ya paste karein. "
                 "Hum foran dhoke ke nishan check karenge.\n\nCommands: *PRICE* · *REPORT* · *ENGLISH*\n\n"
                 "_Hum warning signs batate hain; offer asli hai ya nahi yeh sirf official records se pata chalta hai._"),
        "price": ("*Services*\n• Scam check — muft (yehi chat)\n• Verify-Before-You-Pay report — Rs {price}\n"
                  "  OEP licence + BEOE permission + employer registry + kharchon ki tafseel, 48 ghante\n"
                  "• Mukammal due-diligence file — Rs {deep}\n\nHum worker se placement fee nahi lete.\nShuru karne ke liye *REPORT* likhein."),
        "report": ("✅ Report ki darkhwast mil gayi.\n\nYeh bhejein:\n1. Agent / company ka naam\n2. OEP licence number (agar diya ho)\n"
                   "3. BEOE permission number (agar diya ho)\n4. Kitne paise mange gaye\n\nHum fee (Rs {price}) confirm karke 24 ghante mein shuru karenge.{pay}"),
        "stop": "Ab aap ko mazeed message nahi aayenge. Dobara istemal ke liye *HELP* likhein.",
        "lang": "Zuban Roman Urdu kar di gayi.",
        "media": "Hum sirf text check kar sakte hain. Agent ka message text ki shakal mein bhejein (photo ya voice note nahi).",
        "too_long": "Message bohat lamba hai. Offer ka asal hissa bhejein (4,000 huroof se kam).",
        "rate": "Aap ne pichle ghante mein bohat checks bheje hain. Baad mein koshish karein, ya mukammal check ke liye *REPORT* likhein.",
        "red": "🛑 *RUK JAYEIN — payment na karein*",
        "amber_flags": "⚠️ *HOLD — pehle verify karein*",
        "clean": "ℹ️ *Koi ma'loom dhoka pattern nahi mila*",
        "clean_note": "Is ka matlab yeh nahi ke offer asli hai — abhi kuch verify nahi hua. OEP licence, BEOE permission aur likha hua contract zaroor check karein.",
        "risk": "Risk {score}/100 ({band}) · {n} warning signs",
        "upsell": "Payment se pehle official records se check karwana hai? *REPORT* likhein (Rs {price}).",
    },
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def verify_signature(app_secret, body, header):
    """Constant-time check of Meta's X-Hub-Signature-256 header ('sha256=<hex>')."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):])


def format_scan_reply(result, lang, price_pkr):
    t = TEXT[lang]
    hits, d = result["hits"], result["decision"]
    if not hits:
        lines = [t["clean"], "", t["clean_note"]]
    else:
        head = t["red"] if d["colour"] == "RED" else t["amber_flags"]
        lines = [head, t["risk"].format(score=d["risk"]["score"], band=d["risk"]["band"], n=len(hits)), ""]
        for h in hits[:6]:
            reply = h["response_ur"] if lang == "ur" and h.get("response_ur") else h["response"]
            lines.append("• *%s* — %s" % (h["name"], reply))
        if len(hits) > 6:
            lines.append("• +%d more" % (len(hits) - 6))
    lines += ["", t["upsell"].format(price=price_pkr)]
    return "\n".join(lines)[:MAX_REPLY_CHARS]


class Bot:
    """Transport-agnostic bot logic. `handle(payload)` returns the outbound messages it sent."""

    def __init__(self, send=None, leads_file=None, price_pkr=None, payment_link=None, traps=None):
        self.send = send or (lambda to, text: None)
        self.leads_file = leads_file or os.environ.get("MUSA_LEADS_FILE") or os.path.join(DATA_DIR, "leads.jsonl")
        self.price_pkr = int(price_pkr or os.environ.get("MUSA_REPORT_PRICE_PKR", 4500))
        self.payment_link = payment_link if payment_link is not None else os.environ.get("MUSA_PAYMENT_LINK", "")
        self.traps = traps if traps is not None else load_traps()
        self.lang = {}                       # wa_id -> "en" | "ur"
        self.opted_out = set()
        self.seen = OrderedDict()            # message-id dedupe (Meta retries deliveries)
        self.hits = {}                       # wa_id -> deque of scan timestamps
        self._lock = threading.Lock()
        self._restore_opt_outs()

    def _restore_opt_outs(self):
        """Opt-outs must survive restarts: replay opt_out / opt_in events from the lead log."""
        try:
            with open(self.leads_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if rec.get("intent") == "opt_out":
                        self.opted_out.add(rec.get("wa_id"))
                    elif rec.get("intent") == "opt_in":
                        self.opted_out.discard(rec.get("wa_id"))
        except OSError:
            pass

    # ---- helpers ----
    def _dup(self, msg_id):
        with self._lock:
            if msg_id in self.seen:
                return True
            self.seen[msg_id] = True
            while len(self.seen) > 5000:
                self.seen.popitem(last=False)
            return False

    def _rate_limited(self, wa_id, now=None):
        now = now or time.time()
        limit, window = RATE_LIMIT
        with self._lock:
            q = self.hits.setdefault(wa_id, deque())
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return True
            q.append(now)
            return False

    def _log(self, wa_id, intent, **extra):
        rec = {"at": _now(), "wa_id": wa_id, "intent": intent, "lang": self.lang.get(wa_id, "en")}
        rec.update(extra)
        with self._lock:
            os.makedirs(os.path.dirname(os.path.abspath(self.leads_file)), exist_ok=True)
            with open(self.leads_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _reply(self, out, to, text):
        out.append({"to": to, "text": text})
        self.send(to, text)

    # ---- main entry ----
    def handle(self, payload):
        out = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []) or []:
                    if not msg.get("id") or self._dup(msg["id"]):
                        continue
                    self._handle_message(msg, out)
        return out

    def _handle_message(self, msg, out):
        wa_id = msg.get("from")
        if not wa_id:
            return
        lang = self.lang.get(wa_id, "en")
        t = TEXT[lang]

        if msg.get("type") != "text":
            if wa_id not in self.opted_out:
                self._reply(out, wa_id, t["media"])
            return

        body = (msg.get("text") or {}).get("body", "").strip()
        cmd = COMMANDS.get(body.lower().strip(" .!?*"))

        if cmd == "stop":
            self.opted_out.add(wa_id)
            self._log(wa_id, "opt_out")
            self._reply(out, wa_id, t["stop"])
            return
        if wa_id in self.opted_out:
            if cmd != "help":
                return
            self.opted_out.discard(wa_id)
            self._log(wa_id, "opt_in")
        if cmd in ("lang_ur", "lang_en"):
            self.lang[wa_id] = "ur" if cmd == "lang_ur" else "en"
            self._reply(out, wa_id, TEXT[self.lang[wa_id]]["lang"])
            return
        if cmd == "help":
            self._reply(out, wa_id, t["help"])
            return
        if cmd == "price":
            self._log(wa_id, "price")
            self._reply(out, wa_id, t["price"].format(price=self.price_pkr, deep=self.price_pkr * 5))
            return
        if cmd == "report":
            self._log(wa_id, "report_request")
            pay = ("\n\nPay: " + self.payment_link) if self.payment_link else ""
            self._reply(out, wa_id, t["report"].format(price=self.price_pkr, pay=pay))
            return

        if len(body) > MAX_INBOUND_CHARS:
            self._reply(out, wa_id, t["too_long"])
            return
        if self._rate_limited(wa_id):
            self._reply(out, wa_id, t["rate"])
            return
        result = assess_message(body, self.traps)
        self._log(wa_id, "scan", forwarded=bool((msg.get("context") or {}).get("forwarded")),
                  colour=result["decision"]["colour"], score=result["decision"]["risk"]["score"],
                  traps=[h["id"] for h in result["hits"]])
        self._reply(out, wa_id, format_scan_reply(result, lang, self.price_pkr))


# ---------------- Cloud API transport ----------------

def cloud_api_sender(token=None, phone_number_id=None, version=None, timeout=10):
    token = token or os.environ.get("WA_TOKEN")
    phone_number_id = phone_number_id or os.environ.get("WA_PHONE_NUMBER_ID")
    version = version or os.environ.get("WA_GRAPH_VERSION", "v23.0")
    if not (token and phone_number_id):
        raise RuntimeError("Set WA_TOKEN and WA_PHONE_NUMBER_ID")
    url = "https://graph.facebook.com/%s/%s/messages" % (version, phone_number_id)

    def send(to, text):
        data = json.dumps({"messaging_product": "whatsapp", "recipient_type": "individual", "to": to,
                           "type": "text", "text": {"preview_url": False, "body": text}}).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                r.read()
        except Exception as e:  # never let a send failure crash the webhook
            print("[whatsapp] send to %s failed: %s" % (to[-4:], e), flush=True)

    return send


def check_basic_auth(header, password):
    """True if the Authorization header carries admin:<password>. Disabled when no password is set."""
    if not password or not header or not header.startswith("Basic "):
        return False
    try:
        user, _, given = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(user.encode(), b"admin") & hmac.compare_digest(given.encode(), password.encode())


def make_handler(bot, verify_token, app_secret, admin_password=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MUSA-WhatsApp/1.0"

        def _admin_ok(self):
            if not admin_password:
                self._send(404)
                return False
            if not check_basic_auth(self.headers.get("Authorization"), admin_password):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="MUSA admin", charset="UTF-8"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return False
            return True

        def _send(self, code, body=b"", ctype="text/plain"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/health":
                return self._send(200, b"ok")
            if u.path == "/admin/leads":
                if not self._admin_ok():
                    return
                page = leadlog.admin_html(leadlog.summarise(leadlog.load(bot.leads_file)), price_pkr=bot.price_pkr)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Frame-Options", "DENY")
                body = page.encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                return self.wfile.write(body)
            if u.path != "/webhook":
                return self._send(404)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if q.get("hub.mode") == "subscribe" and verify_token and hmac.compare_digest(q.get("hub.verify_token", ""), verify_token):
                return self._send(200, q.get("hub.challenge", "").encode())
            return self._send(403)

        def do_POST(self):
            path = urlparse(self.path).path
            m = re.fullmatch(r"/admin/leads/(\d{6,20})/done", path)
            if m:
                if not self._admin_ok():
                    return
                origin = self.headers.get("Origin")
                if origin and urlparse(origin).netloc != self.headers.get("Host"):
                    return self._send(403)  # cross-site form post
                leadlog.mark_followed_up(m.group(1), bot.leads_file)
                self.send_response(303)
                self.send_header("Location", "/admin/leads")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path != "/webhook":
                return self._send(404)
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1_000_000:
                return self._send(413)
            body = self.rfile.read(length)
            if not verify_signature(app_secret, body, self.headers.get("X-Hub-Signature-256")):
                return self._send(401)
            try:
                payload = json.loads(body or b"{}")
            except ValueError:
                return self._send(400)
            # Acknowledge immediately; Meta retries if it doesn't get a fast 200.
            self._send(200, b"EVENT_RECEIVED")
            threading.Thread(target=bot.handle, args=(payload,), daemon=True).start()

        def log_message(self, fmt, *args):  # keep phone numbers out of access logs
            print("[whatsapp] %s %s" % (self.command, urlparse(self.path).path), flush=True)

    return Handler


def serve(port=None):
    verify_token = os.environ.get("WA_VERIFY_TOKEN")
    app_secret = os.environ.get("WA_APP_SECRET")
    if not (verify_token and app_secret):
        raise RuntimeError("Set WA_VERIFY_TOKEN and WA_APP_SECRET")
    bot = Bot(send=cloud_api_sender())
    port = int(port or os.environ.get("PORT", 8088))
    admin_password = os.environ.get("MUSA_ADMIN_PASSWORD")
    httpd = ThreadingHTTPServer(("0.0.0.0", port), make_handler(bot, verify_token, app_secret, admin_password))
    print("[whatsapp] MUSA Scam Shield bot listening on :%d  (webhook /webhook%s)"
          % (port, ", admin /admin/leads" if admin_password else ", admin disabled"), flush=True)
    httpd.serve_forever()


def simulate(text, lang="en"):
    """Offline: print what the bot would reply, without Meta credentials."""
    bot = Bot(leads_file=os.devnull)
    bot.lang["sim"] = lang
    msg = {"from": "sim", "id": "sim-%f" % time.time(), "type": "text", "text": {"body": text}}
    return [m["text"] for m in bot.handle({"entry": [{"changes": [{"value": {"messages": [msg]}}]}]})]
