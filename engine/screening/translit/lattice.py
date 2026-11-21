"""Romanization lattice: the core of the transliteration model.

A native-script word has many plausible Latin spellings. Arabic and Hebrew
omit short vowels, Bengali has an inherent vowel that may or may not be
written, and every script has several romanization conventions (Cyrillic
``х`` is kh / h / ch / x). Instead of guessing one spelling, we keep them all
as a *lattice*: a sequence of slots, each slot a small set of alternative
Latin strings (the empty string means "optional").

The language of the lattice is every concatenation that picks one
alternative per slot. A Latin name part is compared against the lattice by
the edit distance to the *closest* string in that language, computed
exactly with an approximate NFA match (no enumeration). That distance is then
judged with the screening SOP's own budget, so a transliterated alias is held
to the same standard as a Latin alias.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import islice, product
from typing import Iterable, Iterator, Sequence


class Lattice:
    """A sequence of slots of alternative Latin strings."""

    __slots__ = ("slots", "source", "script", "display", "_nfa", "_hash")

    def __init__(self, slots: Iterable[Sequence[str]], source: str = "", script: str = "",
                 display: str | None = None):
        cleaned = []
        for slot in slots:
            alts = tuple(dict.fromkeys(a for a in slot))  # dedupe, keep order
            if not alts or alts == ("",):
                continue
            cleaned.append(alts)
        self.slots: tuple[tuple[str, ...], ...] = tuple(cleaned)
        self.source = source
        self.script = script
        self.display = display
        self._nfa = None
        self._hash = hash(self.slots)

    # ------------------------------------------------------------------ basics
    @classmethod
    def literal(cls, text: str, source: str = "", script: str = "Latin") -> "Lattice":
        return cls([(ch,) for ch in text], source=source or text, script=script)

    def __add__(self, other: "Lattice") -> "Lattice":
        return Lattice(self.slots + other.slots, source=f"{self.source}{other.source}",
                       script=self.script or other.script)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Lattice) and self.slots == other.slots

    def __hash__(self) -> int:
        return self._hash

    def __repr__(self) -> str:
        return f"Lattice({self.source!r} -> {self.canonical()!r})"

    def canonical(self) -> str:
        """The preferred romanization (dictionary spelling, else first alternatives)."""
        if self.display:
            return self.display
        return "".join(s[0] for s in self.slots)

    def is_empty(self) -> bool:
        return not self.slots

    def min_length(self) -> int:
        return sum(min(len(a) for a in s) for s in self.slots)

    def size(self) -> int:
        n = 1
        for s in self.slots:
            n *= len(s)
        return n

    def spellings(self, limit: int = 50) -> list[str]:
        """Enumerate up to ``limit`` distinct spellings, preferred ones first."""
        seen: dict[str, None] = {}
        for combo in islice(product(*self.slots), limit * 4):
            seen.setdefault("".join(combo), None)
            if len(seen) >= limit:
                break
        return list(seen)

    # ------------------------------------------------------------ edit distance
    def _build_nfa(self):
        """States are numbered in topological order; every edge goes forward.

        Returns (n_states, char_edges, eps_edges, final_state) where
        char_edges is a list of (src, dst, char) and eps_edges (src, dst).
        """
        char_edges: list[tuple[int, int, str]] = []
        eps_edges: list[tuple[int, int]] = []
        boundary = 0
        nxt = 1
        for slot in self.slots:
            ends: list[int] = []
            for alt in slot:
                if alt == "":
                    ends.append(-1)  # epsilon to the next boundary, patched below
                    continue
                prev = boundary
                for ch in alt[:-1]:
                    char_edges.append((prev, nxt, ch))
                    prev = nxt
                    nxt += 1
                ends.append((prev, alt[-1]))  # type: ignore[arg-type]
            new_boundary = nxt
            nxt += 1
            for e in ends:
                if e == -1:
                    eps_edges.append((boundary, new_boundary))
                else:
                    src, ch = e  # type: ignore[misc]
                    char_edges.append((src, new_boundary, ch))
            boundary = new_boundary
        # sort so that relaxation in index order respects topology
        char_edges.sort(key=lambda e: e[0])
        eps_edges.sort(key=lambda e: e[0])
        return nxt, char_edges, eps_edges, boundary

    def distance(self, text: str, cap: int = 99, vowel_free: bool = False) -> int:
        """Minimum Levenshtein distance from ``text`` to any spelling.

        Approximate NFA matching: dist[q] is the cheapest way to have consumed
        a prefix of ``text`` and reached state q. Moves: match/substitute along
        a char edge (consumes one text char), skip a lattice char (insertion,
        cost 1), drop a text char (deletion, cost 1), epsilon (cost 0).
        With ``vowel_free`` a vowel may replace another vowel at no cost.
        """
        return _distance(self, text, cap, vowel_free)

    def nfa(self):
        if self._nfa is None:
            self._nfa = self._build_nfa()
        return self._nfa


_VOWELS = frozenset("aeiouy")


@lru_cache(maxsize=200_000)
def _distance(lat: Lattice, text: str, cap: int, vowel_free: bool = False) -> int:
    n, char_edges, eps_edges, final = lat.nfa()
    inf = cap + 1
    # merged, index-ordered edge list for the closure pass: (src, dst, cost)
    closure = sorted([(s, d, 1) for s, d, _ in char_edges] + [(s, d, 0) for s, d in eps_edges])

    def close(dist: list[int]) -> None:
        for s, d, c in closure:
            v = dist[s] + c
            if v < dist[d]:
                dist[d] = v

    dist = [inf] * n
    dist[0] = 0
    close(dist)
    for ch in text:
        new = [min(inf, d + 1) for d in dist]  # delete ch from text
        for s, d, label in char_edges:
            v = dist[s] + (0 if label == ch or (vowel_free and label in _VOWELS and ch in _VOWELS) else 1)
            if v < new[d]:
                new[d] = v
        close(new)
        dist = new
        if min(dist) > cap:
            return inf
    return min(dist[final], inf)


def levenshtein(a: str, b: str) -> int:
    """Plain Levenshtein distance (a swap of two letters costs 2)."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def iter_slots(*groups: Sequence[str]) -> Iterator[tuple[str, ...]]:
    for g in groups:
        yield tuple(g)
