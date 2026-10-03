"""Recruiter Reputation Graph — identity resolution and document-template fingerprinting.

The graph surfaces *relationships*, never accusations: output wording is always
"POTENTIAL ENTITY REUSE — independent verification required".
"""
import hashlib
import re
from collections import defaultdict
from itertools import combinations

FREE_MAIL = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "live.com", "icloud.com", "proton.me", "protonmail.com"}

# How much each shared identifier type says about "same operator".
IDENTIFIER_WEIGHT = {"bank": 3, "phone": 2, "email": 2, "domain": 2, "address": 1, "person": 1}


def _digits(s):
    return re.sub(r"\D", "", s or "")


def normalise(kind, value):
    """Normalise an identifier so trivially different spellings collide."""
    if not value:
        return None
    v = value.strip().lower()
    if kind == "phone":
        d = _digits(v)
        return d[-10:] if len(d) >= 9 else None
    if kind == "email":
        return v
    if kind == "domain":
        v = re.sub(r"^https?://", "", v).split("/")[0]
        v = v[4:] if v.startswith("www.") else v
        return None if v in FREE_MAIL else v
    if kind == "bank":
        # Never store raw account numbers in the graph.
        return "sha256:" + hashlib.sha256(_digits(v).encode() or v.encode()).hexdigest()[:16]
    if kind in ("address", "person"):
        return re.sub(r"[^a-z0-9]+", " ", v).strip()
    return v


class ReputationGraph:
    def __init__(self):
        self.entities = {}
        self.index = defaultdict(set)  # (kind, value) -> {entity_id}

    def add_entity(self, entity_id, name, etype="recruiter", identifiers=None, outcomes=None):
        identifiers = identifiers or {}
        norm = []
        for kind, values in identifiers.items():
            for raw in (values if isinstance(values, list) else [values]):
                n = normalise(kind, raw)
                if n:
                    norm.append((kind, n))
                    self.index[(kind, n)].add(entity_id)
                if kind == "email" and n and "@" in n:
                    dom = normalise("domain", n.split("@", 1)[1])
                    if dom:
                        norm.append(("domain", dom))
                        self.index[("domain", dom)].add(entity_id)
        self.entities[entity_id] = {"id": entity_id, "name": name, "type": etype, "identifiers": norm, "outcomes": outcomes or {}}

    def find_reuse(self):
        """Pairs of distinct entities sharing infrastructure, with a confidence grade."""
        pair_shared = defaultdict(list)
        for (kind, value), ids in self.index.items():
            for a, b in combinations(sorted(ids), 2):
                pair_shared[(a, b)].append(kind)
        findings = []
        for (a, b), kinds in pair_shared.items():
            kinds = sorted(set(kinds))
            weight = sum(IDENTIFIER_WEIGHT.get(k, 1) for k in kinds)
            confidence = "HIGH" if weight >= 4 or "bank" in kinds else "MEDIUM" if weight >= 2 else "LOW"
            findings.append({
                "finding": "POTENTIAL ENTITY REUSE",
                "entities": [self.entities[a]["name"], self.entities[b]["name"]],
                "shared": kinds, "confidence": confidence,
                "action": "ESCALATE_FOR_MANUAL_VERIFICATION" if confidence != "LOW" else "NOTE",
            })
        findings.sort(key=lambda f: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}[f["confidence"]])
        return findings

    def lookup(self, identifiers):
        """Which known entities share any of these identifiers? Used by the payment firewall."""
        hits = defaultdict(set)
        for kind, values in (identifiers or {}).items():
            for raw in (values if isinstance(values, list) else [values]):
                n = normalise(kind, raw)
                for eid in self.index.get((kind, n), ()):
                    hits[eid].add(kind)
        return [{"entity": self.entities[e]["name"], "type": self.entities[e]["type"], "shared": sorted(k),
                 "outcomes": self.entities[e]["outcomes"]} for e, k in hits.items()]


# ---------------- document fingerprinting ----------------

def _shingles(text, k=5):
    words = re.findall(r"[a-z0-9€]+", text.lower())
    return {" ".join(words[i:i + k]) for i in range(max(1, len(words) - k + 1))}


def fingerprint(text):
    return {"sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "shingles": _shingles(text)}


def similarity(a, b):
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def template_reuse(documents, threshold=0.6):
    """documents: {doc_id: text}. Flags pairs that look like the same template with names swapped."""
    out = []
    items = list(documents.items())
    for (ia, ta), (ib, tb) in combinations(items, 2):
        sim = similarity(ta, tb)
        if sim >= threshold:
            out.append({"finding": "DOCUMENT TEMPLATE REUSE", "documents": [ia, ib], "similarity": round(sim, 2),
                        "note": "Not proof of fraud — tells the investigator where to look."})
    return sorted(out, key=lambda f: -f["similarity"])
