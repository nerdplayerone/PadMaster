"""Hardware latency results from Gamepadla.com, shipped with PadMaster.

PadMaster does not measure latency. This module only looks up results that Gamepadla.com
measured with hardware testers. The data file is made by tools/fetch_gamepadla.py before a
release. The app never connects to Gamepadla.

Each controller (see history.model_key) is matched to one Gamepadla page:
- "auto": the name matches well, no question needed.
- "ask": the match is not certain. The app asks the owner to confirm, choose another or ignore.
- the owner's choice is saved in settings.json ("latency_map") and wins over the automatic match.
"""

from __future__ import annotations

import difflib
import json
import os
import re

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gamepadla_latency.json")
AUTO_SCORE = 0.86   # at or above: use the match without a question
ASK_SCORE = 0.45    # below: no suggestion
NONE = "none"       # the owner chose "no latency data"

_cache: dict | None = None


def load() -> dict:
    global _cache
    if _cache is None:
        try:
            with open(DATA_FILE, encoding="utf-8") as fh:
                _cache = json.load(fh)
        except (OSError, ValueError):
            _cache = {"controllers": []}
    return _cache


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    drop = {"controller", "gamepad", "wireless", "wired", "the", "for", "pad", "edition"}
    return " ".join(w for w in s.split() if w not in drop)


def score(query: str, name: str) -> float:
    q, n = _norm(query), _norm(name)
    if not q or not n:
        return 0.0
    ratio = difflib.SequenceMatcher(None, q, n).ratio()
    qs, ns = set(q.split()), set(n.split())
    overlap = len(qs & ns) / len(qs) if qs else 0.0  # share of typed words found in the name
    best = max(ratio, 0.5 * ratio + 0.5 * overlap)
    if len(qs) >= 2 and qs <= ns:  # every typed word is in the name (for example, the brand is missing)
        best = max(best, 0.86 + 0.1 * ratio)
    return min(best, 1.0)


def candidates(query: str, limit: int = 8) -> list[dict]:
    out = []
    for c in load().get("controllers", []):
        out.append({"name": c["name"], "url": c["url"], "score": round(score(query, c["name"]), 3)})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


def by_url(url: str) -> dict | None:
    for c in load().get("controllers", []):
        if c["url"] == url:
            return c
    return None


def query_for(meta: dict) -> str:
    """The text to match: the owner's pad name if there is one, else the model name."""
    return str(meta.get("label") or meta.get("device") or "")


def resolve(meta: dict, choices: dict) -> dict:
    """Find the Gamepadla entry for this session.

    Returns {"state": "chosen"|"auto"|"ask"|"none", "entry": dict|None, "suggest": [...]}.
    """
    from .history import model_key
    key = model_key(meta)
    picked = choices.get(key)
    if picked == NONE:
        return {"state": "none", "entry": None, "suggest": [], "key": key}
    if picked:
        entry = by_url(picked)
        if entry:
            return {"state": "chosen", "entry": entry, "suggest": [], "key": key}
    # Match only what the owner typed. The name Windows reports can be wrong (for example,
    # many pads report as "Xbox One Controller"), so it is never used for an automatic match.
    label = str(meta.get("label") or "")
    if not label:
        sug = candidates(str(meta.get("device") or ""))  # hints only: the owner must choose
        return {"state": "ask" if sug else "none", "entry": None, "suggest": sug, "key": key}
    sug = candidates(label)
    clear = len(sug) < 2 or sug[0]["score"] - sug[1]["score"] >= 0.05  # not two near-equal models
    if sug and sug[0]["score"] >= AUTO_SCORE and clear:
        return {"state": "auto", "entry": by_url(sug[0]["url"]), "suggest": sug, "key": key}
    if sug and sug[0]["score"] >= ASK_SCORE:
        return {"state": "ask", "entry": None, "suggest": sug, "key": key}
    return {"state": "ask" if sug else "none", "entry": None, "suggest": sug, "key": key}
