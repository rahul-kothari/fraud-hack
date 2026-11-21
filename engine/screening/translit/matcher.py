"""Principle-8 name agreement, extended to transliterated aliases.

Two parts match when they are identical, are listed together in
name_variants.json, are written together or apart (Abdulsalam ~ Abdul Salam,
one part covering both), or differ by at most 1 edit for parts of 4-6 letters
and 2 for longer ones (the shorter part's length decides; parts shorter than
4 letters must be identical). Names agree when at least two parts match, or
every part of the shorter name matches. Each part is used at most once.

A transliterated part matches a Latin part when the Latin part (or one of
its listed variants) is one of the alias's plausible romanizations, or is
within ``translit_max_edits`` (default 1, and never more than the SOP budget)
of one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .lattice import Lattice, levenshtein
from .normalize import ParsedName, Part, parse_name
from .variants import Variants, default_variants

INDIVIDUAL_TYPES = {"individual", "person", "natural person", ""}


def edit_budget(length: int) -> int:
    if length < 4:
        return 0
    if length <= 6:
        return 1
    return 2


@dataclass(frozen=True)
class PartMatch:
    customer: str          # customer part(s), "+"-joined when one side is written apart
    hit: str               # hit part(s)
    kind: str              # identical | variant | spelling | joined | transliteration
    edits: int = 0
    transliterated: bool = False


@dataclass
class NameComparison:
    agree: bool | None              # None: customer name has < 2 real parts (individual)
    customer_name: str
    hit_name: str
    customer_parts: list[str] = field(default_factory=list)
    hit_parts: list[str] = field(default_factory=list)
    matches: list[PartMatch] = field(default_factory=list)
    note: str = ""

    @property
    def matched(self) -> int:
        return len(self.matches)

    @property
    def via_transliteration(self) -> bool:
        return any(m.transliterated for m in self.matches)

    def explain(self) -> str:
        if self.agree is None:
            return f"'{self.customer_name}' has fewer than two real name parts: {self.note}"
        pairs = ", ".join(f"{m.customer}~{m.hit} [{m.kind}{f' {m.edits} edit' if m.edits else ''}]"
                          for m in self.matches) or "none"
        verdict = "agree" if self.agree else "do not agree"
        return f"'{self.customer_name}' and '{self.hit_name}' {verdict}: matched parts {pairs}. {self.note}".strip()

    def sort_key(self) -> tuple:
        rank = {True: 2, None: 1, False: 0}[self.agree]
        latin = not self.via_transliteration
        return (rank, latin, self.matched, -sum(m.edits for m in self.matches))


@dataclass(frozen=True)
class _Edge:
    a: frozenset[int]
    b: frozenset[int]
    match: PartMatch


class NameMatcher:
    def __init__(self, variants: Variants | None = None, transliterate: bool = True,
                 translit_max_edits: int = 1, translit_max_total_edits: int = 1):
        self.variants = variants or default_variants()
        self.transliterate = transliterate
        self.translit_max_edits = translit_max_edits
        self.translit_max_total_edits = translit_max_total_edits

    # ------------------------------------------------------------- parsing
    def parse(self, name: str | None, entity_type: str | None = None) -> ParsedName:
        return parse_name(name, entity_type, variants=self.variants, transliterate=self.transliterate)

    # -------------------------------------------------------- part matching
    def part_match(self, a: Part, b: Part, kind_if_ok: str | None = None) -> PartMatch | None:
        """Does customer part ``a`` match hit part ``b``?"""
        if a.lattice is None and b.lattice is None:
            x, y = a.text, b.text
            if x == y:
                return PartMatch(x, y, kind_if_ok or "identical")
            if self.variants.same_group(x, y):
                return PartMatch(x, y, kind_if_ok or "variant")
            budget = edit_budget(min(len(x), len(y)))
            if budget:
                d = levenshtein(x, y)
                if d <= budget:
                    return PartMatch(x, y, kind_if_ok or "spelling", edits=d)
            return None
        # at least one side is a transliteration lattice
        if a.lattice is not None and b.lattice is not None:
            ca, cb = a.text, b.text
            if a.lattice.distance(cb, 0) == 0 or b.lattice.distance(ca, 0) == 0:
                return PartMatch(a.display(), b.display(), "transliteration", transliterated=True)
            return None
        latin, lat = (a, b.lattice) if b.lattice is not None else (b, a.lattice)
        assert lat is not None
        x = latin.text
        canon = lat.canonical()
        # Short parts must be identical (SOP). For a lattice that means: an exact
        # spelling, and not one reached only by dropping most optional slots
        # ("le" is not a reading of اللہ).
        if len(x) < 4 and abs(len(x) - len(canon)) > 1:
            return None
        d = lat.distance(x, cap=2)
        kind = "transliteration"
        if d > 0:
            # a listed variant counts only as an exact reading (no stacking of variant + edits)
            for v in sorted(self.variants.variants_of(x)):
                if (len(v) >= 4 or abs(len(v) - len(canon)) <= 1) and lat.distance(v, cap=0) == 0:
                    d, kind = 0, "transliteration+variant"
                    break
            # listed variant groups document vowel variation (Muhammad, Mohammed,
            # Mohamed); for a member of a group, vowel quality is free
            if d > 0 and len(x) >= 4 and self.variants.variants_of(x) and \
                    lat.distance(x, cap=0, vowel_free=True) == 0:
                d, kind = 0, "transliteration+variant"
        budget = min(edit_budget(min(len(x), len(canon))), self.translit_max_edits)
        if d == 0 or d <= budget:
            return PartMatch(a.display(), b.display(), kind, edits=d, transliterated=True)
        return None

    @staticmethod
    def _join(parts: Sequence[Part]) -> Part:
        if all(p.lattice is None for p in parts):
            return Part(text="".join(p.text for p in parts), source=" ".join(p.source for p in parts))
        lat = parts[0].as_lattice()
        for p in parts[1:]:
            if lat.script in ("Arabic", "Hebrew") or p.script in ("Arabic", "Hebrew"):
                lat = lat + Lattice([("", "a", "e", "i", "o", "u")])  # vowel at the seam
            lat = lat + p.as_lattice()
        return Part(text=lat.canonical(), lattice=lat, source=" ".join(p.source for p in parts),
                    script=lat.script)

    def _edges(self, A: list[Part], B: list[Part]) -> list[_Edge]:
        edges: list[_Edge] = []
        for i, a in enumerate(A):
            for j, b in enumerate(B):
                m = self.part_match(a, b)
                if m:
                    edges.append(_Edge(frozenset([i]), frozenset([j]), m))
        # written together or apart: one part vs two adjacent parts on the other side
        for i, a in enumerate(A):
            for j in range(len(B) - 1):
                joined = self._join(B[j:j + 2])
                m = self.part_match(a, joined, "joined")
                if m:
                    edges.append(_Edge(frozenset([i]), frozenset([j, j + 1]),
                                       PartMatch(m.customer, f"{B[j].display()}+{B[j+1].display()}", "joined",
                                                 m.edits, m.transliterated)))
        for j, b in enumerate(B):
            for i in range(len(A) - 1):
                joined = self._join(A[i:i + 2])
                m = self.part_match(joined, b, "joined")
                if m:
                    edges.append(_Edge(frozenset([i, i + 1]), frozenset([j]),
                                       PartMatch(f"{A[i].display()}+{A[i+1].display()}", m.hit, "joined",
                                                 m.edits, m.transliterated)))
        return edges

    def _agrees(self, chosen: Sequence[_Edge], nA: int, nB: int) -> bool:
        if not chosen:
            return False
        usedA = set().union(*(e.a for e in chosen))
        usedB = set().union(*(e.b for e in chosen))
        covered = (nA < nB and len(usedA) == nA) or (nB < nA and len(usedB) == nB) or \
                  (nA == nB and (len(usedA) == nA or len(usedB) == nB))
        # weak transliterated evidence must not stack: at most
        # `translit_max_total_edits` edits across all transliterated matches
        tr_edits = sum(e.match.edits for e in chosen if e.match.transliterated)
        return (len(chosen) >= 2 or covered) and tr_edits <= self.translit_max_total_edits

    def _best_assignment(self, edges: list[_Edge], nA: int, nB: int) -> list[_Edge]:
        """Vertex-disjoint edge set maximising (agreement, #matches, -edits)."""
        best: list[_Edge] = []
        best_key: tuple = (-1,)

        def key(chosen: list[_Edge]) -> tuple:
            return (self._agrees(chosen, nA, nB), len(chosen),
                    not any(e.match.transliterated for e in chosen),
                    -sum(e.match.edits for e in chosen))

        def rec(k: int, chosen: list[_Edge], usedA: frozenset, usedB: frozenset) -> None:
            nonlocal best, best_key
            if k == len(edges):
                kk = key(chosen)
                if kk > best_key:
                    best_key, best = kk, list(chosen)
                return
            # upper bound pruning: even taking every remaining edge cannot beat best count
            if best_key[0] is True and len(chosen) + (len(edges) - k) < best_key[1]:
                return
            e = edges[k]
            if not (e.a & usedA) and not (e.b & usedB):
                chosen.append(e)
                rec(k + 1, chosen, usedA | e.a, usedB | e.b)
                chosen.pop()
            rec(k + 1, chosen, usedA, usedB)

        if len(edges) > 18:  # keep the search bounded: greedy on the cheapest edges
            edges = sorted(edges, key=lambda e: (e.match.edits, e.match.transliterated))[:18]
        rec(0, [], frozenset(), frozenset())
        return best

    # --------------------------------------------------------------- public
    def compare(self, customer_name: str | ParsedName, hit_name: str | ParsedName,
                entity_type: str | None = None, customer_entity_type: str | None = None) -> NameComparison:
        """Compare one customer name with one hit name (name or alias)."""
        cust = customer_name if isinstance(customer_name, ParsedName) else \
            self.parse(customer_name, customer_entity_type or entity_type)
        hit = hit_name if isinstance(hit_name, ParsedName) else self.parse(hit_name, entity_type)
        A, B = cust.parts, hit.parts
        res = NameComparison(agree=False, customer_name=cust.raw, hit_name=hit.raw,
                             customer_parts=[p.display() for p in A], hit_parts=[p.display() for p in B])
        is_individual = (customer_entity_type or entity_type or "").strip().lower() in INDIVIDUAL_TYPES
        if not A or not B:
            res.note = "no comparable name parts"
            if is_individual and len(A) < 2:
                res.agree = None
            return res
        chosen = self._best_assignment(self._edges(A, B), len(A), len(B))
        res.matches = [e.match for e in chosen]
        res.agree = self._agrees(chosen, len(A), len(B))
        if is_individual and len(A) < 2:
            # SOP: an individual whose names have fewer than two real parts can be
            # neither confirmed nor cleared on name.
            res.note = "customer name has fewer than two real parts"
            res.agree = None
        return res

    def compare_any(self, customer_names: Iterable[str | ParsedName], hit_names: Iterable[str | ParsedName],
                    entity_type: str | None = None, customer_entity_type: str | None = None) -> NameComparison:
        """Best comparison over every customer name x every hit name/alias.

        ``agree`` is True if any pair agrees; False only if every pair was
        comparable and none agrees (the basis for NAME_MISMATCH_VERIFIED);
        None if nothing could be compared.
        """
        best: NameComparison | None = None
        hits = [h if isinstance(h, ParsedName) else self.parse(h, entity_type) for h in hit_names]
        for c in customer_names:
            if not c:
                continue
            for h in hits:
                if not h.parts:
                    continue
                r = self.compare(c, h, entity_type, customer_entity_type)
                if best is None or r.sort_key() > best.sort_key():
                    best = r
        if best is None:
            return NameComparison(agree=None, customer_name="", hit_name="", note="no comparable names")
        return best


@dataclass
class NameAssessment:
    """Name evidence for one hit, in the two readings the decision needs.

    ``literal`` applies principle 8 to Latin letters only (non-Latin aliases
    have no comparable parts). ``transliterated`` also reads the hit's
    *independent* native-script aliases through the transliteration model.

    A native alias that agrees with one of the hit's own Latin names is just
    a rendering of it, and a lossy one (Arabic writes Wyn and Wynn alike), so
    it adds nothing and is left out (``redundant_aliases``). An alias with no
    Latin counterpart (``independent_aliases``) is real extra evidence: a
    customer named like it must not be cleared on name.

    Use it asymmetrically, as the SOP's "when in doubt, REVIEW" asks:
    * clear on name (NAME_MISMATCH_VERIFIED) only if neither reading agrees;
    * confirm on name only on literal agreement, unless
      ``confirm_on_transliteration`` is set.
    """
    literal: NameComparison
    transliterated: NameComparison
    confirm_on_transliteration: bool = False
    independent_aliases: list[str] = field(default_factory=list)
    redundant_aliases: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.literal.agree:
            return "agree"
        if self.transliterated.agree:
            return "agree_via_transliteration"
        if self.literal.agree is None and self.transliterated.agree is None:
            return "undecidable"
        return "disagree"

    @property
    def can_clear(self) -> bool:
        """True when the names give a NAME_MISMATCH contradiction."""
        return self.literal.agree is False and self.transliterated.agree is False

    @property
    def supports_confirm(self) -> bool:
        if self.literal.agree:
            return True
        return bool(self.confirm_on_transliteration and self.transliterated.agree)

    @property
    def best(self) -> NameComparison:
        return self.literal if self.literal.agree or not self.transliterated.agree else self.transliterated

    def explain(self) -> str:
        if self.status == "agree_via_transliteration":
            return (f"{self.transliterated.explain()} Only this native-script alias, which has no Latin "
                    "counterpart on the profile, agrees; the Latin names do not.")
        return self.best.explain()


def _literal_twin(m: NameMatcher) -> NameMatcher:
    twin = getattr(m, "_literal", None)
    if twin is None:
        twin = NameMatcher(m.variants, transliterate=False)
        m._literal = twin  # type: ignore[attr-defined]
    return twin


def assess(self: NameMatcher, customer_names: Iterable[str], hit_names_: Iterable[str],
           entity_type: str | None = None, customer_entity_type: str | None = None,
           confirm_on_transliteration: bool = False, independent_only: bool = True) -> NameAssessment:
    """Assess a customer's names against all of a hit's names and aliases."""
    cust = [c for c in customer_names if c]
    hits = [h for h in hit_names_ if h]
    literal = _literal_twin(self)
    lit = literal.compare_any(cust, hits, entity_type, customer_entity_type)
    if not self.transliterate:
        return NameAssessment(lit, lit, confirm_on_transliteration)
    parsed = {h: self.parse(h, entity_type) for h in hits}
    native = [h for h in hits if parsed[h].scripts]
    latin = [h for h in hits if not parsed[h].scripts]
    independent, redundant = [], []
    for h in native:
        if independent_only and latin and \
                self.compare_any(latin, [parsed[h]], entity_type, entity_type).agree is True:
            redundant.append(h)
        else:
            independent.append(h)
    tr = self.compare_any(cust, latin + independent, entity_type, customer_entity_type)
    return NameAssessment(lit, tr, confirm_on_transliteration, independent, redundant)


NameMatcher.assess = assess  # type: ignore[attr-defined]
