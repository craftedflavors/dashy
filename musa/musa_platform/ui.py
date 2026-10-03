"""Server-rendered pages. Every value that reaches HTML goes through e()."""
from html import escape
import json
import os
from urllib.parse import quote, urlencode

from .compliance import CONSENT_TEXT, RETENTION_DAYS

TIER_LABEL = {0: "Government", 1: "Employer", 2: "Licensed agency", 3: "Professional", 4: "Job board", 5: "Social / unverified"}
STATUS_LABEL = {"lead": "Lead — unverified", "signal": "Official signal", "verified": "Verified by MUSA", "flagged": "Flagged", "expired": "Expired"}


def e(v):
    return escape("" if v is None else str(v), quote=True)


def fmt_int(n):
    return format(int(n or 0), ",")


def tier_chip(t):
    t = int(t if t is not None else 5)
    return '<span class="chip t%d" title="Source trust tier %d">T%d · %s</span>' % (t, t, t, e(TIER_LABEL.get(t, "")))


def status_chip(s):
    cls = {"verified": "ok", "flagged": "bad"}.get(s, "")
    return '<span class="chip %s">%s</span>' % (cls, e(STATUS_LABEL.get(s, s)))


def consent_box(kind, name="consent"):
    return ('<label class="check"><input type="checkbox" name="%s" id="%s-%s" required> <span>%s '
            '<a href="/privacy">Privacy notice</a>.</span></label>' % (name, name, kind, e(CONSENT_TEXT[kind])))


NAV = [("/check", "Scam Shield"), ("/opportunities", "Opportunities"), ("/guides", "Guides"), ("/match", "Match & CV"), ("/ask", "Ask"), ("/pricing", "Pricing")]


def site_url():
    return os.environ.get("MUSA_SITE_URL", "").rstrip("/")


def whatsapp_number():
    return "".join(ch for ch in os.environ.get("MUSA_WHATSAPP", "") if ch.isdigit())


def wa_link(text):
    n = whatsapp_number()
    return "https://wa.me/%s?%s" % (n, urlencode({"text": text})) if n else ""


DEFAULT_DESC = "Check job and visa offers before you pay. Verified opportunities and hiring for the Pakistan–Cyprus corridor."


def head_meta(title, description, path, jsonld):
    """Canonical URL, Open Graph and JSON-LD for public pages (search and WhatsApp/Facebook link previews)."""
    base = site_url()
    out = ['<meta property="og:title" content="%s">' % e(title), '<meta property="og:description" content="%s">' % e(description),
           '<meta property="og:type" content="website">', '<meta property="og:site_name" content="MUSA Corridor">', '<meta name="twitter:card" content="summary">']
    if base and path is not None:
        out.append('<link rel="canonical" href="%s%s">' % (e(base), e(path)))
        out.append('<meta property="og:url" content="%s%s">' % (e(base), e(path)))
    for block in ([jsonld] if isinstance(jsonld, dict) else (jsonld or [])):
        out.append('<script type="application/ld+json">%s</script>' % json.dumps(block, ensure_ascii=False).replace("</", "<\\/"))
    return "".join(out)


def layout(title, body, active="", description="", admin=False, flash=None, path=None, jsonld=None, noindex=False, lang="en"):
    nav = "".join('<a href="%s"%s>%s</a>' % (h, ' aria-current="page"' if h == active else "", e(t)) for h, t in NAV)
    nav += '<a class="cta" href="/business">For business</a>'
    if admin:
        nav = "".join('<a href="%s"%s>%s</a>' % (h, ' aria-current="page"' if h == active else "", t) for h, t in [
            ("/admin", "Overview"), ("/admin/opportunities", "Opportunities"), ("/admin/orders", "Orders"), ("/admin/partners", "Partners"),
            ("/admin/employers", "Employers"), ("/admin/leads", "WhatsApp leads"), ("/admin/scout", "Scout"), ("/admin/compliance", "Compliance"), ("/admin/revenue", "Revenue")])
    flash_html = ""
    if flash:
        kind, msg = flash
        flash_html = '<div class="wrap" style="padding-top:16px"><div class="flash %s" role="status">%s</div></div>' % ("err" if kind == "err" else "", e(msg))
    return """<!doctype html>
<html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>%s</title><meta name="description" content="%s">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Familjen+Grotesk:wght@500;600;700&family=IBM+Plex+Mono:wght@500;600&family=Public+Sans:wght@400;500;600&display=swap">
<link rel="stylesheet" href="/static/site.css">%s<link rel="icon" href="data:image/svg+xml,%%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%%3E%%3Crect width='32' height='32' rx='6' fill='%%230c4a5c'/%%3E%%3Ctext x='16' y='22' font-size='16' text-anchor='middle' fill='white' font-family='Arial' font-weight='700'%%3EM%%3C/text%%3E%%3C/svg%%3E">
%s</head><body>
<a class="skip" href="#main">Skip to content</a>
<header class="site"><div class="wrap"><a class="logo" href="%s"><b>MUSA</b><span>PAK → CYP · VERIFIED CORRIDOR%s</span></a><nav class="main" aria-label="Main">%s</nav></div></header>
%s<main id="main">%s</main>
<footer class="site"><div class="wrap">
<div><b style="color:var(--ink)">MUSA Corridor</b><p>Verification-first help for work, study and hiring between Pakistan, Cyprus and the EU. We do not sell jobs or visas.</p></div>
<ul><li><a href="/check">Scam Shield</a></li><li><a href="/ur" hreflang="ur-Latn">Roman Urdu</a></li><li><a href="/opportunities">Opportunities</a></li><li><a href="/match">Match &amp; EU CV</a></li><li><a href="/ask">Ask the concierge</a></li></ul>
<ul><li><a href="/business">For employers &amp; agencies</a></li><li><a href="/business/partners">Become a verified partner</a></li><li><a href="/business/employers">Request candidates</a></li><li><a href="/pricing">Pricing</a></li></ul>
<ul>%s<li><a href="/privacy">Privacy (GDPR)</a></li><li><a href="/privacy/request">Your data rights</a></li><li><a href="/agents">AI &amp; automation transparency</a></li><li><a href="/terms">Terms</a></li></ul>
</div></footer></body></html>""" % (lang,
        e(title + ("" if title.startswith("MUSA") else " · MUSA Corridor")), e(description or DEFAULT_DESC),
        "" if admin else head_meta(title, description or DEFAULT_DESC, path, jsonld),
        '<meta name="robots" content="noindex">' if (admin or noindex) else "", "/admin" if admin else "/", " · ADMIN" if admin else "", nav, flash_html, body,
        ('<li><a href="%s" target="_blank" rel="noopener">WhatsApp +%s</a></li>' % (e(wa_link("Assalam o alaikum, I have a question about an offer.")), e(whatsapp_number()))) if whatsapp_number() else "")


# ---------------- public pages ----------------

def opp_card(o):
    meta = tier_chip(o["source_tier"]) + status_chip(o["status"])
    if o["visa_signal"]:
        meta += '<span class="chip visa">Visa sponsorship mentioned</span>'
    if o["sector"]:
        meta += '<span class="chip">%s</span>' % e(o["sector"])
    return """<article class="opp"><div class="stack" style="gap:8px"><h3><a href="/opportunities/%d">%s</a></h3>
<div class="meta">%s</div><small>%s · %s · found %s</small></div>
<a class="btn small" href="/report?opp=%d">Verify this</a></article>""" % (
        o["id"], e(o["title"]), meta, e(o["source"]), e(o["country"] or "—"), e((o["found_at"] or "")[:10]), o["id"])


def home(stats, latest):
    mrz = ("P&lt;PAK&lt;&lt;CYP&lt;&lt;OPPORTUNITIES&lt;<b>%s</b>&lt;&lt;VISA&lt;SIGNALS&lt;<b>%s</b>&lt;&lt;SCANS&lt;7D&lt;<b>%s</b>&lt;&lt;PARTNERS&lt;<b>%s</b>&lt;&lt;&lt;"
           % (fmt_int(stats["opps"]), fmt_int(stats["visa"]), fmt_int(stats["scans_7d"]), fmt_int(stats["partners"])))
    cards = "".join(opp_card(o) for o in latest) or '<p class="muted">Scout is collecting the first opportunities.</p>'
    return layout("MUSA Corridor — check before you pay", """
<section class="hero"><div class="wrap split">
 <div class="stack" style="gap:20px">
  <span class="eyebrow">Pakistan → Cyprus &amp; EU · work · study · hiring</span>
  <h1>Check the offer before you pay the agent.</h1>
  <p class="lede">MUSA verifies job and visa offers against official records, shows you which fees are real, and connects verified workers with licensed agencies and employers in Cyprus.</p>
  <div class="row"><a class="btn primary" href="/check">Scan an agent's message</a><a class="btn" href="/opportunities">See live opportunities</a></div>
  <div class="row"><span class="chip ok">GDPR by design</span><span class="chip">EU AI Act transparency</span><span class="chip">Human approval on every decision</span></div>
 </div>
 <form class="panel stack" method="post" action="/check" aria-label="Quick scam check">
  <span class="eyebrow">Scam Shield · free</span>
  <label for="hero-text">Paste the agent's WhatsApp message or offer<span class="hint">Checked against 20 known scam patterns. The text is not stored.</span></label>
  <textarea id="hero-text" name="text" required placeholder="e.g. Cyprus visa 100%% guarantee. Pay 2 lakh today to my account, contract after payment."></textarea>
  <button class="btn copper" type="submit">Check for warning signs</button>
 </form>
</div>
<div class="wrap" style="margin-top:36px"><div class="mrz" aria-label="Live platform numbers">%s</div></div></section>

<section class="tight"><div class="wrap grid">
 <div class="card"><span class="eyebrow">For workers</span><h3>Don't lose money to fake offers</h3><p>Free scam scan, a Verify-Before-You-Pay report for Rs 4,500, and an EU-format CV with job matching.</p><a href="/report">Order a report →</a></div>
 <div class="card"><span class="eyebrow">Students &amp; families</span><h3>Get sourced answers</h3><p>Our concierge answers from official sources only and shows each source. Study, work and family routes.</p><a href="/ask">Ask a question →</a></div>
 <div class="card"><span class="eyebrow">Employers in Cyprus</span><h3>Hire pre-verified candidates</h3><p>Shortlists of candidates whose identity, documents and experience are checked, through licensed agencies.</p><a href="/business/employers">Request candidates →</a></div>
 <div class="card"><span class="eyebrow">Agencies &amp; OEPs</span><h3>Earn the verified badge</h3><p>Licensed recruiters are shown as verified when families check their offers. Plus case tooling.</p><a href="/business/partners">Apply as a partner →</a></div>
</div></section>

<section><div class="wrap stack">
 <div class="row" style="justify-content:space-between"><div><span class="eyebrow">Updated by Scout</span><h2>Latest opportunities</h2></div><a class="btn" href="/opportunities">All opportunities</a></div>
 <p class="muted">Every listing shows where it came from and how far it can be trusted. Leads are not verified vacancies. Verify before anyone pays.</p>
 <div class="opps">%s</div>
</div></section>

<section><div class="wrap stack">
 <span class="eyebrow">How verification works</span><h2>Four checks before any money moves</h2>
 <div class="steps">
  <div><h3>Scan the offer</h3><p class="muted">Sentinel flags guaranteed visas, personal accounts, fake appointment fees and 17 other known tricks.</p></div>
  <div><h3>Check at the source</h3><p class="muted">OEP licence and BEOE permission on beoe.gov.pk; the employer in the Cyprus company registry.</p></div>
  <div><h3>Split the fees</h3><p class="muted">Official government fees separated from agent fees. Anything without a source is marked unverified.</p></div>
  <div><h3>Pay safely, or don't</h3><p class="muted">A written decision: proceed, hold, or stop. A person signs off on every decision.</p></div>
 </div>
</div></section>

<section class="tight"><div class="wrap"><div class="panel split" style="align-items:center">
 <div><span class="eyebrow">Built for EU rules</span><h2>Compliance is the product, not a footnote</h2>
 <p class="muted">GDPR consent on every form, data export and erasure on request, published retention periods, an audit trail for every decision, and an AI transparency page listing every agent and what a human must approve.</p></div>
 <div class="stack"><a class="btn" href="/agents">See our agents</a><a class="btn" href="/privacy">Read the privacy notice</a></div>
</div></div></section>
""" % (mrz, cards), active="/", path="/", jsonld={"@context": "https://schema.org", "@type": "Organization", "name": "MUSA Corridor", "description": DEFAULT_DESC})


def check_page(text="", result=None):
    res = ""
    if result:
        d = result["decision"]
        hits = result["hits"]
        if d["colour"] == "RED":
            stamp, msg = '<span class="stamp red">Stop — do not pay</span>', "Serious warning signs. Do not pay anyone until the offer is verified."
        elif hits:
            stamp, msg = '<span class="stamp amber">Hold — verify first</span>', "Warning signs found. Verify before paying."
        else:
            stamp, msg = '<span class="stamp amber">No known pattern</span>', "No known scam pattern found. That does not make the offer genuine: nothing has been verified yet."
        items = "".join('<div class="hit"><div class="row"><span class="sev %s">%s</span><b>%s</b></div><q>…%s…</q><div>%s</div><small class="muted">%s</small></div>' % (
            e(h["severity"]), e(h["severity"]), e(h["name"]), e(h["evidence"]), e(h["response"]), e(h.get("response_ur", ""))) for h in hits)
        res = """<div class="panel result" aria-live="polite">%s<p>%s</p>
<div><div class="meter" role="img" aria-label="Risk %d out of 100"><i style="width:%d%%"></i></div><small class="muted">Risk %d/100 (%s) · %d warning sign(s)</small></div>
%s<div class="note">Want it checked against official records before you pay? <a href="/report">Order a Verify-Before-You-Pay report (Rs 4,500)</a>%s.</div></div>""" % (
            stamp, e(msg), d["risk"]["score"], min(100, d["risk"]["score"]), d["risk"]["score"], e(d["risk"]["band"]), len(hits), items,
            (' or <a href="%s" target="_blank" rel="noopener">ask us on WhatsApp</a>' % e(wa_link("Assalam o alaikum, Scam Shield found %d warning sign(s): %s. I want a report." % (len(hits), ", ".join(h["id"] for h in hits))))) if whatsapp_number() else "")
    return layout("Scam Shield", """<section><div class="wrap split">
<form class="stack" method="post" action="/check"><div class="row" style="justify-content:space-between"><span class="eyebrow">Scam Shield</span><a class="chip" href="/ur/check" hreflang="ur-Latn">Roman Urdu mein</a></div><h1>Is this offer a scam?</h1>
<p class="muted">Paste what the agent sent: WhatsApp message, ad or offer letter. English or Roman Urdu. We check it against 20 patterns from real cases. The text is processed and discarded, not stored.</p>
<label for="text">Agent's message</label><textarea id="text" name="text" required>%s</textarea>
<div class="row"><button class="btn copper" type="submit">Check for warning signs</button><a class="btn" href="/check?example=1">Try an example</a></div></form>
<div class="stack">%s<div class="card"><h3>Five rules that protect your money</h3><ol class="muted" style="margin:0;padding-left:18px">
<li>Get the OEP licence and BEOE permission number, and check both on beoe.gov.pk yourself.</li><li>Contract first, payment second.</li>
<li>Pay the company, never a personal account or wallet, and get a receipt.</li><li>No one can guarantee a visa.</li><li>Never travel on a visit visa to work.</li></ol></div></div>
</div></section>""" % (e(text), res), active="/check", path="/check", description="Paste a recruiter's message and see known scam warning signs instantly. Free, English and Roman Urdu.")


def opportunities_page(rows, sectors, f, total):
    opts = lambda vals, cur: "".join('<option value="%s"%s>%s</option>' % (e(v), " selected" if v == cur else "", e(v or "All")) for v in vals)
    cards = "".join(opp_card(o) for o in rows) or '<p class="muted">No opportunities match these filters.</p>'
    return layout("Opportunities", """<section><div class="wrap stack">
<span class="eyebrow">Live board · refreshed by Scout</span><h1>Opportunities</h1>
<p class="muted">%s listings from government records, licensed partners and job boards. Each shows its source and trust tier. A lead is something we found, not something we verified.</p>
<form class="form-grid card" method="get" action="/opportunities">
 <label>Sector<select name="sector">%s</select></label>
 <label>Trust<select name="tier"><option value="">Any source</option><option value="0"%s>Government only</option><option value="2"%s>Licensed partners and above</option></select></label>
 <label>Visa sponsorship<select name="visa"><option value="">Any</option><option value="1"%s>Mentions sponsorship</option></select></label>
 <label>Search<input name="q" value="%s" placeholder="e.g. hotel, Limassol"></label>
 <div style="align-self:end"><button class="btn primary" type="submit">Filter</button></div>
</form>
<div class="opps">%s</div>
<p class="muted">API: <a href="/api/opportunities">/api/opportunities</a> (JSON)</p>
</div></section>""" % (fmt_int(total), opts([""] + sectors, f.get("sector", "")), " selected" if f.get("tier") == "0" else "",
                       " selected" if f.get("tier") == "2" else "", " selected" if f.get("visa") == "1" else "", e(f.get("q", "")), cards), active="/opportunities", path="/opportunities", description="Live Cyprus and EU opportunities for Pakistani workers, each labelled by source and trust level.")


def opportunity_detail(o):
    return layout(o["title"], """<section><div class="wrap split">
<div class="stack"><span class="eyebrow">Opportunity #%d</span><h1 style="font-size:clamp(1.6rem,3.6vw,2.4rem)">%s</h1>
<div class="row">%s%s%s</div>
<dl class="card" style="margin:0;display:grid;grid-template-columns:max-content 1fr;gap:8px 16px">
<dt class="muted">Sector</dt><dd style="margin:0">%s</dd><dt class="muted">Country</dt><dd style="margin:0">%s</dd>
<dt class="muted">Employer</dt><dd style="margin:0">%s</dd><dt class="muted">Location</dt><dd style="margin:0">%s</dd>
<dt class="muted">Source</dt><dd style="margin:0">%s</dd><dt class="muted">First seen</dt><dd style="margin:0">%s</dd></dl>
%s
<div class="row">%s<a class="btn primary" href="/report?opp=%d">Verify before you pay</a></div></div>
<div class="card stack"><h3>What this label means</h3><p class="muted">%s</p>
<h3>Before you pay anyone for this</h3><ol class="muted" style="margin:0;padding-left:18px"><li>Ask for the OEP licence and BEOE permission number.</li><li>Ask for the employer's legal name and registration number.</li><li>Ask for the contract and an itemised fee list.</li></ol>
<a href="/check">Scan the agent's message →</a></div></div></section>""" % (
        o["id"], e(o["title"]), tier_chip(o["source_tier"]), status_chip(o["status"]),
        '<span class="chip visa">Visa sponsorship mentioned</span>' if o["visa_signal"] else "",
        e(o["sector"] or "—"), e(o["country"] or "—"), e(o["employer"] or "Not stated"), e(o["location"] or "—"), e(o["source"]), e((o["found_at"] or "")[:10]),
        ('<p>%s</p>' % e(o["summary"])) if o["summary"] else "",
        ('<a class="btn" href="%s" target="_blank" rel="noopener nofollow">Open original listing</a>' % e(o["url"])) if o["url"] else "", o["id"],
        {"lead": "We found this listing on a third-party site. Nobody has confirmed the employer, the job or the visa route yet.",
         "signal": "This comes from an official government source, but you still need to confirm the OEP and the employer.",
         "verified": "A MUSA analyst confirmed the employer and the recruiter's licence. Fees and contract still need checking for your case.",
         "flagged": "We found problems with this listing. Do not pay for it.", "expired": "This listing has not been seen for 45 days."}.get(o["status"], "")), active="/opportunities", path="/opportunities/%d" % o["id"])


def match_page(results=None, profile=None, token=None, live=None, flash=None):
    out = ""
    if results is not None:
        rows = "".join("""<div class="card stack" style="gap:8px"><div class="row" style="justify-content:space-between"><h3 style="margin:0">%s</h3><span class="chip %s">%d%% · %s</span></div>
<div class="bar"><i style="width:%d%%"></i></div><small class="muted">Skills %d · experience %d · language %d · certifications %d</small>%s</div>""" % (
            e(r["job"]), "ok" if r["verdict"] == "STRONG" else "", r["overall"], e(r["verdict"].lower()), r["overall"],
            r["axes"].get("skills", 0), r["axes"].get("experience", 0), r["axes"].get("language", 0), r["axes"].get("certifications", 0),
            ('<small>To improve: %s</small>' % e("; ".join(r["gaps"][:3]))) if r["gaps"] else "") for r in results[:6])
        opps = "".join(opp_card(o) for o in (live or [])[:4])
        out = """<div class="stack"><div class="flash">Profile saved. <a href="/cv/%s">Open your EU-format CV</a> · keep this private link to view or delete it.</div>
<h2>Your best-fit roles</h2>%s<p class="muted">Match scores support a recruiter's decision; they never decide for one. Whether a visa route exists depends on a real, verified offer.</p>
%s</div>""" % (e(token), rows, ('<h3>Live opportunities in your top sector</h3><div class="opps">%s</div>' % opps) if opps else "")
    p = profile or {}
    return layout("Match & EU CV", """<section><div class="wrap split">
<form class="stack" method="post" action="/match"><span class="eyebrow">Matchmaker · free</span><h1>Find roles that fit, and get an EU-format CV</h1>
<p class="muted">Tell us your trade. We score you against roles Cyprus employers are hiring for and build a clean CV you can send.</p>
<div class="form-grid"><label>Full name<input name="name" required maxlength="80" value="%s"></label><label>Headline<input name="headline" maxlength="120" placeholder="e.g. Mason, 6 years, Gulf experience" value="%s"></label></div>
<label>Skills<span class="hint">Comma-separated, e.g. mason, shuttering, tiling</span><input name="skills" required value="%s"></label>
<div class="form-grid"><label>Years of experience<input name="years" type="number" min="0" max="50" value="%s"></label>
<label>Languages<span class="hint">e.g. en:A2, ur:native</span><input name="languages" value="%s"></label></div>
<label>Certificates<span class="hint">e.g. OSHA 10, forklift licence</span><input name="certifications" value="%s"></label>
<label>Work history<textarea name="experience" placeholder="2019–2024 · Mason · Al-Futtaim Construction, Dubai">%s</textarea></label>
<label>Education<input name="education" value="%s"></label>
<label>Contact (optional)<span class="hint">Only if you want verified employers to reach you through MUSA</span><input name="contact" maxlength="80"></label>
<label class="check"><input type="checkbox" name="relocation_ready" id="reloc"> <span>I am ready to relocate within 3 months</span></label>
%s<label class="check"><input type="checkbox" name="share_ok" id="share-ok"> <span>%s</span></label><button class="btn primary" type="submit">Match me</button></form>
<div>%s</div></div></section>""" % (
        e(p.get("name", "")), e(p.get("headline", "")), e(", ".join(p.get("skills", []))), e(p.get("years", "")),
        e(", ".join("%s:%s" % kv for kv in (p.get("languages") or {}).items())), e(", ".join(p.get("certifications", []))),
        e(p.get("experience", "")), e(p.get("education", "")), consent_box("profile"), e(CONSENT_TEXT["share"]),
        out or '<div class="card stack"><h3>What employers look for</h3><p class="muted">Construction: masonry, formwork, rebar. Hospitality: line cook, housekeeping, food service (English B1). Logistics: picking, forklift licence. Agriculture: harvesting. Care: caregiving and first aid.</p></div>'), active="/match", flash=flash)


def cv_page(p, token):
    langs = ", ".join("%s (%s)" % (k.upper(), v) for k, v in (p.get("languages") or {}).items()) or "—"
    return layout("CV — " + (p.get("name") or ""), """<section><div class="wrap stack">
<div class="row"><a class="btn small" href="/match">← Back</a><form method="post" action="/cv/%s/delete" class="inline-form"><button class="btn small" type="submit">Delete my profile</button></form>
<small class="muted">Private link. Anyone with it can see this CV. Deleted automatically after 12 months.</small></div>
<article class="cv"><h1>%s</h1><p class="muted" style="margin:4px 0 0">%s</p>
<h2>Skills</h2><p>%s</p><h2>Work experience</h2><p style="white-space:pre-line">%s</p><p class="muted">Total: %s years</p>
<h2>Languages</h2><p>%s</p><h2>Certificates</h2><p>%s</p><h2>Education</h2><p>%s</p>
<h2>Mobility</h2><p>%s</p></article></div></section>""" % (
        e(token), e(p.get("name")), e(p.get("headline")), e(", ".join(p.get("skills", [])) or "—"), e(p.get("experience") or "—"),
        e(p.get("years", 0)), e(langs), e(", ".join(p.get("certifications", [])) or "—"), e(p.get("education") or "—"),
        "Ready to relocate to the EU within 3 months." if p.get("relocation_ready") else "Relocation timing to be agreed."), noindex=True)


def shortlist_page(req, items):
    cards = []
    for it in items:
        p = it["profile"]
        langs = ", ".join("%s (%s)" % (k.upper(), v) for k, v in (p.get("languages") or {}).items()) or "—"
        cards.append("""<article class="cv" style="padding:24px"><div class="row" style="justify-content:space-between"><h2 style="margin:0;font-size:1.3rem;font-family:var(--display);color:var(--ink);border:0;text-transform:none;letter-spacing:0">%s</h2>
<span class="chip ok">Match %d%%</span></div><p class="muted" style="margin:4px 0 10px">%s · candidate ref <span class="mono">%s</span></p>
<p><b>Skills:</b> %s</p><p><b>Experience:</b> %s years. %s</p><p><b>Languages:</b> %s · <b>Certificates:</b> %s</p><p class="muted">%s</p></article>""" % (
            e(p.get("name")), it["score"], e(it["role"] or ""), e(it["profile_token"][:8].upper()), e(", ".join(p.get("skills", []))),
            e(p.get("years", 0)), e((p.get("experience") or "")[:400]), e(langs), e(", ".join(p.get("certifications", [])) or "—"),
            "Ready to relocate within 3 months." if p.get("relocation_ready") else "Relocation timing to be agreed."))
    return layout("Shortlist for " + req["company"], """<section><div class="wrap stack" style="max-width:860px"><span class="eyebrow">Candidate shortlist · confidential</span>
<h1 style="font-size:clamp(1.6rem,4vw,2.4rem)">Shortlist for %s</h1><p class="muted">%s · %s. Candidates agreed to share their CV with verified employers. Contact details are held by MUSA; reply with the candidate references you want to interview and we arrange it, together with your licensed agency, which handles the permit.</p>
<div class="stack">%s</div><p class="muted">Placement fee is payable per candidate hired, as agreed in your service terms. This link is private: please do not forward it.</p></div></section>""" % (
        e(req["company"]), e(req["sector"]), e(req["roles"][:200]), "".join(cards) or '<p class="muted">No candidates have been added yet.</p>'), noindex=True)


def ask_page(question="", result=None, examples=()):
    ans = ""
    if result:
        srcs = "".join('<li><a href="%s" target="_blank" rel="noopener">%s</a> <small class="muted">[%s]</small></li>' % (e(s["url"]), e(s["title"]), e(s.get("entry", ""))) for s in result["sources"])
        ans = """<div class="panel stack" aria-live="polite"><span class="ai-label">%s</span><div class="answer">%s</div>%s
<small class="muted">General information, not legal advice. Sources should be re-checked on the day you act.</small></div>""" % (
            "AI-GENERATED ANSWER (CLAUDE) · GROUNDED IN THE SOURCES BELOW" if result["mode"] == "ai" else "ANSWER FROM MUSA'S SOURCED KNOWLEDGE BASE",
            e(result["answer"]).replace("\n", "<br>"), ('<ul class="sources">%s</ul>' % srcs) if srcs else "")
    ex = "".join('<a class="chip" href="/ask?%s">%s</a>' % (urlencode({"q": q}), e(q)) for q in examples)
    return layout("Ask the concierge", """<section><div class="wrap split">
<form class="stack" method="get" action="/ask"><span class="eyebrow">Concierge</span><h1>Ask about Cyprus work, study and family routes</h1>
<p class="muted">Answers come only from official sources, and each answer lists them. If we have no sourced answer, we say so.</p>
<label for="q">Your question (English or Roman Urdu)</label><textarea id="q" name="q" required maxlength="800" style="min-height:90px">%s</textarea>
<button class="btn primary" type="submit">Ask</button><div class="row">%s</div></form>
<div class="stack">%s</div></div></section>""" % (e(question), ex, ans or '<div class="card"><h3>Not legal advice</h3><p class="muted">For your specific case, order a Verify-Before-You-Pay report or speak to a licensed immigration lawyer.</p></div>'), active="/ask")


def pricing_page(products):
    worker = [p for p in products if p["id"] in ("verify_basic", "verify_deep", "docs_concierge", "cv_eu")]
    biz = [p for p in products if p["id"] in ("oep_trust_badge", "agency_saas", "employer_sourcing", "corridor_intel")]

    def plan(p, featured=False, href="/report"):
        unit = "/month" if p["type"] == "monthly" else ""
        return '<div class="plan%s"><span class="eyebrow">%s</span><h3>%s</h3><div class="price">€%s<small class="muted" style="font-size:.9rem">%s</small></div><p class="muted">%s</p><a class="btn %s" href="%s">%s</a></div>' % (
            " featured" if featured else "", e(p["buyer"]), e(p["name"]), fmt_int(p["price"]), unit, e(p["purpose"]),
            "primary" if featured else "", href, "Get started")
    hrefs = {"verify_basic": "/report", "verify_deep": "/report?product=verify_deep", "docs_concierge": "/report", "cv_eu": "/match",
             "oep_trust_badge": "/business/partners", "agency_saas": "/business/partners", "employer_sourcing": "/business/employers", "corridor_intel": "/business/partners"}
    return layout("Pricing", """<section><div class="wrap stack"><span class="eyebrow">Pricing</span><h1>Clear prices. No placement fees for workers.</h1>
<p class="muted">Workers pay only for checks and documents. Hiring is paid by employers, through licensed agencies.</p>
<h2>For workers and families</h2><div class="plans">%s</div>
<h2 style="margin-top:28px">For businesses</h2><div class="plans">%s</div>
<p class="note">Payments go only to MUSA's registered business accounts. If anyone gives you a personal account and claims it's MUSA, don't pay.</p></div></section>""" % (
        "".join(plan(p, p["id"] == "verify_basic", hrefs[p["id"]]) for p in worker),
        "".join(plan(p, p["id"] == "agency_saas", hrefs[p["id"]]) for p in biz)), active="/pricing", path="/pricing")


def report_page(cfg, product="verify_basic", opp=None, error=None):
    opts = "".join('<option value="%s"%s>%s — Rs %s (€%s), %s</option>' % (k, " selected" if k == product else "", e(p["name"]), fmt_int(p["pkr"]), p["eur"], e(p["delivery"]))
                   for k, p in cfg["products"].items())
    pre = ("Opportunity #%d: %s" % (opp["id"], opp["title"])) if opp else ""
    return layout("Order a verification report", """<section><div class="wrap split">
<form class="stack" method="post" action="/report"><span class="eyebrow">Verify before you pay</span><h1>Order a verification report</h1>
%s<label>Report<select name="product">%s</select></label>
<div class="form-grid"><label>Your name<input name="name" required maxlength="80"></label><label>WhatsApp or email<input name="contact" required maxlength="80"></label></div>
<label>What should we check?<span class="hint">Agent / company name, OEP licence no., BEOE permission no., amount asked, country and job</span><textarea name="details" required maxlength="3000">%s</textarea></label>
%s<button class="btn primary" type="submit">Continue to payment</button></form>
<div class="card stack"><h3>What you get</h3><ul class="muted" style="margin:0;padding-left:18px"><li>OEP licence and BEOE permission checked on beoe.gov.pk</li><li>Employer checked in the company registry</li><li>Every fee labelled official, contractual or unverified</li><li>A written decision: proceed, hold or stop</li></ul>
<p class="muted">We do not sell jobs and take no commission from recruiters on your case.</p></div></div></section>""" % (
        ('<div class="flash err">%s</div>' % e(error)) if error else "", opts, e(pre), consent_box("order")), active="/pricing")


def order_page(o, cfg, methods, flash=None):
    p = cfg["products"].get(o["product"], {})
    rows = []
    for m in methods:
        if m["type"] == "link":
            url = m["urls"][o["product"]] + ("&" if "?" in m["urls"][o["product"]] else "?") + urlencode({m.get("reference_param", "client_reference_id"): o["ref"]})
            rows.append('<div class="card row" style="justify-content:space-between"><b>%s</b><a class="btn primary" href="%s" target="_blank" rel="noopener">Pay €%s by card</a></div>' % (e(m["label"]), e(url), e(p.get("eur"))))
        elif m["type"] == "wallet":
            rows.append('<div class="card"><b>%s</b><p class="mono" style="margin:6px 0 0">%s · %s</p></div>' % (e(m["label"]), e(m["account"]), e(m["account_title"])))
        else:
            rows.append('<div class="card"><b>%s</b><p class="mono" style="margin:6px 0 0">%s</p></div>' % (e(m["label"]), e(" · ".join(x for x in [m.get("bank"), m.get("iban"), ("Raast " + m["raast_id"]) if m.get("raast_id") else "", m.get("account_title")] if x))))
    status = {"requested": "Waiting for payment", "claimed": "Payment reported — we are confirming it", "paid": "Paid — your report is in progress",
              "delivered": "Delivered", "cancelled": "Cancelled"}.get(o["status"], o["status"])
    pay = ""
    if o["status"] == "requested":
        pay = """<h2>Pay Rs %s</h2>%s<p class="note">Write the reference <b class="mono">%s</b> in the payment note. We only take payment into the business accounts above.</p>
<form method="post" action="/order/%s/paid" class="row"><button class="btn" type="submit">I have paid</button><small class="muted">We confirm every payment manually before starting.</small></form>""" % (
            fmt_int(o["amount_pkr"]), "".join(rows) or '<div class="card"><p class="muted" style="margin:0">Payment details will be sent to you on WhatsApp or email within 24 hours.</p></div>', e(o["ref"]), e(o["ref"]))
    return layout("Order " + o["ref"], """<section><div class="wrap stack" style="max-width:760px">
<span class="eyebrow">Order</span><h1 class="mono" style="font-size:clamp(1.4rem,4vw,2rem)">%s</h1>
<div class="row"><span class="chip">%s</span><span class="chip">%s</span></div>
<p class="muted">Keep this page's link to check your order status.</p>%s</div></section>""" % (e(o["ref"]), e(p.get("name", o["product"])), e(status), pay), flash=flash, noindex=True)


def business_page(products):
    by = {p["id"]: p for p in products}
    return layout("For business", """<section class="hero"><div class="wrap split">
<div class="stack"><span class="eyebrow">For employers, agencies, OEPs and universities</span><h1>The trust layer for Pakistan → Cyprus hiring</h1>
<p class="lede">Cyprus employers need workers who arrive. Families need recruiters they can trust. MUSA verifies both sides and keeps the evidence.</p>
<div class="row"><a class="btn primary" href="/business/employers">Request candidates</a><a class="btn" href="/business/partners">Apply as a partner</a></div></div>
<div class="panel stack"><span class="eyebrow">Why partners join</span><ul style="margin:0;padding-left:18px">
<li>Families check offers on MUSA before paying. Verified partners show up as verified.</li><li>Candidates arrive with identity, documents and experience checked at source.</li>
<li>Case engine, cost ledger and payment firewall for your own team.</li><li>Every badge can be revoked. That is why it carries weight.</li></ul></div></div></section>
<section class="tight"><div class="wrap plans">
<div class="plan"><span class="eyebrow">Licensed OEPs</span><h3>Verified Recruiter badge</h3><div class="price">€%s<small class="muted" style="font-size:.9rem">/month</small></div><p class="muted">Licence and live BEOE permissions shown as verified in Scam Shield and on your public badge page.</p><a class="btn" href="/business/partners">Apply</a></div>
<div class="plan featured"><span class="eyebrow">Consultancies</span><h3>Partner Platform Pro</h3><div class="price">€%s<small class="muted" style="font-size:.9rem">/month</small></div><p class="muted">White-label Sentinel: case engine, risk scoring, cost ledger and branded reports for your team.</p><a class="btn primary" href="/business/partners">Apply</a></div>
<div class="plan"><span class="eyebrow">Cyprus employers</span><h3>Verified shortlists</h3><div class="price">€%s<small class="muted" style="font-size:.9rem">/candidate</small></div><p class="muted">Pre-verified candidates for construction, hospitality, logistics, agriculture and care, through a licensed Cyprus agency.</p><a class="btn" href="/business/employers">Request</a></div>
<div class="plan"><span class="eyebrow">Universities</span><h3>Student pipeline</h3><div class="price">Commission</div><p class="muted">Admission-ready, document-verified applicants under a signed agent agreement. Accredited institutions only (CYQAA).</p><a class="btn" href="/business/partners">Talk to us</a></div>
</div></section>
<section><div class="wrap card stack"><h2>What we will not do</h2><p class="muted">Recruit without the required licences, charge workers placement fees, hide who receives a payment, or let a partner keep a badge after verified complaints. Partners are checked (KYB) before activation and monitored afterwards.</p></div></section>""" % (
        fmt_int(by["oep_trust_badge"]["price"]), fmt_int(by["agency_saas"]["price"]), fmt_int(by["employer_sourcing"]["price"])), active="", path="/business", description="Verified candidates, recruiter badges and case tooling for employers, agencies and universities in the Pakistan–Cyprus corridor.")


def partner_apply_page(error=None):
    return layout("Become a verified partner", """<section><div class="wrap split">
<form class="stack" method="post" action="/business/partners"><span class="eyebrow">Partner application · KYB</span><h1>Become a verified partner</h1>
%s<div class="form-grid"><label>Organisation name<input name="org_name" required maxlength="120"></label>
<label>Type<select name="org_type" required><option value="oep">Pakistan OEP (BEOE licensed)</option><option value="cy_agency">Cyprus employment agency</option><option value="consultancy">Education / visa consultancy</option><option value="university">University / college</option><option value="law_firm">Law firm</option><option value="employer">Employer</option></select></label>
<label>Country<input name="country" required maxlength="40"></label><label>Licence number<span class="hint">BEOE OEP licence or Cyprus Department of Labour licence</span><input name="licence_no" maxlength="60"></label>
<label>Company registration no.<input name="registry_no" maxlength="60"></label><label>Website<input name="website" maxlength="120" placeholder="https://"></label>
<label>Contact name<input name="contact_name" required maxlength="80"></label><label>Business email<input name="email" type="email" required maxlength="120"></label>
<label>Phone<input name="phone" maxlength="40"></label><label>Plan<select name="tier"><option value="badge">Verified Recruiter badge</option><option value="pro">Partner Platform Pro</option><option value="custom">Enterprise / custom</option></select></label></div>
<label>Anything we should know?<textarea name="message" maxlength="2000"></textarea></label>
%s<button class="btn primary" type="submit">Submit application</button></form>
<div class="card stack"><h3>How verification works</h3><ol class="muted" style="margin:0;padding-left:18px"><li>We check your licence on the official register.</li><li>We check your company registration and official contact details.</li><li>A short video call with the owner.</li><li>Your badge page goes live; it lists exactly what was verified and when.</li></ol>
<p class="muted">Typical time: 5–10 working days. Accounts are bound to the verified owner and cannot be transferred.</p></div></div></section>""" % (
        ('<div class="flash err">%s</div>' % e(error)) if error else "", consent_box("partner")))


def employer_page(error=None):
    return layout("Request candidates", """<section><div class="wrap split">
<form class="stack" method="post" action="/business/employers"><span class="eyebrow">For employers in Cyprus</span><h1>Request verified candidates</h1>
%s<div class="form-grid"><label>Company<input name="company" required maxlength="120"></label><label>Country<input name="country" value="Cyprus" maxlength="40"></label>
<label>Sector<select name="sector"><option>Construction</option><option>Hospitality</option><option>Logistics</option><option>Agriculture</option><option>Manufacturing</option><option>Cleaning</option><option>Care</option><option>Other</option></select></label>
<label>Number of workers<input name="headcount" type="number" min="1" max="500" value="5"></label></div>
<label>Roles and requirements<textarea name="roles" required maxlength="2000" placeholder="e.g. 4 masons (3+ years), 2 steel fixers; English A2; start in March"></textarea></label>
<div class="form-grid"><label>Contact name<input name="contact_name" required maxlength="80"></label><label>Email<input name="email" type="email" required maxlength="120"></label><label>Phone<input name="phone" maxlength="40"></label></div>
<label>Notes<textarea name="message" maxlength="2000"></textarea></label>
%s<button class="btn primary" type="submit">Send request</button></form>
<div class="card stack"><h3>How hiring works</h3><p class="muted">The labour-market test and permit application stay with you and your licensed Cyprus agency. MUSA supplies candidates whose identity, documents and experience are verified, and who were recruited through BEOE-licensed OEPs on the Pakistan side. Workers pay no placement fees.</p></div></div></section>""" % (
        ('<div class="flash err">%s</div>' % e(error)) if error else "", consent_box("employer")))


def partner_badge(p):
    return layout(p["org_name"] + " — verified partner", """<section><div class="wrap stack" style="max-width:760px">
<span class="stamp green">Verified partner</span><h1>%s</h1><div class="card"><dl style="margin:0;display:grid;grid-template-columns:max-content 1fr;gap:8px 16px">
<dt class="muted">Type</dt><dd style="margin:0">%s</dd><dt class="muted">Country</dt><dd style="margin:0">%s</dd><dt class="muted">Licence</dt><dd style="margin:0" class="mono">%s</dd>
<dt class="muted">Website</dt><dd style="margin:0">%s</dd><dt class="muted">Verified on</dt><dd style="margin:0" class="mono">%s</dd></dl></div>
<p class="muted">MUSA checked this organisation's licence and registration on the date shown. Partners pay a subscription; verification standards are the same for every partner and badges are revoked after verified complaints. A badge does not guarantee any specific job or visa. Always check each offer's BEOE permission and contract. Report a problem: <a href="/ask">contact us</a>.</p></div></section>""" % (
        e(p["org_name"]), e(p["org_type"]), e(p["country"]), e(p["licence_no"] or "—"), e(p["website"] or "—"), e((p["decided_at"] or "")[:10])))


def partner_billing_page(p, plan, cfg, flash=None):
    status = {"unpaid": "Waiting for payment", "claimed": "Payment reported — we are confirming it", "active": "Active",
              "lapsed": "Lapsed — renew to restore your badge", "none": "Not yet approved"}.get(p["billing_status"] or "none", p["billing_status"])
    rows = []
    if plan.get("stripe_link"):
        url = plan["stripe_link"] + ("&" if "?" in plan["stripe_link"] else "?") + urlencode({"client_reference_id": p["billing_ref"]})
        rows.append('<div class="card row" style="justify-content:space-between"><b>Card (monthly, cancel any time)</b><a class="btn primary" href="%s" target="_blank" rel="noopener">Subscribe €%s/%s</a></div>' % (e(url), e(plan["eur"]), e(plan["interval"])))
    for m in cfg.get("methods", []):
        if m["type"] == "bank" and m.get("account_title") and (m.get("iban") or m.get("raast_id")):
            rows.append('<div class="card"><b>%s</b><p class="mono" style="margin:6px 0 0">%s</p></div>' % (e(m["label"]), e(" · ".join(x for x in [m.get("bank"), m.get("iban"), ("Raast " + m["raast_id"]) if m.get("raast_id") else "", m["account_title"]] if x))))
    pay = ""
    if p["status"] == "approved" and p["billing_status"] in ("unpaid", "lapsed"):
        pay = """<h2>Activate your badge</h2>%s<p class="note">For bank transfers, write <b class="mono">%s</b> in the payment note.</p>
<form method="post" action="/partner/billing/%s/paid" class="row"><button class="btn" type="submit">I have paid by bank transfer</button></form>""" % (
            "".join(rows) or '<div class="card"><p class="muted" style="margin:0">We will email you payment details within one working day.</p></div>', e(p["billing_ref"]), e(p["billing_ref"]))
    live = ('<p>Your public badge page: <a href="/partners/%s">/partners/%s</a></p>' % (e(p["slug"]), e(p["slug"]))) if p["billing_status"] == "active" and p["slug"] else ""
    return layout("Partner billing", """<section><div class="wrap stack" style="max-width:760px"><span class="eyebrow">Partner billing</span>
<h1 style="font-size:clamp(1.6rem,4vw,2.4rem)">%s</h1><div class="row"><span class="chip">%s · €%s/%s</span><span class="chip%s">%s</span></div>%s%s
<p class="muted">Every partner passes the same verification checks, whatever they pay. A badge is revoked after verified complaints, even on a paid plan.</p></div></section>""" % (
        e(p["org_name"]), e(plan["name"]), e(plan["eur"]), e(plan["interval"]), " ok" if p["billing_status"] == "active" else "", e(status), live, pay), flash=flash, noindex=True)


def agents_page(registry):
    rows = "".join("<tr><td><b>%s</b></td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (e(a["name"]), e(a["kind"]), e(a["job"]), e(a["human"]), e(a["data"])) for a in registry)
    return layout("AI & automation transparency", """<section><div class="wrap stack"><span class="eyebrow">EU AI Act · transparency</span><h1>Our agents, and what a person must approve</h1>
<p class="muted">MUSA uses rules, automation and one AI model (Claude, by Anthropic) to help people make decisions. No agent makes a final decision about a person, a payment or a visa. Answers written by AI are labelled as AI-generated wherever they appear.</p>
<div class="table-wrap"><table><thead><tr><th>Agent</th><th>Type</th><th>What it does</th><th>Human oversight</th><th>Data</th></tr></thead><tbody>%s</tbody></table></div>
<p class="muted">Candidate matching is treated as high-risk under Annex III of the EU AI Act. Scores are explained (skills, experience, language, certificates) and never used on their own to accept or reject anyone.</p></div></section>""" % rows)


def privacy_page():
    r = RETENTION_DAYS
    return layout("Privacy notice", """<section><div class="wrap stack" style="max-width:820px"><span class="eyebrow">GDPR</span><h1>Privacy notice</h1>
<p>MUSA Corridor collects only what each service needs, and tells you how long it keeps it.</p>
<div class="table-wrap"><table><thead><tr><th>What</th><th>Why (legal basis)</th><th>Kept for</th></tr></thead><tbody>
<tr><td>Scam Shield text</td><td>Answer your scan (legitimate interest)</td><td>Not stored. Only the risk band and pattern IDs are counted.</td></tr>
<tr><td>Concierge questions</td><td>Answer your question</td><td>Not stored by MUSA. Sent to Anthropic to generate AI answers when AI mode is on.</td></tr>
<tr><td>Report orders</td><td>Contract (Art. 6(1)(b)); accounting law</td><td>%d years</td></tr>
<tr><td>CV / match profiles</td><td>Consent (Art. 6(1)(a)); withdraw any time</td><td>%d months, or until you delete it</td></tr>
<tr><td>Employer requests</td><td>Pre-contract steps (Art. 6(1)(b))</td><td>%d months</td></tr>
<tr><td>Partner applications</td><td>Pre-contract steps; verification (KYB)</td><td>While the partnership lasts</td></tr>
<tr><td>WhatsApp leads</td><td>Answer your request</td><td>WhatsApp number, dates and pattern IDs, never message text</td></tr>
</tbody></table></div>
<h2>Your rights</h2><p>You can ask for a copy of your data, ask us to correct or delete it, object to processing, or withdraw consent. <a href="/privacy/request">Make a request</a>. We reply within one month. You can also complain to your data protection authority (in Cyprus, the Commissioner for Personal Data Protection).</p>
<h2>Processors</h2><p>Hosting provider (EU region recommended), Anthropic (AI answers, only when AI mode is on), Meta WhatsApp Business (if you message us there), and payment providers (Stripe, JazzCash, Easypaisa, banks) for payments you make.</p>
<h2>Cookies</h2><p>We use no tracking or advertising cookies. The site works without any cookies; the admin area uses your browser's built-in login.</p></div></section>""" % (
        r["orders"] // 365, r["profiles"] // 30, r["employer_requests"] // 30))


def terms_page():
    return layout("Terms", """<section><div class="wrap stack" style="max-width:820px"><h1>Terms of service</h1>
<p>MUSA provides verification, information and document-preparation services. We do not provide legal advice, recruit workers, issue visas or guarantee any outcome. Decisions on permits and visas are made only by the competent authorities.</p>
<p>A verification report states what we could confirm from official sources on the date of the report. It does not certify that an offer is genuine or that a visa will be granted.</p>
<p>We never ask for payment into a personal account. We never create, alter or "arrange" documents. Requests to do so end the service.</p>
<p>Partners must hold every licence their activity requires, must not charge workers unlawful fees, and may lose their badge after verified complaints.</p></div></section>""")


def privacy_request_page(done=False):
    return layout("Your data rights", """<section><div class="wrap split"><form class="stack" method="post" action="/privacy/request"><span class="eyebrow">GDPR rights</span><h1>Request your data, or ask us to delete it</h1>
%s<label>The email or WhatsApp number you used<input name="contact" required maxlength="120"></label>
<label>Request<select name="kind"><option value="export">Send me a copy of my data</option><option value="erase">Delete my data</option></select></label>
<button class="btn primary" type="submit">Send request</button><small class="muted">We will contact you at that address to confirm it is you before acting. Answer within one month.</small></form>
<div class="card"><h3>Faster options</h3><p class="muted">CV profiles can be deleted instantly from your private CV link. On WhatsApp, send STOP to stop all messages.</p></div></div></section>""" % (
        '<div class="flash">Request received. We will contact you to confirm your identity, then act within one month.</div>' if done else ""))


def not_found():
    return layout("Not found", '<section><div class="wrap stack"><h1>Page not found</h1><p><a href="/">Go to the home page</a></p></div></section>')
