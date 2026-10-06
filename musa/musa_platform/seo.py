"""Acquisition engine: search-optimised guides, programmatic sector pages, sitemap and robots.

Guides only restate entries from the sourced knowledge base and the trap library, so nothing
published here is unsourced. Sector pages are built live from the opportunity board.
"""
import re
from datetime import datetime, timezone

from . import db
from .ui import alerts_cta, e, layout, opp_card, site_url, wa_link

SECTOR_INTRO = {
    "Construction": "Masons, steel fixers, shuttering carpenters, electricians and site labourers are among the most-requested roles for third-country workers in Cyprus.",
    "Hospitality": "Hotels and restaurants in Limassol, Paphos, Ayia Napa and Larnaca hire cooks, housekeeping and service staff, often ahead of the summer season.",
    "Logistics": "Warehouses and distribution companies hire pickers, forklift operators and drivers, mainly around Limassol, Nicosia and Larnaca.",
    "Agriculture": "Farms and greenhouses hire seasonal harvest and farm workers. Seasonal roles have their own permit conditions, so check the contract length.",
    "Manufacturing": "Factories and food-production sites hire machine operators, packers and quality staff.",
    "Cleaning": "Cleaning companies hire for hotels, offices and residential contracts.",
    "Care": "Elderly-care and domestic-care roles usually ask for caregiving experience, first aid and conversational English.",
    "Maritime": "Shipping companies in Limassol hire seafarers and maritime support staff.",
    "General": "Mixed listings that did not match a single sector.",
}


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def guides(knowledge, traps):
    k = {x["id"]: x for x in knowledge}

    def faq(ids):
        return [(k[i]["q"], k[i]["a"], k[i]["sources"]) for i in ids if i in k]

    return [
        {"slug": "cyprus-work-visa-from-pakistan", "title": "Cyprus work visa from Pakistan: how the process really works",
         "description": "Who applies, what must exist before you travel, and how to check the agent, explained with official sources.",
         "lede": "A work visa for Cyprus starts with a real employer, not an agent. Here is the order of steps and what to check at each one.",
         "faq": faq(["K2", "K1", "K3", "K10", "K4", "K5"])},
        {"slug": "cyprus-visa-scams", "title": "Cyprus and Europe visa scams: %d warning signs from real cases" % len(traps),
         "description": "The tricks agents use: guaranteed visas, appointment fees, personal accounts, fake documents. How to spot them and what to reply.",
         "lede": "Every pattern below comes from real recruitment cases. One sign is a reason to slow down; several together are a reason to stop.",
         "traps": True, "faq": faq(["K9", "K10", "K4"])},
        {"slug": "check-oep-licence-beoe", "title": "How to check a Pakistani recruiting agent (OEP) and BEOE permission",
         "description": "Get the OEP licence and BEOE permission number, check both yourself, and contact the agency through official details.",
         "lede": "Licensed Overseas Employment Promoters are registered with BEOE. Checking takes ten minutes and protects lakhs of rupees.",
         "faq": faq(["K3", "K2", "K10"])},
        {"slug": "cyprus-visa-cost", "title": "How much does a Cyprus work visa cost?",
         "description": "Why nobody honest quotes a single 'package' price, and how to split official fees from agent fees before paying.",
         "lede": "Official fees change and are published by the authorities. Anything else in a 'package' is an agent fee and should be written down.",
         "faq": faq(["K5", "K10", "K1"])},
        {"slug": "study-in-cyprus-from-pakistan", "title": "Studying in Cyprus from Pakistan: the student route",
         "description": "Accredited institutions, admission, the student permit and proof of funds, with official sources.",
         "lede": "Start with an accredited institution and a real admission letter. The permit follows from that.",
         "faq": faq(["K7", "K8", "K12"])},
        {"slug": "north-cyprus-vs-cyprus-work-permit", "title": "North Cyprus vs the Republic of Cyprus: why offers are not the same",
         "description": "The island has two separate immigration systems. What that means for job offers 'in Cyprus'.",
         "lede": "Many offers say 'Cyprus' without saying which system. The difference decides your rights, your permit and your route to the EU.",
         "faq": faq(["K6", "K2", "K4"])},
    ]


def _faq_ld(items):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a, _ in items]}


def _cta(topic):
    wa = wa_link("Assalam o alaikum, I read your guide on %s and want my offer checked." % topic)
    return ('<div class="panel stack"><span class="eyebrow">Before you pay anyone</span><h3>Get your offer checked against official records</h3>'
            '<p class="muted">OEP licence, BEOE permission, employer registration and a fee breakdown. Written decision in 48 hours.</p>'
            '<div class="row"><a class="btn primary" href="/report">Order a report (Rs 4,500)</a><a class="btn" href="/check">Free scam scan</a>%s</div></div>'
            % (('<a class="btn" href="%s" target="_blank" rel="noopener">Ask on WhatsApp</a>' % e(wa)) if wa else ""))


def guides_index(items):
    cards = "".join('<a class="card" href="/guides/%s" style="text-decoration:none;color:inherit"><h3>%s</h3><p class="muted" style="margin:0">%s</p></a>'
                    % (g["slug"], e(g["title"]), e(g["description"])) for g in items)
    sectors = "".join('<a class="chip" href="/jobs/%s">%s</a>' % (slugify(s), e(s)) for s in SECTOR_INTRO if s != "General")
    return layout("Guides", """<section><div class="wrap stack"><span class="eyebrow">Guides</span><h1>Plain answers before you pay anyone</h1>
<p class="muted">Short guides built from official sources, with every source listed. Written for workers, students and families in Pakistan.</p>
<div class="grid">%s</div><h2 style="margin-top:24px">Jobs by sector</h2><div class="row">%s</div></div></section>""" % (cards, sectors),
                  active="/guides", path="/guides", description="Guides to Cyprus work, study and family routes from Pakistan, with official sources.")


def guide_page(g, traps):
    body = ""
    if g.get("traps"):
        rows = "".join('<div class="hit"><div class="row"><span class="sev %s">%s</span><b>%s</b></div><div>%s</div><small class="muted">%s</small></div>'
                       % (e(t["severity"]), e(t["severity"]), e(t["name"]), e(t["response"]), e(t.get("response_ur", ""))) for t in traps)
        body += '<h2>The warning signs</h2><div class="card result">%s</div>' % rows
    qa = ""
    for q, a, srcs in g["faq"]:
        links = " · ".join('<a href="%s"%s>%s</a>' % (e(s["url"]), ' target="_blank" rel="noopener"' if s["url"].startswith("http") else "", e(s["title"])) for s in srcs)
        qa += '<div class="card"><h3>%s</h3><p>%s</p><small class="muted">Sources: %s</small></div>' % (e(q), e(a), links)
    article = {"@context": "https://schema.org", "@type": "Article", "headline": g["title"], "description": g["description"],
               "publisher": {"@type": "Organization", "name": "MUSA Corridor"}, "inLanguage": "en"}
    return layout(g["title"], """<section><div class="wrap split"><article class="stack"><span class="eyebrow">Guide</span><h1 style="font-size:clamp(1.8rem,4vw,2.8rem)">%s</h1>
<p class="lede" style="font-size:1.1rem;color:var(--muted)">%s</p>%s<h2>Questions people ask</h2>%s
<p class="muted">General information, not legal advice. Rules and fees change: re-check each official source on the day you act.</p></article>
<aside class="stack">%s<div class="card stack"><h3>Paste the agent's message</h3><form method="post" action="/check" class="stack" style="width:100%%"><textarea name="text" required aria-label="Agent's message" style="min-height:110px"></textarea><button class="btn copper" type="submit">Check for warning signs</button></form></div></aside>
</div></section>""" % (e(g["title"]), e(g["lede"]), body, qa, _cta(g["title"])),
                  active="/guides", path="/guides/" + g["slug"], description=g["description"], jsonld=[article, _faq_ld(g["faq"])])


def sector_page(sector, rows, total, visa_count):
    intro = SECTOR_INTRO.get(sector, "")
    cards = "".join(opp_card(o) for o in rows) or '<p class="muted">No live listings in this sector right now. Scout checks for new ones every few hours.</p>'
    title = "Cyprus %s jobs with visa sponsorship for Pakistani workers" % sector.lower()
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": title, "description": intro,
          "about": {"@type": "Occupation", "name": sector + " worker", "occupationLocation": {"@type": "Country", "name": "Cyprus"}}}
    return layout(title, """<section><div class="wrap stack"><span class="eyebrow">Jobs by sector · updated by Scout</span><h1 style="font-size:clamp(1.8rem,4vw,2.8rem)">%s</h1>
<p class="muted">%s</p><div class="row"><span class="chip">%d live listings</span><span class="chip visa">%d mention sponsorship</span></div>
<div class="note">A listing is a lead, not a verified job. Before paying anyone, check the OEP licence, the BEOE permission and the employer, or <a href="/report">let us check it</a>.</div>
<div class="opps">%s</div>
<div class="split" style="margin-top:20px"><div class="card stack"><h3>Get matched to %s roles</h3><p class="muted">Enter your skills and experience; we score you against what Cyprus employers ask for and build an EU-format CV.</p><a class="btn primary" href="/match">Match me</a></div>%s</div>
<div style="margin-top:20px">%s</div>
</div></section>""" % (e(title), e(intro), total, visa_count, cards, e(sector.lower()), _cta(sector.lower() + " jobs"), alerts_cta(sector)),
                  active="/opportunities", path="/jobs/" + slugify(sector), description="%s Live listings with source labels and a free scam check." % intro, jsonld=ld)


def sitemap(guide_items, sectors):
    base = site_url()
    if not base:
        return None
    today = datetime.now(timezone.utc).date().isoformat()
    paths = ["/", "/ur", "/ur/check", "/check", "/opportunities", "/guides", "/match", "/ask", "/pricing", "/business", "/business/partners",
             "/business/employers", "/alerts", "/agents", "/privacy", "/terms"]
    paths += ["/guides/" + g["slug"] for g in guide_items] + ["/jobs/" + slugify(s) for s in sectors]
    paths += ["/opportunities/%d" % r["id"] for r in db.q("SELECT id FROM opportunities WHERE status IN ('signal','verified') ORDER BY id DESC LIMIT 500")]
    paths += ["/partners/" + r["slug"] for r in db.q("SELECT slug FROM partners WHERE status='approved'")]
    urls = "".join("<url><loc>%s%s</loc><lastmod>%s</lastmod></url>" % (e(base), e(p), today) for p in paths)
    return '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">%s</urlset>' % urls


def robots():
    base = site_url()
    lines = ["User-agent: *", "Disallow: /admin", "Disallow: /cv/", "Disallow: /order/", "Disallow: /shortlist/", "Disallow: /api/", "Disallow: /alerts/stop/", "Allow: /"]
    if base:
        lines.append("Sitemap: %s/sitemap.xml" % base)
    return "\n".join(lines) + "\n"
