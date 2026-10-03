"""The platform's agents. Each one is listed publicly on /agents (EU AI Act transparency):
what it does, whether it is rules or AI, what a human must approve, and what data it touches.
"""
import json
import os
import re

from . import DATA_DIR, db

REGISTRY = [
    {"id": "sentinel", "name": "Sentinel", "kind": "Rules", "job": "Scans recruiter messages for 20 known scam patterns and scores the risk.",
     "human": "Only a person can call an offer genuine or fraudulent. Sentinel never returns 'safe'.", "data": "Message text is processed in memory and not stored; only the risk band and pattern IDs are counted."},
    {"id": "scout", "name": "Scout", "kind": "Automation", "job": "Collects new opportunities from approved public sources on a schedule, respecting robots.txt.",
     "human": "Nothing Scout finds is marked verified. An analyst verifies or flags each listing.", "data": "Public job listings only. No personal data."},
    {"id": "verifier", "name": "Verifier", "kind": "Rules", "job": "Labels each opportunity by source trust tier (government → social media) and visa-sponsorship signals.",
     "human": "Labels are evidence grades, not approvals.", "data": "Listing text and source."},
    {"id": "matchmaker", "name": "Matchmaker", "kind": "Rules", "job": "Scores a candidate against open roles on skills, experience, language level and certifications, and explains every gap.",
     "human": "Scores support a human recruiter's decision; they never accept or reject a person. (Recruitment AI is high-risk under the EU AI Act, Annex III.)", "data": "The profile you enter, kept until you delete it."},
    {"id": "concierge", "name": "Concierge", "kind": "AI (Claude) with rules fallback", "job": "Answers corridor questions only from MUSA's sourced knowledge base and cites each source.",
     "human": "It refuses rather than guesses. Legal questions are referred to a licensed professional.", "data": "Your question is sent to the model provider to answer it and is not stored by MUSA."},
    {"id": "firewall", "name": "Payment Firewall", "kind": "Rules", "job": "Checks a payment request: who receives it, what it is for, which fees are verified.",
     "human": "Every PAY decision still needs a named person to approve it.", "data": "Payment details you provide for a case."},
    {"id": "outreach", "name": "Outreach Writer", "kind": "Templates", "job": "Drafts neutral due-diligence messages to agents, employers and embassies, and partner pitches.",
     "human": "A person reviews and sends every message. Nothing is sent automatically.", "data": "Names and references you supply."},
    {"id": "guardian", "name": "Guardian", "kind": "Automation", "job": "Applies data-retention limits, expires stale listings and writes the audit trail.",
     "human": "Erasure requests are actioned by a person and logged.", "data": "Records past their retention period are deleted."},
]


# ---------------- Concierge ----------------

def load_knowledge(path=None):
    with open(path or os.path.join(DATA_DIR, "knowledge.json"), encoding="utf-8") as f:
        return json.load(f)["entries"]


def _words(s):
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def retrieve(question, knowledge, k=3):
    """Keyword-overlap retrieval: phrase hits count double. Deterministic and auditable."""
    ql = question.lower()
    qw = _words(question)
    scored = []
    for e in knowledge:
        score = 0
        for kw in e["keywords"]:
            if " " in kw:
                score += 2 if kw in ql else 0
            elif kw in qw:
                score += 1
        if score:
            scored.append((score, e))
    scored.sort(key=lambda t: -t[0])
    return [e for _, e in scored[:k]]


SYSTEM_PROMPT = """You are the MUSA Corridor concierge for people from Pakistan and South Asia asking about work, study and family routes to Cyprus and the EU, and for employers and agencies hiring through that corridor.

Answer ONLY from the knowledge entries supplied in the user turn. Cite every factual sentence with its entry id in square brackets, like [K2]. If the entries do not answer the question, say plainly that you do not have a sourced answer, and suggest the Verify-Before-You-Pay report or a licensed immigration lawyer. Never state fees, quotas or processing times; never promise a visa outcome; never help create or alter documents. Write short, plain sentences. If the question is written in Roman Urdu, answer in Roman Urdu."""


def _rules_answer(question, hits):
    if not hits:
        return {"mode": "rules", "answer": "I don't have a sourced answer to that yet. For a specific offer, paste it into Scam Shield or order a Verify-Before-You-Pay report; for legal advice, speak to a licensed immigration lawyer.",
                "sources": [], "matched": []}
    top = hits[0]
    return {"mode": "rules", "answer": top["a"] + " [%s]" % top["id"], "sources": [dict(s, entry=top["id"]) for s in top["sources"]],
            "matched": [h["id"] for h in hits], "related": [{"id": h["id"], "q": h["q"]} for h in hits[1:]]}


def ask(question, knowledge=None, client=None):
    """Answer a question. Uses Claude when ANTHROPIC_API_KEY (or another SDK credential) is configured
    and the `anthropic` package is installed; otherwise the deterministic rules answer."""
    question = (question or "").strip()[:800]
    knowledge = knowledge if knowledge is not None else load_knowledge()
    hits = retrieve(question, knowledge)
    result = None
    if os.environ.get("MUSA_CONCIERGE_AI", "auto") != "off" and hits:
        result = _claude_answer(question, hits, client)
    if result is None:
        result = _rules_answer(question, hits)
    db.insert("questions", created_at=db.now_iso(), mode=result["mode"], matched=",".join(result.get("matched", [])),
              answered=1 if result.get("sources") else 0)
    return result


def _claude_answer(question, hits, client=None):
    try:
        if client is None:
            if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                return None
            import anthropic  # optional dependency: pip install anthropic
            client = anthropic.Anthropic(timeout=30.0, max_retries=1)
        ledger = "\n\n".join("[%s] %s\n%s\nSources: %s" % (e["id"], e["q"], e["a"], "; ".join(s["title"] for s in e["sources"])) for e in hits)
        kwargs = dict(
            model=os.environ.get("MUSA_CONCIERGE_MODEL", "claude-opus-5-5"),
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": "Knowledge entries:\n\n%s\n\nQuestion: %s" % (ledger, question)}],
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        try:
            resp = client.beta.messages.create(**kwargs)
        except TypeError:  # older SDK without the `fallbacks` keyword: send it as a raw body field
            kwargs["extra_body"] = {"fallbacks": kwargs.pop("fallbacks")}
            resp = client.beta.messages.create(**kwargs)
        if resp.stop_reason == "refusal":
            return None
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        if not text:
            return None
        cited = [e for e in hits if "[%s]" % e["id"] in text]
        if not cited:  # an uncited answer is not allowed out
            return None
        return {"mode": "ai", "answer": text, "matched": [h["id"] for h in hits],
                "sources": [dict(s, entry=e["id"]) for e in cited for s in e["sources"]]}
    except Exception as e:  # any API/SDK problem → rules answer
        db.audit("agent:concierge", "concierge.ai_error", detail={"error": type(e).__name__})
        return None


# ---------------- EU-format CV ----------------

CV_FIELDS = ["name", "headline", "skills", "years", "languages", "certifications", "experience", "education", "relocation_ready"]


def parse_profile_form(form):
    langs = {}
    for part in (form.get("languages") or "").split(","):
        if ":" in part:
            k, v = part.split(":", 1)
            langs[k.strip().lower()[:12]] = v.strip().upper()[:6]
    split = lambda s: [x.strip() for x in (s or "").replace("\n", ",").split(",") if x.strip()][:30]
    try:
        years = max(0, min(50, int(form.get("years") or 0)))
    except ValueError:
        years = 0
    return {
        "name": (form.get("name") or "").strip()[:80],
        "headline": (form.get("headline") or "").strip()[:120],
        "skills": split(form.get("skills")),
        "years": years,
        "languages": langs,
        "certifications": split(form.get("certifications")),
        "experience": (form.get("experience") or "").strip()[:2000],
        "education": (form.get("education") or "").strip()[:800],
        "relocation_ready": form.get("relocation_ready") == "on",
        "share_ok": form.get("share_ok") == "on",
        "visa_eligible": None,  # unknown until a real offer is verified; never assumed
    }
