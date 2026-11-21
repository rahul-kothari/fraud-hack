"""Name comparison, POLICY principle 8.

Parts: ignore case, accents, punctuation and anything in brackets. Single letters are initials (not
parts); each distinct part counts once; placeholders are not parts; for companies, legal forms are not
parts. Two parts match when identical, in the same name_variants group, written together or apart
(Abdulsalam ~ Abdul Salam, one part covering both), or within the edit limit (shorter part 4-6 letters:
1 edit, 7+: 2 edits, under 4: identical). Names agree when at least two parts match, or every part of
the shorter name matches.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from .config import REFERENCE

PLACEHOLDERS = {"na", "test", "unknown", "xxx", "none", "null", "nil", "tbd", "tba", "unk", "noname",
                "name", "customer", "dummy", "sample", "anonymous", "nn", "nk", "notknown"}
_TRANSLIT = str.maketrans({"ß": "ss", "ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe",
                           "ł": "l", "Ł": "l", "đ": "d", "Đ": "d", "ı": "i", "þ": "th", "ð": "d"})


@lru_cache(maxsize=1)
def _reference() -> tuple[dict[str, frozenset[int]], frozenset[str]]:
    data = json.loads((REFERENCE / "name_variants.json").read_text(encoding="utf-8"))
    groups: dict[str, set[int]] = {}
    for gi, g in enumerate(data["name_variant_groups"]):
        for w in g:
            groups.setdefault(w, set()).add(gi)
    return {k: frozenset(v) for k, v in groups.items()}, frozenset(data["company_legal_forms"])


def variant_groups(part: str) -> frozenset[int]:
    return _reference()[0].get(part, frozenset())


def legal_forms() -> frozenset[str]:
    return _reference()[1]


@lru_cache(maxsize=200_000)
def parts(name: str | None, company: bool = False) -> tuple[str, ...]:
    if not name:
        return ()
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}", " ", name)
    s = s.translate(_TRANSLIT)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    s = s.lower().replace("'", "").replace("’", "").replace("`", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    out: list[str] = []
    for t in s.split():
        if t.isdigit():
            continue
        t = re.sub(r"\d+", "", t)
        if len(t) < 2 or t in PLACEHOLDERS or re.fullmatch(r"(.)\1+", t):
            continue
        if company and t in legal_forms():
            continue
        if t not in out:
            out.append(t)
    return tuple(out)


def levenshtein(a: str, b: str, limit: int) -> int:
    """Edit distance (insert/delete/substitute), returning limit+1 as soon as it is exceeded."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        best = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            best = min(best, v)
        if best > limit:
            return limit + 1
        prev = cur
    return prev[-1]


@lru_cache(maxsize=500_000)
def part_match(a: str, b: str) -> bool:
    if a == b:
        return True
    if variant_groups(a) & variant_groups(b):
        return True
    short = min(len(a), len(b))
    if short < 4:
        return False
    limit = 1 if short <= 6 else 2
    return levenshtein(a, b, limit) <= limit


def _units(p: tuple[str, ...]) -> list[tuple[str, frozenset[int]]]:
    """Each part, plus each adjacent pair written together (covering both parts)."""
    u = [(x, frozenset({i})) for i, x in enumerate(p)]
    u += [(p[i] + p[i + 1], frozenset({i, i + 1})) for i in range(len(p) - 1)]
    return u


@dataclass(frozen=True)
class NameResult:
    agrees: bool
    matched: int            # matched parts (a joined pair counts once)
    pairs: tuple[tuple[str, str], ...]


def compare_parts(a: tuple[str, ...], b: tuple[str, ...]) -> NameResult:
    if not a or not b:
        return NameResult(False, 0, ())
    cand = [(ua, ia, ub, ib) for ua, ia in _units(a) for ub, ib in _units(b) if part_match(ua, ub)]
    best: tuple[int, int, tuple] = (0, 0, ())  # (matches, covered-of-shorter, pairs)
    short_is_a = len(a) <= len(b)

    def search(k: int, used_a: frozenset, used_b: frozenset, chosen: tuple) -> None:
        nonlocal best
        cover = len(used_a) if short_is_a else len(used_b)
        score = (len(chosen), cover, chosen)
        if score[:2] > best[:2]:
            best = score
        for n in range(k, len(cand)):
            ua, ia, ub, ib = cand[n]
            if ia & used_a or ib & used_b:
                continue
            search(n + 1, used_a | ia, used_b | ib, chosen + ((ua, ub),))

    search(0, frozenset(), frozenset(), ())
    matched, covered, pairs = best
    shorter = len(a) if short_is_a else len(b)
    agrees = matched >= 2 or covered == shorter
    return NameResult(agrees, matched, pairs)


def names_agree(a: str | None, b: str | None, company: bool = False) -> NameResult:
    return compare_parts(parts(a, company), parts(b, company))


def real_part_count(name: str | None, company: bool = False) -> int:
    return len(parts(name, company))
