"""Scout agent — keeps the opportunity board fresh.

Fetches configured public sources (RSS/Atom, JSON Feed, or an HTML page's job links), honours
robots.txt and a per-host delay, classifies sector + visa signals, de-duplicates by content hash,
and expires stale items. Nothing Scout finds is ever marked "verified": that takes a human.
"""
import hashlib
import json
import os
import re
import time
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from . import DATA_DIR, db

USER_AGENT = "MUSA-Scout/1.0 (+opportunity indexing; contact via site) Python-urllib"
FETCH_TIMEOUT = 15
HOST_DELAY_S = 2.0
FRESH_DAYS = 45

SECTORS = {
    "Construction": ["construction", "mason", "builder", "steel fixer", "rebar", "shuttering", "formwork", "carpenter",
                     "plumber", "electrician", "welder", "crane", "site labour", "labourer", "laborer", "tiler", "painter"],
    "Hospitality": ["hotel", "hospitality", "restaurant", "chef", "cook", "kitchen", "waiter", "housekeep", "bartender",
                    "receptionist", "horeca", "dishwasher"],
    "Logistics": ["warehouse", "logistics", "forklift", "driver", "delivery", "picker", "packer", "courier"],
    "Agriculture": ["farm", "agricultur", "harvest", "fruit picking", "greenhouse", "livestock", "poultry"],
    "Manufacturing": ["factory", "manufactur", "production line", "assembly", "machine operator", "cnc"],
    "Cleaning": ["cleaner", "cleaning", "janitor"],
    "Care": ["caregiver", "carer", "nurse", "elderly care", "domestic worker"],
    "Maritime": ["seafarer", "maritime", "deckhand", "ship", "vessel"],
    "IT & Office": ["developer", "software", "accountant", "analyst", "engineer", "it support", "administrator"],
}
VISA_TERMS = ["visa sponsor", "work permit", "sponsorship", "non-eu", "non eu", "third-country", "third country",
              "relocation", "visa provided", "work visa", "foreign workers", "overseas"]
COUNTRIES = ["Cyprus", "Greece", "Romania", "Poland", "Portugal", "Malta", "Croatia", "Bulgaria", "Hungary",
             "Czech", "Slovakia", "Lithuania", "Latvia", "Estonia", "Germany", "Italy", "Spain"]


def classify(text):
    t = text.lower()
    sector = next((s for s, kws in SECTORS.items() if any(k in t for k in kws)), "General")
    visa = any(k in t for k in VISA_TERMS)
    country = next((c for c in COUNTRIES if c.lower() in t), "")
    return sector, visa, country


def opp_hash(title, url):
    key = (re.sub(r"\s+", " ", title.strip().lower()) + "|" + (url or "").split("#")[0].rstrip("/")).encode()
    return hashlib.sha256(key).hexdigest()[:32]


def load_sources(path=None):
    path = path or os.environ.get("MUSA_SOURCES_FILE") or os.path.join(DATA_DIR, "sources.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)["sources"]


# ---------------- fetching ----------------

_robots = {}
_last_hit = {}


def allowed(url):
    """robots.txt check, cached per host. Unreachable robots.txt = allowed (standard crawler behaviour)."""
    p = urlparse(url)
    base = "%s://%s" % (p.scheme, p.netloc)
    rp = _robots.get(base)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser(base + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp = None
        _robots[base] = rp
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def fetch(url, opener=None):
    if not allowed(url):
        raise PermissionError("robots.txt disallows %s" % url)
    host = urlparse(url).netloc
    wait = HOST_DELAY_S - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with (opener or urllib.request.urlopen)(req, timeout=FETCH_TIMEOUT) as r:
        return r.read(3_000_000).decode(r.headers.get_content_charset() or "utf-8", "replace")


# ---------------- parsers ----------------

def _strip_tags(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse_feed(text):
    """RSS 2.0 or Atom → [{title, url, summary}]."""
    root = ET.fromstring(text.encode("utf-8") if isinstance(text, str) else text)
    items = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        get = lambda name: next((c for c in it if c.tag.split("}")[-1] == name), None)
        title = get("title")
        link = get("link")
        url = ""
        if link is not None:
            url = (link.text or "").strip() or link.attrib.get("href", "")
        summ = get("description") or get("summary") or get("content")
        items.append({"title": _strip_tags(title.text if title is not None else ""), "url": url,
                      "summary": _strip_tags(summ.text if summ is not None else "")[:600]})
    return [i for i in items if i["title"]]


def parse_jsonfeed(text):
    data = json.loads(text)
    out = []
    for it in data.get("items", []):
        out.append({"title": _strip_tags(it.get("title", "")), "url": it.get("url", ""),
                    "summary": _strip_tags(it.get("summary") or it.get("content_text") or it.get("content_html") or "")[:600]})
    return [i for i in out if i["title"]]


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links, self._href, self._buf = [], None, []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._buf).split())))
            self._href = None


def parse_html_links(text, base_url, must_contain=(), href_pattern=None):
    p = _LinkParser()
    p.feed(text)
    rx = re.compile(href_pattern) if href_pattern else None
    out, seen = [], set()
    for href, label in p.links:
        if not href or not label or len(label) < 8:
            continue
        url = urljoin(base_url, href)
        if rx and not rx.search(url):
            continue
        low = (label + " " + url).lower()
        if must_contain and not any(k.lower() in low for k in must_contain):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append({"title": label[:200], "url": url, "summary": ""})
    return out


PARSERS = {"rss": parse_feed, "atom": parse_feed, "jsonfeed": parse_jsonfeed}


# ---------------- ingest ----------------

def ingest(items, source, now=None):
    """Upsert items; returns number of new opportunities."""
    added = 0
    stamp = now or db.now_iso()
    for it in items:
        text = " ".join([it.get("title", ""), it.get("summary", ""), source.get("default_country", "")])
        sector, visa, country = classify(text)
        h = opp_hash(it["title"], it.get("url"))
        existing = db.q("SELECT id FROM opportunities WHERE hash=?", (h,), one=True)
        if existing:
            db.x("UPDATE opportunities SET updated_at=?, expires_at=? WHERE id=?", (stamp, db.now_iso(FRESH_DAYS), existing["id"]))
            continue
        db.insert("opportunities", hash=h, title=it["title"][:240], sector=it.get("sector") or sector,
                  country=it.get("country") or country or source.get("default_country", ""),
                  location=it.get("location", ""), employer=it.get("employer", ""), salary_text=it.get("salary_text", ""),
                  url=it.get("url", ""), source=source["name"], source_tier=int(source.get("tier", 4)),
                  visa_signal=1 if (visa or it.get("visa_signal")) else 0,
                  status="signal" if int(source.get("tier", 4)) <= 1 else "lead",
                  summary=it.get("summary", ""), found_at=stamp, updated_at=stamp, expires_at=db.now_iso(FRESH_DAYS))
        added += 1
    return added


def run_source(source, opener=None):
    run_id = db.insert("scout_runs", started_at=db.now_iso(), source=source["id"])
    fetched = added = 0
    err = ""
    try:
        text = fetch(source["url"], opener)
        if source["type"] == "html-links":
            items = parse_html_links(text, source["url"], source.get("must_contain", ()), source.get("href_pattern"))
        else:
            items = PARSERS[source["type"]](text)
        items = items[: int(source.get("max_items", 100))]
        fetched = len(items)
        added = ingest(items, source)
    except Exception as e:  # one bad source never stops the others
        err = "%s: %s" % (type(e).__name__, e)
    db.x("UPDATE scout_runs SET finished_at=?, fetched=?, added=?, error=? WHERE id=?",
         (db.now_iso(), fetched, added, err[:500], run_id))
    return {"source": source["id"], "fetched": fetched, "added": added, "error": err}


def expire_stale():
    return db.xc("UPDATE opportunities SET status='expired' WHERE status IN ('lead','signal') AND expires_at < ?", (db.now_iso(),))


def run_all(sources=None, opener=None):
    sources = sources if sources is not None else load_sources()
    results = [run_source(s, opener) for s in sources if s.get("enabled") and s.get("url")]
    expire_stale()
    db.audit("agent:scout", "scout.run", detail={"sources": len(results), "added": sum(r["added"] for r in results)})
    return results


def seed(path=None):
    """Load research signals once (idempotent — hash dedupe)."""
    path = path or os.path.join(DATA_DIR, "opportunities_seed.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError:
        return 0
    total = 0
    for group in data["groups"]:
        total += ingest(group["items"], group["source"], now=data.get("observed_on"))
    return total
