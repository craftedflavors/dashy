"""Trap library scanner: turns a recruiter message into risk signals and suggested replies."""
import json
import os
import re

from . import DATA_DIR
from .risk import decide

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def load_traps(path=None):
    path = path or os.path.join(DATA_DIR, "traps.json")
    with open(path, encoding="utf-8") as f:
        traps = json.load(f)["traps"]
    for t in traps:
        t["_compiled"] = [re.compile(p, re.IGNORECASE) for p in t["patterns"]]
    return traps


def scan(text, traps=None):
    """Scan free text (WhatsApp chat, email, ad). Returns hits sorted by severity."""
    traps = traps if traps is not None else load_traps()
    hits = []
    for t in traps:
        for rx in t["_compiled"]:
            m = rx.search(text)
            if m:
                hits.append({
                    "id": t["id"], "name": t["name"], "severity": t["severity"], "signal": t["signal"],
                    "evidence": text[max(0, m.start() - 30):m.end() + 30].strip(),
                    "response": t["response"], "response_ur": t.get("response_ur", ""),
                })
                break
    hits.sort(key=lambda h: _SEVERITY_ORDER.get(h["severity"], 9))
    return hits


def assess_message(text, traps=None):
    """Scan + decide. A message alone can never be GREEN — nothing has been verified yet."""
    hits = scan(text, traps)
    decision = decide({h["signal"] for h in hits})
    return {"hits": hits, "decision": decision}
