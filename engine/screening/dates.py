"""Partial dates and the date-of-birth rules (POLICY principles 6 and 7)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})
MONTHS["sept"] = 9
_MON = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?"


@dataclass(frozen=True, order=True)
class PDate:
    """A date where month and day may be unknown."""
    year: int
    month: int | None = None
    day: int | None = None

    @staticmethod
    def from_iso(s: str | None) -> "PDate | None":
        if not s:
            return None
        m = re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", s.strip())
        if not m:
            return None
        y, mo, d = m.groups()
        return PDate(int(y), int(mo) if mo else None, int(d) if d else None)

    @property
    def full(self) -> bool:
        return self.month is not None and self.day is not None

    def iso(self) -> str:
        s = f"{self.year:04d}"
        if self.month:
            s += f"-{self.month:02d}"
            if self.day:
                s += f"-{self.day:02d}"
        return s

    def __str__(self) -> str:
        return self.iso()

    def earliest(self) -> tuple[int, int, int]:
        return (self.year, self.month or 1, self.day or 1)

    def latest(self) -> tuple[int, int, int]:
        return (self.year, self.month or 12, self.day or 31)


# ---------------------------------------------------------------- text dates

_PATTERNS = [
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "dmy"),
    (re.compile(rf"\b({_MON}) (\d{{1,2}}),? (\d{{4}})\b"), "Mdy"),
    (re.compile(rf"\b(\d{{1,2}}) ({_MON}),? (\d{{4}})\b"), "dMy"),
    (re.compile(rf"\b({_MON}),? (\d{{4}})\b"), "My"),
]


def _month(word: str) -> int | None:
    return MONTHS.get(word.lower().rstrip("."))


def find_dates(text: str) -> list[tuple[PDate, tuple[int, int], str]]:
    """All dates in text as (PDate, span, matched text), most specific match wins, in text order."""
    found: list[tuple[PDate, tuple[int, int], str]] = []
    taken: list[tuple[int, int]] = []
    for rx, kind in _PATTERNS:
        for m in rx.finditer(text or ""):
            a, b = m.span()
            if any(a < tb and b > ta for ta, tb in taken):
                continue
            g = m.groups()
            try:
                if kind == "ymd":
                    p = PDate(int(g[0]), int(g[1]), int(g[2]))
                elif kind == "dmy":
                    p = PDate(int(g[2]), int(g[1]), int(g[0]))
                elif kind == "Mdy":
                    p = PDate(int(g[2]), _month(g[0]), int(g[1]))
                elif kind == "dMy":
                    p = PDate(int(g[2]), _month(g[1]), int(g[0]))
                else:
                    p = PDate(int(g[1]), _month(g[0]))
            except (TypeError, ValueError):
                continue
            if p.month and not 1 <= p.month <= 12 or p.day and not 1 <= p.day <= 31:
                continue
            found.append((p, (a, b), m.group(0)))
            taken.append((a, b))
    return sorted(found, key=lambda x: x[1][0])


def parse_one(text: str | None) -> PDate | None:
    if not text:
        return None
    if p := PDate.from_iso(text):
        return p
    ds = find_dates(text)
    return ds[0][0] if ds else None


# ------------------------------------------------------------ birth date specs

@dataclass(frozen=True)
class BirthSpec:
    """One birth date a hit gives: a set of possible years (2 when derived from an age) and maybe month/day."""
    years: frozenset[int]
    month: int | None = None
    day: int | None = None
    source: str = ""          # "dobs", "profile_notes" or a search result id
    note: str = field(default="", compare=False)

    @staticmethod
    def exact(p: PDate, source: str, note: str = "") -> "BirthSpec":
        return BirthSpec(frozenset({p.year}), p.month, p.day, source, note)

    @staticmethod
    def from_age(age: int, at: PDate, source: str, note: str = "") -> "BirthSpec":
        # Someone aged 45 in March 2019 was born in 1973 or 1974.
        return BirthSpec(frozenset({at.year - age - 1, at.year - age}), None, None, source, note)

    def describe(self) -> str:
        ys = sorted(self.years)
        if len(ys) == 1:
            return PDate(ys[0], self.month, self.day).iso()
        return " or ".join(str(y) for y in ys)


def dob_agrees(c: PDate, h: BirthSpec) -> bool:
    """Principle 7: customer's year is one of the hit's years and every part both give is equal."""
    if c.year not in h.years:
        return False
    if c.month and h.month and c.month != h.month:
        return False
    if c.day and h.day and c.day != h.day:
        return False
    return True


def dob_contradicts(c: PDate, h: BirthSpec) -> bool:
    """Principle 6: year more than 1 outside, or same year with differing month (or day)."""
    if min(abs(c.year - y) for y in h.years) > 1:
        return True
    if c.year in h.years and c.month and h.month:
        if c.month != h.month:
            return True
        if c.day and h.day and c.day != h.day:
            return True
    return False


def max_age_at(dob: PDate, at: PDate) -> int:
    """The oldest the person could be on `at` given what is known of their birth date."""
    by, bm, bd = dob.earliest()
    ay, am, ad = at.latest()
    return ay - by - (1 if (am, ad) < (bm, bd) else 0)
