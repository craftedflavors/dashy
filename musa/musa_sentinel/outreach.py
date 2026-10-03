"""Message templates (spec §23-25) plus sales templates for the revenue engine.

Rules baked in: neutral, evidence-oriented, never accusatory, never impersonating anyone,
always sent under the sender's real name and company.
"""
import re

TEMPLATES = {
    "oep_due_diligence": """Assalam o Alaikum.

We are evaluating the foreign employment opportunity under BEOE permission {permission}.
Before proceeding with candidate processing, please provide:
1. OEP licence number and current licence status
2. Employer legal name and registration details
3. Job order / permission details, job title, vacancies
4. Salary, working hours, contract duration, accommodation
5. Work-authorisation status and visa category
6. Complete worker cost breakdown — official government charges separated from OEP/service charges
7. Payment schedule and refund policy if the visa is refused or the job cancelled
8. Required documents and expected processing stages

We require official receipts for all payments.
Regards,
{sender} — {company}""",

    "employer_confirmation": """Dear {contact},

We are conducting due diligence regarding recruitment for {job} at {employer}.
Could you please confirm:
1. Your legal company name, registration number and registered address
2. Whether you are currently recruiting workers from Pakistan for this role
3. Whether {agency} is authorised to recruit on your behalf
4. Number of vacancies, salary, working hours, contract duration and accommodation
5. Work-authorisation status and expected recruitment timeline

We are verifying these details before any candidate processing or payment.
Regards,
{sender} — {company}""",

    "embassy_procedure": """Dear Sir/Madam,

We are seeking clarification of the official employment-visa procedure for Pakistani nationals taking up employment in {country}.
Could you please confirm: the correct visa category; whether prior work authorisation is required; where and how applications are submitted; the appointment procedure; the official fee; the document list; whether any authorised external service provider is involved; and the official page where current requirements are published.

Regards,
{sender} — {company}""",

    "partner_cy_agency": """Dear {contact},

I run {company}, a verification-first recruitment intelligence service in the Pakistan → Cyprus corridor.
Cyprus employers lose months to no-shows, fake documents and unlicensed middlemen. We pre-verify every candidate (identity, BEOE/Protector status, genuine experience, documents checked at source) before they reach you, and we only work with BEOE-licensed OEPs on the Pakistan side.

Proposal: you remain the licensed Cyprus agency of record; we supply verified, interview-ready shortlists for your employer mandates on an employer-pays basis, with a referral share agreed in writing. Zero fees charged to workers.

Could we have a 20-minute call this week? Which sectors are your employers short on right now (construction, hospitality, logistics, agriculture)?

Regards,
{sender} — {company} · {phone}""",

    "partner_oep": """Assalam o Alaikum {contact},

{company} runs MUSA Sentinel — a verification layer families use before paying any recruiter. Thousands of workers are scared of Cyprus/Europe visa scams, and they now check recruiters with us first.

Licensed OEPs can join our Verified Recruiter programme (€{price}/month): your licence and active BEOE permissions are shown as VERIFIED when families scan your offers, and you get our case-tracking and cost-ledger tools. The badge is revocable on any red-flag pattern — that is exactly why families trust it.

Shall I send the onboarding checklist? We need your OEP licence number and one active BEOE permission.

{sender} · {phone}""",

    "partner_lawyer": """Dear {contact},

{company} pre-screens Pakistan → Cyprus work-permit and student cases. Many of our cases need a Cyprus immigration lawyer for the final filing. We would like to refer verified, document-complete clients to {firm} under a written referral agreement. Could we discuss your fee schedule for TCN employment and student files?

Regards,
{sender} — {company}""",

    "worker_report_offer": """Assalam o Alaikum {name},

Aap ne jo offer scan kiya us mein {flags} khatre ke nishan mile hain. Payment se pehle verify karna zaroori hai.

MUSA Verify-Before-You-Pay Report (Rs {price_pkr}):
✔ OEP licence aur BEOE permission check
✔ Employer company registry check
✔ Kharchon ki tafseel — kaunsa government fee hai aur kaunsa agent ka
✔ 48 ghante mein written report

Hum job nahi bechte aur kisi agent se commission nahi lete — sirf aap ka paisa bachate hain.
Reply "REPORT" to start.""",
}

_FIELD = re.compile(r"{(\w+)}")


def fields(name):
    return sorted(set(_FIELD.findall(TEMPLATES[name])))


def render(name, **values):
    missing = [f for f in fields(name) if f not in values]
    if missing:
        raise KeyError("Template %r needs: %s" % (name, ", ".join(missing)))
    return TEMPLATES[name].format(**values)
