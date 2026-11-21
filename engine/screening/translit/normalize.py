"""Turn a raw name string into SOP name parts.

Principle 8: compare name parts ignoring case, accents, punctuation and
anything in brackets; single letters are initials, not parts; each distinct
part counts once; placeholders (NA, N/A, TEST, UNKNOWN, XXX, NONE, digits and
the like) are not parts; for companies the legal forms are not parts.

Tokens written in another script are transliterated into romanization
lattices (see ``lattice.py``) so they can be compared with Latin parts.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from .lattice import Lattice
from .scripts import alphabetic, arabic, eastasian, indic
from .variants import Variants, default_variants

try:
    from anyascii import anyascii as _anyascii
except Exception:  # pragma: no cover
    _anyascii = None

# ---------------------------------------------------------------- constants
BRACKETS = re.compile(r"[\(\[\{（［｛【][^\)\]\}）］｝】]*[\)\]\}）］｝】]")
APOSTROPHES = "'’‘`´ʼʻʽʾʿˈ׳"
SEPARATORS = re.compile(r"[\s,;:/\\|&+_.·・•‧\-‐‑‒–—―\"“”„«»!?@#*=~<>،؛​　、。]+")
PLACEHOLDERS = {
    "na", "test", "tests", "testing", "unknown", "unk", "none", "null", "nil", "tbd", "tba",
    "fnu", "lnu", "nfn", "nmn", "dummy", "notknown", "noname", "nn", "nan", "void", "sample",
}
SPECIAL_FOLD = {
    "ß": "ss", "ẞ": "ss", "æ": "ae", "Æ": "ae", "œ": "oe", "Œ": "oe", "ø": "o", "Ø": "o",
    "đ": "d", "Đ": "d", "ð": "d", "Ð": "d", "þ": "th", "Þ": "th", "ł": "l", "Ł": "l",
    "ı": "i", "ŋ": "ng", "ħ": "h", "ĸ": "k", "ſ": "s", "ƒ": "f", "ǝ": "e", "ə": "e", "ɛ": "e",
    "ɔ": "o", "ʃ": "sh", "ʒ": "zh",
}


# ------------------------------------------------------------- data classes
@dataclass(frozen=True)
class Part:
    """One SOP name part. Latin parts have ``lattice=None``."""
    text: str                       # normalised Latin (canonical romanization if transliterated)
    lattice: Lattice | None = None  # romanization lattice for transliterated parts
    source: str = ""                # the original token
    script: str = "Latin"

    @property
    def transliterated(self) -> bool:
        return self.lattice is not None

    def as_lattice(self) -> Lattice:
        return self.lattice if self.lattice is not None else Lattice.literal(self.text)

    def display(self) -> str:
        return f"{self.text} ({self.source})" if self.transliterated else self.text


@dataclass
class ParsedName:
    raw: str
    parts: list[Part] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (token, why)
    scripts: set[str] = field(default_factory=set)

    @property
    def transliterated(self) -> bool:
        return any(p.transliterated for p in self.parts)

    def texts(self) -> list[str]:
        return [p.text for p in self.parts]


# ---------------------------------------------------------------- scripts
def char_script(c: str) -> str | None:
    cp = ord(c)
    if cp < 0x80:
        if c.isalpha():
            return "Latin"
        if c.isdigit():
            return "Digit"
        return "Apos" if c in APOSTROPHES else None
    if c in APOSTROPHES:
        return "Apos"
    cat = unicodedata.category(c)
    if cat == "Nd":
        return "Digit"
    if cat in ("Mn", "Mc", "Me"):
        return "Mark"
    if 0x00C0 <= cp <= 0x024F or 0x1E00 <= cp <= 0x1EFF or 0x2C60 <= cp <= 0x2C7F or 0xA720 <= cp <= 0xA7FF \
            or 0x0250 <= cp <= 0x02AF:
        return "Latin"
    if 0x02B0 <= cp <= 0x02FF:
        return "Apos"
    if 0x0370 <= cp <= 0x03FF or 0x1F00 <= cp <= 0x1FFF:
        return "Greek"
    if 0x0400 <= cp <= 0x052F or 0x1C80 <= cp <= 0x1C8F or 0xA640 <= cp <= 0xA69F:
        return "Cyrillic"
    if 0x0530 <= cp <= 0x058F or 0xFB13 <= cp <= 0xFB17:
        return "Armenian"
    if 0x0590 <= cp <= 0x05FF or 0xFB1D <= cp <= 0xFB4F:
        return "Hebrew"
    if 0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F or 0x08A0 <= cp <= 0x08FF \
            or 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF:
        return "Arabic"
    if 0x0900 <= cp <= 0x0D7F:
        return "Indic"
    if 0x10A0 <= cp <= 0x10FF or 0x1C90 <= cp <= 0x1CBF or 0x2D00 <= cp <= 0x2D2F:
        return "Georgian"
    if 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F:
        return "Hangul"
    if 0x3040 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF:
        return "Kana"
    if eastasian.is_han(c):
        return "Han"
    return "Other" if c.isalpha() else None


def fold_latin(token: str) -> str:
    """Lowercase, strip accents, fold special letters, drop apostrophes/punctuation."""
    s = "".join(SPECIAL_FOLD.get(c, c) for c in token)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.casefold()
    return re.sub(r"[^a-z0-9]", "", s)


def _runs(token: str) -> list[tuple[str, str]]:
    """Split a token into (script, text) runs; marks/apostrophes stick to their run."""
    runs: list[list] = []
    for c in token:
        sc = char_script(c)
        if sc is None:
            continue
        if sc in ("Mark", "Apos"):
            if runs:
                runs[-1][1] += c
            continue
        if runs and runs[-1][0] == sc:
            runs[-1][1] += c
        else:
            runs.append([sc, c])
    return [(a, b) for a, b in runs]


def transliterate_run(script: str, text: str, personal_name: bool = True) -> list[Lattice]:
    if script == "Arabic":
        return arabic.word_lattices(text)
    if script == "Cyrillic":
        return alphabetic.cyrillic(text)
    if script == "Greek":
        return alphabetic.greek(text)
    if script == "Armenian":
        return alphabetic.armenian(text)
    if script == "Georgian":
        return alphabetic.georgian(text)
    if script == "Hebrew":
        return alphabetic.hebrew(text)
    if script == "Indic":
        return indic.word_lattices(text)
    if script == "Hangul":
        return eastasian.hangul(text)
    if script == "Kana":
        return eastasian.kana(text)
    if script == "Han":
        return eastasian.han(text, personal_name=personal_name)
    if _anyascii is not None:  # any other script: generic transliteration
        lat = fold_latin(_anyascii(text))
        return [Lattice.literal(lat, source=text, script=script)] if lat else []
    return []


# ------------------------------------------------------------------ parsing
def is_placeholder(text: str) -> bool:
    return (text in PLACEHOLDERS or text.isdigit() or bool(re.fullmatch(r"x{2,}", text))
            or bool(re.fullmatch(r"[0-9]+[a-z]?|[a-z]?[0-9]+", text) and sum(ch.isdigit() for ch in text) >= 3))


def parse_name(name: str | None, entity_type: str | None = None, *,
               variants: Variants | None = None, transliterate: bool = True) -> ParsedName:
    """Split a name into distinct SOP parts.

    ``entity_type``: "Company"/"Organisation"/"Entity" drops legal forms.
    ``transliterate``: if False, non-Latin tokens are dropped (literal SOP
    reading, where only Latin letters can be compared).
    """
    variants = variants or default_variants()
    raw = name or ""
    out = ParsedName(raw=raw)
    is_company = bool(entity_type) and entity_type.strip().lower() not in ("individual", "person", "")
    s = BRACKETS.sub(" ", raw)
    s = unicodedata.normalize("NFKC", s)
    tokens = [t for t in SEPARATORS.split(s) if t]
    seen: set = set()
    native_tokens = [t for t in tokens if any(char_script(c) not in (None, "Latin", "Digit", "Apos", "Mark")
                                              for c in t)]
    single_han_name = len(tokens) == 1 and len(native_tokens) == 1

    for tok in tokens:
        runs = _runs(tok)
        if not runs:
            continue
        scripts = {sc for sc, _ in runs}
        if scripts <= {"Latin", "Digit"}:
            text = fold_latin(tok)
            if not text:
                continue
            if is_placeholder(text):
                out.dropped.append((tok, "placeholder"))
                continue
            if len(text) == 1:
                out.dropped.append((tok, "initial"))
                continue
            if is_company and text in variants.legal_forms:
                out.dropped.append((tok, "legal form"))
                continue
            part = Part(text=text, source=tok)
        else:
            if not transliterate:
                out.dropped.append((tok, "non-Latin script"))
                continue
            lattices: list[Lattice] = []
            for sc, txt in runs:
                if sc == "Digit":
                    continue
                if sc == "Latin":
                    folded = fold_latin(txt)
                    if folded:
                        lattices.append(Lattice.literal(folded, source=txt))
                    continue
                out.scripts.add(sc)
                lattices += transliterate_run(sc, txt, personal_name=single_han_name and not is_company)
            if not lattices:
                out.dropped.append((tok, "not transliterable"))
                continue
            # one token -> one part, except Korean/Chinese personal names (surname + given)
            if len(runs) > 1:
                merged = lattices[0]
                for extra in lattices[1:]:
                    merged = merged + extra
                lattices = [merged]
            for lat in lattices:
                canon = lat.canonical()
                if len(canon) <= 1 and lat.min_length() <= 1 and not lat.source.strip() in indic.ABBREVIATIONS:
                    out.dropped.append((lat.source, "initial"))
                    continue
                if is_company and canon in variants.legal_forms:
                    out.dropped.append((lat.source, "legal form"))
                    continue
                part = Part(text=canon, lattice=lat, source=lat.source, script=lat.script)
                key = ("L", lat.slots)
                if key in seen:
                    continue
                seen.add(key)
                out.parts.append(part)
            continue
        key = ("T", part.text)
        if key in seen:
            continue
        seen.add(key)
        out.parts.append(part)
    return out
