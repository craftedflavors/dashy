# MUSA — Verify-First Recruitment Intelligence (Pakistan → Cyprus corridor)

> The agent is not paid to make anyone believe an opportunity is genuine.
> It is paid to determine whether the evidence supports proceeding.

MUSA turns the Cyprus job-hunt research into a business. Instead of selling visas, which needs licences you
don't have yet, it sells **certainty**. Workers and families pay to have an offer checked before they pay an agent. Licensed
recruiters pay to be shown as verified. Employers and universities pay, through licensed partners, for candidates who have
already been checked. Every case also feeds a reputation graph, and that graph becomes a data asset that competitors can't copy.

```
DISCOVER → VERIFY → PRICE → CROSS-CHECK → CONTACT → NEGOTIATE → DOCUMENT → ESCALATE → APPROVE → MONITOR
```

---

## What's in the box

| Piece | Where | What it does |
|---|---|---|
| **Scam Shield** (public lead magnet) | `public/musa/index.html` | Mobile-first page in English and Roman Urdu. A worker pastes a recruiter's message and gets a STOP/HOLD verdict, the red flags it found, and a WhatsApp button to buy a report. Runs fully in the browser, so nothing the worker pastes is uploaded. Dashy serves it at `/musa/`. |
| **Trap library** | `data/traps.json` | 20 scam patterns (guaranteed visa, appointment fee, personal account, tourist-visa switch, fake documents, urgency…). Each has English and Roman Urdu regexes and a suggested neutral reply. The engine and the web page both read from this one file. |
| **Risk engine** | `musa_sentinel/risk.py` | Point-based risk score (§46), hard stops (§47) and the GREEN / AMBER / RED / BLACK decision (§61). It can never return GREEN while anything is still unverified, and only a human can mark a case BLACK. |
| **Cost ledger** | `musa_sentinel/costs.py` | Splits each quote into categories A–F. Money that isn't verified never counts toward the verified total. A fee labelled "official" with no source is downgraded to a claim. Also flags when agents quoting the same job give conflicting fees. |
| **Payment Firewall** | `musa_sentinel/firewall.py` | Returns PAY, HOLD or ESCALATE. It checks the six "who / why / which agreement" questions, the beneficiary, the payment class (P0–P6), the fees, the case evidence and the reputation graph. **Every outcome still needs a human to approve.** |
| **Reputation Graph** | `musa_sentinel/graph.py` | Spots the same phone, bank account (stored only as a hash), email domain or address showing up under different company names. Also spots contract templates reused across "different" employers. It reports *potential* reuse and never accuses anyone. |
| **Case state machine** | `musa_sentinel/case.py` | Runs a case from LEAD to CASE_CLOSED. A case can't move to the next stage until that stage's check is done. Payment, submission and travel need a named human approver. Evidence from WhatsApp or Facebook (tier 5) can never count as verified. |
| **Lead pipeline** | `musa_sentinel/leads.py`, `data/contacts.json` | All 21 contacts from your research, each labelled with how trustworthy its source is and its current status. Every one is **UNVERIFIED** for now. Produces a ranked outreach queue with the next step for each contact. Replaces the broken scoring in `cyprus_job_hunter.py`. |
| **Skills matching** | `musa_sentinel/matching.py` | Matches a candidate to a job by skills, experience, language level (CEFR), certifications and readiness to relocate, and explains the score. If the candidate has no lawful visa route, the score is 0. |
| **Outreach templates** | `musa_sentinel/outreach.py` | Due-diligence messages to OEPs, employers and embassies (§23–25), plus sales pitches to Cyprus agencies, OEPs and lawyers, and a Roman Urdu offer for workers. |
| **Revenue forecaster** | `musa_sentinel/revenue.py`, `data/pricing.json` | Projects 12 months of revenue under conservative, base and aggressive assumptions, product by product. |
| **Leads page + admin** | `musa_sentinel/leadlog.py`, `user-data/musa-leads.yml` (generated) | A Dashy "MUSA Leads" page with report requests waiting, warm leads, scans, conversion rate, opt-outs, a follow-up queue and the top scam patterns of the week (your next reel topics). **It is public-safe on purpose:** Dashy publishes everything in `user-data/` as plain files, so numbers are masked to the last 4 digits. Full numbers, one-tap WhatsApp follow-up links and a **Done** button live only in the bot's `/admin/leads`, behind a password. |
| **Command Centre** | `user-data/musa.yml` (generated) | A Dashy page with the revenue engine, official sources, partners ranked by score, and job channels. |
| **WhatsApp bot** | `musa_sentinel/whatsapp.py` | A webhook for the Meta WhatsApp Cloud API. Workers forward an agent's message and get the scam check in English or Roman Urdu. Commands: PRICE, REPORT (sends your payment link), HELP, URDU/ENGLISH, STOP. Every webhook's signature is verified, Meta's duplicate deliveries are ignored, each sender is limited to 10 scans an hour, and opt-outs survive a restart. Each scan is logged as a lead in `data/leads.jsonl`, **without the message text**. |
| **Cyprus adapter** | `data/country_adapters/cyprus.json` | Records which authority decides what for each route. Fees and processing times are left **blank on purpose**: read them from the official source and record the date you checked. |

## Run it

Needs Python 3.9 or later. It uses only the standard library, so it works the same on Windows (`C:\MUSA`) and Linux.

```bash
cd musa
python -m musa_sentinel scan "Visa 100% guarantee. Pay today to my personal account."
python -m musa_sentinel firewall samples/payment_request.json --graph samples/entities.json
python -m musa_sentinel graph samples/entities.json
python -m musa_sentinel leads                       # who to contact today, and how
python -m musa_sentinel match samples/candidate.json samples/jobs.json
python -m musa_sentinel forecast --scenario conservative
python -m musa_sentinel draft                       # list templates
python -m musa_sentinel draft partner_cy_agency contact="HR Team" company="MUSA" sender="Musa" phone="+92..."
python -m musa_sentinel whatsapp-sim "Visa 100% guarantee, pay today" --lang ur   # bot reply, offline
python -m musa_sentinel leads-page --leads samples/leads.jsonl   # preview the leads page with demo data
python -m musa_sentinel build                       # regenerate Scam Shield data + Dashy page after editing data/*.json
python -m unittest discover -s tests                # 57 tests
```

Add `--json` before the subcommand to get machine-readable output for n8n, Make or Zapier, e.g. `python -m musa_sentinel --json scan ...`.

**Before launch:** put your WhatsApp Business number in `CONFIG.whatsapp` at the bottom of `public/musa/index.html`.

## Going live on WhatsApp (about 1 hour)

1. **Meta app:** at developers.facebook.com, create an app of type *Business*, add the **WhatsApp** product, and add and verify your business phone number.
   Create a **system user** in Business Settings and generate a permanent token with `whatsapp_business_messaging`. Note the
   **Phone number ID** and the **App secret** (App settings → Basic).
2. **Configure:** `cp .env.example .env` and fill in the values. Set `MUSA_PAYMENT_LINK` to your JazzCash, Easypaisa-merchant or Stripe link.
3. **Run it on an HTTPS host.** Meta only calls HTTPS webhooks. Pick one:
   - `docker build -t musa-whatsapp . && docker run -d -p 8088:8088 --env-file .env -v musa-data:/app/data musa-whatsapp`
     behind Caddy or nginx on a small Hetzner VPS (Caddy gives you HTTPS automatically).
   - Or on any Python host: `python -m musa_sentinel whatsapp-serve`.
   - To test from your laptop, `cloudflared tunnel --url http://localhost:8088` gives a temporary HTTPS URL.
4. **Webhook:** in Meta → WhatsApp → Configuration, set the callback to `https://<your-host>/webhook`, set the verify token to `WA_VERIFY_TOKEN`,
   and subscribe to the **messages** field.
5. **Test:** send "Hi" to your number, then forward a scam-looking offer.
6. **Admin view:** set `MUSA_ADMIN_PASSWORD`, then open `https://<your-host>/admin/leads` and log in as user `admin`. You get the follow-up queue with full numbers,
   a **WhatsApp** button that pre-fills the right follow-up message, and **Done** to clear a lead. A new REPORT request from the same person puts them back in the queue.
7. **Leads page in Dashy:** on the bot server, run
   `MUSA_ADMIN_URL=https://<your-host>/admin/leads python -m musa_sentinel leads-page` (cron it every 15 min if Dashy runs there too).
   It writes `user-data/musa-leads.yml` with masked numbers only. The copy in git is the empty state, so the public Netlify site never shows real leads.
8. **Daily routine:** clear every 🔥 hot lead the same day. Nudge warm leads with the REPORT offer, but only inside 24 hours of their last message. Turn the "Top scam patterns" list into that week's Urdu reels.

Notes:
- The bot only replies to people who message first, which keeps it inside WhatsApp's free 24-hour service window. Promotional messages *you* start
  need Meta-approved templates and opt-in. Don't broadcast to the lead log.
- The bot keeps language choice and duplicate tracking in memory, so a restart resets language to English. Opt-outs are rebuilt from the
  lead log on startup.
- Keep the lead log private and delete old entries regularly; it contains WhatsApp numbers.

---

## The money map

Products are ordered by **how quickly they bring in cash**, not by how big they could get. Prices are starting guesses to test,
and you can change them in `data/pricing.json`.

### Micro-offers: cash in week 1, no licence, no partners needed
1. **Verify-Before-You-Pay Report, €15 (~Rs 4,500).** Workers are already scared of Cyprus visa scams, and the Facebook
   groups you found ("Cyprus Visa & Jobs Update 2026 | Pakistanis Ke Liye") are full of them. Scam Shield is the free hook,
   the WhatsApp button closes the sale, and the work takes about 30 minutes per report using the OEP, BEOE and registry checks.
2. **Deep Due-Diligence File, €79.** For families about to pay €3,000–€6,000. Adds direct confirmation from the employer, a
   check of the work-permit reference, a contract review and a Payment Firewall decision. Easy to sell: 2% of what they're at risk of losing.
3. **EU-format CV + Match Profile, €10.** Cheap to deliver. **Every one adds a candidate to your talent pool**, and that pool is what licensed agencies pay for later.
4. **Document & Attestation Concierge, €45.** Guidance on HEC, IBCC and MOFA attestation, plus translation coordination. Genuine documents only.

### Recurring revenue: months 1–6
5. **Verified Recruiter badge, €99/month.** BEOE-licensed OEPs pay to appear as VERIFIED when families scan their offers.
   The badge can be taken away, which is why families trust it. This is how the free tool earns from the recruiter side.
6. **Corridor Intelligence brief, €29/month.** A monthly brief for OEPs, agencies and lawyers: demand by sector, employer hiring
   signals, fee benchmarks, and fraud patterns from the graph.
7. **Partner Platform Pro, €499/month.** The Meridian MPP Tier 1 offer: white-label Sentinel for consultancies, with the case engine,
   risk scoring and branded reports. The tier structure and the 7 anti-abuse layers (KYB, applicant identity checks,
   checking documents with whoever issued them, behaviour scoring, watermarking, usage caps and bonds, and verification by the
   receiving Cyprus side) are in the uploaded blueprint. Build them onto this engine in that order.

### Large-ticket deals: months 3+, via licensed partners only
8. **Employer Sourcing Fee, ~€400 per shortlisted candidate.** Cyprus employers in construction, hospitality, logistics and agriculture
   pay for **verified** candidates. The contract runs through a Cyprus agency licensed by the Department of Labour and a BEOE-licensed OEP.
   MUSA earns a written referral or technology share, and the worker pays MUSA nothing.
9. **University placement commission, often 10–20% of first-year tuition.** The student corridor from the Meridian
   blueprint. It's legal and paid by the institution, but needs a signed agent agreement with each institution. Check that the institution is CYQAA-accredited.

### Forecast (`python -m musa_sentinel forecast`)

| Scenario | 12-month revenue | MRR in month 12 |
|---|---|---|
| Conservative | ~€80k | ~€4.4k |
| Base | ~€160k | ~€8.7k |
| Aggressive | ~€288k | ~€15.7k |

The model counts tooling costs only (about €365/month), **not your time**. It also assumes the first employer-sourcing and student deals
close in months 3–4. Treat these numbers as a planning tool, not a promise. Replace each assumption with real conversion data as soon as you have it.

---

## Legal guardrails (built into the design; confirm with counsel)

- **Pakistan:** recruiting for overseas jobs requires a BEOE **OEP licence** (Emigration Ordinance 1979).
  Until you hold one, MUSA must **not** recruit, place or collect placement fees from workers. Verification, advice, CVs and
  document guidance are separate services. Keep them separate in your invoices and your wording too.
- **Cyprus:** private employment agencies need a **Department of Labour licence**. Placement income comes only through
  licensed agencies and only from employers.
- **Northern Cyprus** is outside the Republic of Cyprus / EU immigration system. Never merge those cases (TRAP-018 and the adapter both cover this).
- **Data protection:** GDPR applies on the Cyprus side and PECA/PDPB on the Pakistan side. Scam Shield runs in the browser by design. Bank numbers are stored only as hashes. Get consent before storing anything about a candidate.
- **Defamation:** the graph and Scam Shield only describe *warning signs* and *potential reuse*. Never publish a "scammer list".
  Recording a BLACK verdict needs a human.
- **AI Act:** candidate matching is "high-risk" under Annex III of the EU AI Act once it's used to decide who gets hired.
  Keep scores explainable (they are), keep a human in the loop, and log every decision.

## About the BEOE link you shared

`beoe.gov.pk/foreign-jobs/4667359/5207835` is **70 Agricultural Workers → Portugal** (€920/month, R.B.S. Brothers OEP),
not Cyprus. Permissions #4349941 and #858327 appeared as "Cyprus" only in **Google results**. Open each one on BEOE before
treating it as a Cyprus lead.

## 30-day launch plan

| Days | Do this | Engine support |
|---|---|---|
| 1–3 | Register the business name, set up WhatsApp Business, put the number in Scam Shield, deploy Dashy (Netlify, Vercel or Docker). Book one hour with a Pakistan lawyer on the scope of your service vs. the OEP licence. | `build` |
| 4–7 | Post an Urdu reel or short a day ("Agent ne yeh kaha? Check karein") in the Cyprus job Facebook groups. Every post links to Scam Shield. | traps → content ideas |
| 4–10 | Verify the top 8 partners in `leads` against the official registers, then send `partner_cy_agency` / `partner_lawyer`. | `leads`, `draft` |
| 8–14 | Deliver the first 10–20 paid reports by hand, and time each step. | `scan`, `firewall`, case report |
| 10–20 | Pitch 20 BEOE-licensed OEPs the Verified badge; aim for 2 paying. | `draft partner_oep` |
| 15–30 | Sign one Cyprus licensed agency on an employer-pays referral split and one university agent agreement. Start shortlisting candidates from the CV pool. | `match` |
| 30 | Review real conversion rates and update `pricing.json`. | `forecast` |

## Scaling path (Sovereign stack)

The two EU Sovereignty Platform blueprints, Education and Talent, are where this goes once there is revenue. This engine becomes their verification
and matching core:

- **Automation (n8n / Make):** call the CLI with `--json`, e.g. WhatsApp message in → `scan` → reply with flags and payment link.
- **System of record (Supabase/Postgres → Odoo):** the dataclasses in `case.py` and `graph.py` map one-to-one onto the
  `entities / identifiers / relationships / claims / evidence / payments` tables from the training spec.
- **AI layer (Mistral, hosted in the EU):** add LLM extraction *in front of* the trap library, for long PDFs and voice-note transcripts. Keep
  the rule engine as the final decision-maker, so a persuasive recruiter message can't talk the system out of an official fact.
- **Hosting:** Hetzner (Germany) for GDPR. The Proton suite for staff email and document storage.

## Next build steps (highest value first)
1. ~~WhatsApp bot~~ ✅ and ~~leads page + admin~~ ✅ done.
2. Lookup helpers for the BEOE OEP list and permissions that write `Claim` objects with `checked_on` dates.
3. Persistent storage for cases and the graph (SQLite to start, then Supabase), so the reputation graph keeps building.
4. Stripe or JazzCash payment links for the €15 and €79 reports.
5. KYB onboarding and the Sentinel partner score for the €499 Partner Platform tier.
