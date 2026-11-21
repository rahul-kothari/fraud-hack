"""Name matching and transliteration for sanctions screening.

Quick use::

    from screening.translit import NameMatcher, hit_names, romanize

    m = NameMatcher()
    r = m.compare_any(["Harunur Roshud"], [h.text for h in hit_names(hit)])
    r.agree, r.explain()

    romanize("Армен Мкртчян")            # 'armen mkrtchyan'
    spellings("محمد ندیم", limit=5)       # plausible Latin spellings
"""
from __future__ import annotations

from .hitnames import HitName, hit_names
from .lattice import Lattice, levenshtein
from .matcher import NameAssessment, NameComparison, NameMatcher, PartMatch, edit_budget
from .normalize import ParsedName, Part, parse_name
from .variants import Variants, default_variants

__all__ = [
    "HitName", "hit_names", "Lattice", "levenshtein", "NameAssessment", "NameComparison", "NameMatcher", "PartMatch",
    "edit_budget", "ParsedName", "Part", "parse_name", "Variants", "default_variants",
    "romanize", "spellings",
]


def romanize(name: str, entity_type: str | None = None) -> str:
    """Preferred Latin rendering of a name in any script (parts joined by spaces)."""
    return " ".join(p.text for p in parse_name(name, entity_type).parts)


def spellings(name: str, limit: int = 10) -> list[str]:
    """Up to ``limit`` plausible Latin spellings of each part, as 'part1 part2' strings."""
    parts = parse_name(name).parts
    if not parts:
        return []
    per_part = [p.lattice.spellings(limit) if p.lattice else [p.text] for p in parts]
    out = []
    for k in range(limit):
        out.append(" ".join(opts[min(k, len(opts) - 1)] for opts in per_part))
    return list(dict.fromkeys(out))
