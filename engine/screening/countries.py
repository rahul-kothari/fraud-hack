"""Country normalisation and finding countries in free text.

Uses the mapping written by scripts/build_processed.py (processed/reference/countries.json).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from .config import REFERENCE

NOT_COUNTRIES = {"International", "Europe"}


@lru_cache(maxsize=1)
def _ref() -> dict:
    return json.loads((REFERENCE / "countries.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def mapping() -> dict[str, str]:
    r = _ref()
    m = {**r["codes"], **r["demonyms"], **r["spellings"]}
    for c in r["canonical_values_seen"]:
        m.setdefault(c, c)
    return m


def norm(value: str | None) -> str | None:
    if not value:
        return None
    v = re.sub(r"\[[^\]]*\]", "", value).strip().rstrip(".").strip()
    if not v or v in NOT_COUNTRIES:
        return None
    return mapping().get(v, v)


@lru_cache(maxsize=1)
def _text_pattern() -> re.Pattern:
    # Names and demonyms only (not 2-letter codes, which collide with words like "IN", "ID").
    r = _ref()
    words = set(r["demonyms"]) | set(r["spellings"]) | set(r["canonical_values_seen"])
    words |= {"Côte d'Ivoire", "Cote d'Ivoire", "Cote D'Ivoire", "the United States", "the United Kingdom"}
    alts = sorted(words, key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(w) for w in alts) + r")(?![A-Za-z])")


def find_in_text(text: str) -> list[str]:
    """Canonical countries mentioned in text, in order of appearance, deduplicated."""
    out: list[str] = []
    for m in _text_pattern().finditer(text or ""):
        w = m.group(1)
        if w.startswith("the "):
            w = w[4:]
        c = norm(w)
        if c and c not in out:
            out.append(c)
    return out
