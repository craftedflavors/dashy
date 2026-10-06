"""Roman Urdu pages (/ur, /ur/check): the B2C front door in the language most users search and chat in."""
from .ui import e, fmt_int, layout, opp_card, wa_link, whatsapp_number

LANG = "ur-Latn"


def _wa_button(text, label="WhatsApp par poochein"):
    link = wa_link(text)
    return ('<a class="btn" href="%s" target="_blank" rel="noopener">%s</a>' % (e(link), e(label))) if whatsapp_number() else ""


def home(stats, latest):
    cards = "".join(opp_card(o) for o in latest)
    return layout("Agent ko paisa dene se pehle offer check karein", """
<section class="hero"><div class="wrap split">
 <div class="stack" style="gap:20px">
  <div class="row" style="justify-content:space-between"><span class="eyebrow">Pakistan → Cyprus · kaam · parhai · hiring</span><a class="chip" href="/" hreflang="en">English</a></div>
  <h1>Agent ko paisa dene se pehle offer check karein.</h1>
  <p class="lede">MUSA job aur visa offers ko official records se check karta hai, batata hai kaunsi fees asli hain, aur verified workers ko licensed agencies aur Cyprus ke employers se milata hai.</p>
  <div class="row"><a class="btn primary" href="/ur/check">Agent ka message check karein</a><a class="btn" href="/opportunities">Live opportunities</a></div>
  <div class="row"><span class="chip ok">GDPR ke mutabiq</span><span class="chip">Har faisla insaan karta hai</span></div>
 </div>
 <form class="panel stack" method="post" action="/ur/check"><span class="eyebrow">Scam Shield · muft</span>
  <label for="ur-hero">Agent ka WhatsApp message ya offer yahan paste karein<span class="hint">20 ma'loom dhokon se check hota hai. Aap ka message save nahi hota.</span></label>
  <textarea id="ur-hero" name="text" required placeholder="Maslan: Cyprus visa 100%% guarantee. Aaj hi 2 lakh mere account mein bhejo, contract baad mein."></textarea>
  <button class="btn copper" type="submit">Dhoke ke nishan check karein</button></form>
</div>
<div class="wrap" style="margin-top:28px"><div class="mrz">P&lt;PAK&lt;&lt;CYP&lt;&lt;OPPORTUNITIES&lt;<b>%s</b>&lt;&lt;VISA&lt;<b>%s</b>&lt;&lt;SCANS&lt;7D&lt;<b>%s</b>&lt;&lt;&lt;</div></div></section>
<section class="tight"><div class="wrap grid">
 <div class="card"><span class="eyebrow">Workers ke liye</span><h3>Jaali offer se paisa na doobne dein</h3><p>Muft scam scan, Rs 4,500 mein Verify-Before-You-Pay report, aur EU format CV.</p><a href="/report">Report mangwayein →</a></div>
 <div class="card"><span class="eyebrow">Students aur families</span><h3>Sawal poochein, jawab source ke saath</h3><p>Hum sirf official sources se jawab dete hain aur source dikhate hain.</p><a href="/ask">Sawal poochein →</a></div>
 <div class="card"><span class="eyebrow">Guides</span><h3>Pehle parhein, phir paisa dein</h3><p>Cyprus work visa ka asal tareeqa, OEP licence kaise check karein, aur dhokon ki list.</p><a href="/guides">Guides →</a></div>
</div></section>
<section><div class="wrap stack"><span class="eyebrow">Paisa dene se pehle 5 usool</span><h2>Yeh 5 baatein aap ka paisa bachati hain</h2>
<div class="steps">
 <div><h3>Licence number lein</h3><p class="muted">OEP licence aur BEOE permission number lein aur khud beoe.gov.pk par check karein.</p></div>
 <div><h3>Pehle contract</h3><p class="muted">Pehle likha hua contract, phir payment. Kabhi ulta nahi.</p></div>
 <div><h3>Company ko payment</h3><p class="muted">Zaati account ya Easypaisa/JazzCash par kabhi nahi. Har dafa raseed lein.</p></div>
 <div><h3>Visa guarantee nahi</h3><p class="muted">Visa ka faisla sirf immigration authority karti hai. Koi guarantee nahi de sakta.</p></div>
</div></div></section>
<section class="tight"><div class="wrap stack"><h2>Taaza opportunities</h2><p class="muted">Har listing par likha hai ke kahan se aayi aur kitni bharosemand hai. Lead ka matlab verified job nahi.</p><div class="opps">%s</div></div></section>
""" % (fmt_int(stats["opps"]), fmt_int(stats["visa"]), fmt_int(stats["scans_7d"]), cards), active="/", path="/ur", lang=LANG,
                  description="Cyprus ya Europe job ke liye agent ko paisa dene se pehle offer muft check karein. Roman Urdu mein.")


def check(text="", result=None):
    res = ""
    if result:
        d, hits = result["decision"], result["hits"]
        if d["colour"] == "RED":
            stamp, msg = '<span class="stamp red">Ruk jayein — payment na karein</span>', "Khatarnak nishan mile hain. Offer verify hone tak kisi ko paisa na dein."
        elif hits:
            stamp, msg = '<span class="stamp amber">Ruk kar verify karein</span>', "Warning signs mile hain. Payment se pehle verify karein."
        else:
            stamp, msg = '<span class="stamp amber">Koi ma\'loom pattern nahi</span>', "Koi ma'loom dhoka pattern nahi mila. Is ka matlab yeh nahi ke offer asli hai — abhi kuch verify nahi hua."
        items = "".join('<div class="hit"><div class="row"><span class="sev %s">%s</span><b>%s</b></div><q>…%s…</q><div>%s</div></div>' % (
            e(h["severity"]), e(h["severity"]), e(h["name"]), e(h["evidence"]), e(h.get("response_ur") or h["response"])) for h in hits)
        wa = _wa_button("Assalam o alaikum, Scam Shield ne %d warning signs dikhaye: %s. Mujhe report chahiye." % (len(hits), ", ".join(h["id"] for h in hits)), "WhatsApp par report mangwayein")
        res = """<div class="panel result" aria-live="polite">%s<p>%s</p>
<div><div class="meter"><i style="width:%d%%"></i></div><small class="muted">Risk %d/100 · %d warning signs</small></div>%s
<div class="note">Payment se pehle official records se check karwana hai? <a href="/report">Verify-Before-You-Pay report (Rs 4,500)</a></div><div class="row">%s</div></div>""" % (
            stamp, e(msg), min(100, d["risk"]["score"]), d["risk"]["score"], len(hits), items, wa)
    return layout("Scam Shield — kya yeh offer dhoka hai?", """<section><div class="wrap split">
<form class="stack" method="post" action="/ur/check"><div class="row" style="justify-content:space-between"><span class="eyebrow">Scam Shield</span><a class="chip" href="/check" hreflang="en">English</a></div>
<h1>Kya yeh offer dhoka hai?</h1><p class="muted">Agent ne jo bheja hai woh yahan paste karein: WhatsApp message, ad ya offer letter. Hum 20 asal case patterns se check karte hain. Aap ka message save nahi hota.</p>
<label for="ur-text">Agent ka message</label><textarea id="ur-text" name="text" required>%s</textarea>
<button class="btn copper" type="submit">Dhoke ke nishan check karein</button></form>
<div class="stack">%s</div></div></section>""" % (e(text), res), active="/check", path="/ur/check", lang=LANG,
                  description="Agent ka WhatsApp message paste karein aur muft dekhein ke us mein dhoke ke nishan hain ya nahi.")
