"""Skills matching engine (EU Talent Sovereignty Platform, Module 3) — transparent, explainable scoring.

Score = weighted sum of axes, each 0-1. Visa eligibility is a gate, not a weight:
a candidate whose route is not lawful for the job scores 0 overall.
"""

CEFR = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6, "NATIVE": 7}

WEIGHTS = {"skills": 0.40, "experience": 0.25, "language": 0.20, "certifications": 0.10, "relocation": 0.05}

SKILL_ALIASES = {
    "mason": "masonry", "bricklayer": "masonry", "steel fixer": "rebar", "shuttering": "formwork",
    "chef de partie": "line cook", "commis": "line cook", "housekeeper": "housekeeping",
    "forklift": "forklift operation", "reach truck": "forklift operation", "pipe fitter": "plumbing",
    "electrician": "electrical installation", "wiring": "electrical installation", "cook": "line cook", "chef": "line cook",
    "waiter": "food service", "waitress": "food service", "picker": "picking", "order picking": "picking",
    "driver": "driving", "farm work": "harvesting", "fruit picking": "harvesting", "cleaner": "cleaning",
    "carer": "caregiving", "caregiver": "caregiving", "machine operator": "machine operation", "block laying": "masonry",
}


def _norm(skills):
    out = set()
    for s in skills or []:
        s = s.strip().lower()
        out.add(SKILL_ALIASES.get(s, s))
    return out


def match(candidate, job):
    """candidate: {skills, years, languages{en:B1}, certifications, relocation_ready, visa_eligible}
       job:       {title, required_skills, nice_skills, min_years, languages{en:A2}, certifications}"""
    if candidate.get("visa_eligible") is False:
        return {"job": job.get("title"), "overall": 0, "axes": {}, "gaps": ["No lawful visa/work-authorisation route"], "verdict": "NOT ELIGIBLE"}

    have = _norm(candidate.get("skills"))
    req, nice = _norm(job.get("required_skills")), _norm(job.get("nice_skills"))
    skills = (len(have & req) + 0.5 * len(have & nice)) / max(1, len(req) + 0.5 * len(nice))

    min_years = job.get("min_years", 0)
    experience = 1.0 if not min_years else min(1.0, candidate.get("years", 0) / min_years)

    lang_scores = []
    for lang, level in (job.get("languages") or {}).items():
        got = CEFR.get(str((candidate.get("languages") or {}).get(lang, "")).upper(), 0)
        lang_scores.append(min(1.0, got / CEFR[level.upper()]))
    language = sum(lang_scores) / len(lang_scores) if lang_scores else 1.0

    need_cert = _norm(job.get("certifications"))
    certifications = len(_norm(candidate.get("certifications")) & need_cert) / len(need_cert) if need_cert else 1.0
    relocation = 1.0 if candidate.get("relocation_ready") else 0.3

    axes = {"skills": skills, "experience": experience, "language": language, "certifications": certifications, "relocation": relocation}
    overall = sum(WEIGHTS[k] * v for k, v in axes.items())
    gaps = ["Missing skill: " + s for s in sorted(req - have)]
    gaps += ["Language below requirement"] if language < 1 else []
    gaps += ["Missing certification: " + c for c in sorted(need_cert - _norm(candidate.get("certifications")))]
    verdict = "STRONG" if overall >= 0.8 else "POSSIBLE" if overall >= 0.6 else "WEAK"
    return {"job": job.get("title"), "overall": round(overall * 100), "axes": {k: round(v * 100) for k, v in axes.items()},
            "gaps": gaps, "verdict": verdict}


def rank(candidate, jobs):
    return sorted((match(candidate, j) for j in jobs), key=lambda r: -r["overall"])
