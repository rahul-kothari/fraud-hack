"""Table-driven romanization for alphabets and the Hebrew abjad.

Each table maps a letter (or digraph, matched longest-first) to its Latin
alternatives, preferred first. Alternatives cover the national standards
(BGN/PCGN, ISO 9, Ukrainian and Serbian passport systems, ALA-LC, Armenian
and Georgian national systems) plus common informal / German / French
spellings seen on watchlists.
"""
from __future__ import annotations

import unicodedata

from ..lattice import Lattice

V = ("", "a", "e", "i", "o", "u")

CYRILLIC: dict[str, tuple[str, ...]] = {
    "а": ("a",), "б": ("b",), "в": ("v", "w"), "г": ("g", "h", "gh"), "ґ": ("g",),
    "д": ("d",), "е": ("e", "ye", "ie", "je"), "ё": ("yo", "e", "io", "jo", "ye"),
    "є": ("ye", "ie", "je", "e"), "ж": ("zh", "j", "z", "g", "s", "sh"), "з": ("z", "s"),
    "и": ("i", "y", "ee"), "і": ("i", "y"), "ї": ("yi", "i", "ji"), "й": ("y", "i", "j", ""),
    "к": ("k", "c", "ck"), "л": ("l",), "м": ("m",), "н": ("n",), "о": ("o", "a"),
    "п": ("p",), "р": ("r",), "с": ("s", "ss"), "т": ("t",), "у": ("u", "ou", "oo", "w"),
    "ў": ("w", "u", "v"), "ф": ("f", "ph"), "х": ("kh", "h", "ch", "x"),
    "ц": ("ts", "c", "tz", "z", "cz", "tc"), "ч": ("ch", "c", "tch", "tsch", "cz", "tsh"),
    "ш": ("sh", "s", "sch", "sz", "ch"), "щ": ("shch", "sch", "sh", "sht", "shtch", "szcz", "st"),
    "ъ": ("", "a", "u", "ie"), "ы": ("y", "i"), "ь": ("", "i", "y"), "э": ("e",),
    "ю": ("yu", "iu", "ju", "u", "you"), "я": ("ya", "ia", "ja", "a"),
    # Serbian / Macedonian
    "ђ": ("dj", "d", "gj", "dz"), "ј": ("j", "y", "i"), "љ": ("lj", "l", "ly"),
    "њ": ("nj", "n", "ny"), "ћ": ("c", "ch", "tj", "tch"), "џ": ("dz", "j", "dzh", "dj"),
    "ѓ": ("gj", "g", "dj"), "ќ": ("kj", "k", "c"), "ѕ": ("dz", "z"),
    # Kazakh / Central Asian extras
    "ә": ("a", "ae"), "ғ": ("g", "gh"), "қ": ("q", "k"), "ң": ("ng", "n"), "ө": ("o", "oe"),
    "ұ": ("u",), "ү": ("u", "ue"), "һ": ("h",), "ҳ": ("h",), "ӣ": ("i",), "ӯ": ("u",),
    "ҷ": ("j",), "ҡ": ("q", "k"),
    # digraphs and common endings
    "кс": ("ks", "x", "cs"), "ий": ("iy", "y", "ii", "i", "ij"), "ый": ("y", "iy", "yi", "yy", "i"),
    "ия": ("iya", "ia", "ija", "ya"), "ье": ("ye", "ie", "e"), "ьё": ("yo", "io"),
    "ъе": ("ye", "ie", "e"), "дж": ("dzh", "j", "dj", "dz"), "кх": ("kh",),
}
CYRILLIC_INITIAL = {"е": ("ye", "e", "ie", "je"), "є": ("ye", "e", "ie")}

GREEK: dict[str, tuple[str, ...]] = {
    "α": ("a",), "β": ("v", "b"), "γ": ("g", "gh", "y"), "δ": ("d", "dh", "th"), "ε": ("e",),
    "ζ": ("z",), "η": ("i", "e", "ee"), "θ": ("th", "t"), "ι": ("i", "y"), "κ": ("k", "c"),
    "λ": ("l",), "μ": ("m",), "ν": ("n",), "ξ": ("x", "ks"), "ο": ("o",), "π": ("p",),
    "ρ": ("r",), "σ": ("s",), "ς": ("s",), "τ": ("t",), "υ": ("y", "i", "u"),
    "φ": ("f", "ph"), "χ": ("ch", "kh", "h", "x"), "ψ": ("ps",), "ω": ("o",),
    "ου": ("ou", "u"), "αι": ("ai", "e"), "ει": ("ei", "i"), "οι": ("oi", "i"), "υι": ("yi", "i"),
    "μπ": ("b", "mp"), "ντ": ("d", "nt"), "γγ": ("ng", "gg"), "γκ": ("g", "gk", "nk"),
    "αυ": ("av", "af", "au"), "ευ": ("ev", "ef", "eu"), "τζ": ("tz", "dz", "j"), "τσ": ("ts",),
}

ARMENIAN: dict[str, tuple[str, ...]] = {
    "ա": ("a",), "բ": ("b", "p"), "գ": ("g", "k"), "դ": ("d", "t"), "ե": ("e", "ye", "ie"),
    "զ": ("z",), "է": ("e",), "ը": ("y", "e", "u", ""), "թ": ("t", "th"), "ժ": ("zh", "j"),
    "ի": ("i",), "լ": ("l",), "խ": ("kh", "x", "h", "kh"), "ծ": ("ts", "tz", "c", "dz"),
    "կ": ("k", "g"), "հ": ("h",), "ձ": ("dz", "ts", "tz"), "ղ": ("gh", "g", "r", "x"),
    "ճ": ("ch", "tch", "j", "dj"), "մ": ("m",), "յ": ("y", "i", "h", ""), "ն": ("n",),
    "շ": ("sh",), "ո": ("o", "vo", "va"), "չ": ("ch", "tch"), "պ": ("p", "b"),
    "ջ": ("j", "dj", "ch"), "ռ": ("r", "rr"), "ս": ("s",), "վ": ("v",), "տ": ("t", "d"),
    "ր": ("r",), "ց": ("ts", "c", "tz"), "փ": ("p", "ph"), "ք": ("k", "q", "kh"),
    "օ": ("o",), "ֆ": ("f",), "ու": ("u", "ou", "oo"), "և": ("ev", "yev", "yev"),
}
ARMENIAN_INITIAL = {"ե": ("ye", "e", "ie"), "ո": ("vo", "o", "vo")}

GEORGIAN: dict[str, tuple[str, ...]] = {
    "ა": ("a",), "ბ": ("b",), "გ": ("g",), "დ": ("d",), "ე": ("e",), "ვ": ("v", "w"),
    "ზ": ("z",), "თ": ("t", "th"), "ი": ("i",), "კ": ("k",), "ლ": ("l",), "მ": ("m",),
    "ნ": ("n",), "ო": ("o",), "პ": ("p",), "ჟ": ("zh", "j"), "რ": ("r",), "ს": ("s",),
    "ტ": ("t",), "უ": ("u", "ou"), "ფ": ("p", "ph", "f"), "ქ": ("k", "q", "kh"),
    "ღ": ("gh", "g"), "ყ": ("q", "k", "y"), "შ": ("sh", "ch"), "ჩ": ("ch", "tch"),
    "ც": ("ts", "c", "tz"), "ძ": ("dz",), "წ": ("ts", "tz", "c"), "ჭ": ("ch", "tch"),
    "ხ": ("kh", "x", "h"), "ჯ": ("j", "dj"), "ჰ": ("h",),
}

HEBREW: dict[str, tuple[str, ...]] = {
    "א": ("", "a", "e"), "ב": ("b", "v"), "ג": ("g",), "ד": ("d",), "ה": ("h", "", "a", "e"),
    "ו": ("v", "o", "u", "w"), "ז": ("z",), "ח": ("h", "kh", "ch"), "ט": ("t",),
    "י": ("y", "i", "e", "ee", "j", "ei", "ai"), "כ": ("k", "kh", "ch"), "ך": ("k", "kh", "ch"),
    "ל": ("l",), "מ": ("m",), "ם": ("m",), "נ": ("n",), "ן": ("n",), "ס": ("s",),
    "ע": ("", "a", "e"), "פ": ("p", "f", "ph"), "ף": ("f", "p"), "צ": ("ts", "tz", "z", "s", "c"),
    "ץ": ("ts", "tz", "z"), "ק": ("k", "q", "c"), "ר": ("r",), "ש": ("sh", "s"), "ת": ("t", "th"),
    "וו": ("v", "w", "vv"), "יי": ("y", "yy", "ei", "ai"),
    # geresh forms (letter + ׳ or ')
    "ג'": ("j", "g", "dj"), "ז'": ("zh", "j"), "צ'": ("ch", "tsh"), "ע'": ("gh", "g", "r"),
    "ת'": ("th", "t"), "ח'": ("kh", "h"), "ד'": ("dh", "d"), "ט'": ("z", "dh"),
    "ג׳": ("j", "g", "dj"), "ז׳": ("zh", "j"), "צ׳": ("ch", "tsh"), "ע׳": ("gh", "g", "r"),
    "ת׳": ("th", "t"), "ח׳": ("kh", "h"), "ד׳": ("dh", "d"), "ט׳": ("z", "dh"),
}
HEBREW_VOWEL_LETTERS = set("אהויע")


def _strip_marks(word: str) -> str:
    """Remove combining accents/niqqud (Greek tonos, Hebrew points)."""
    return "".join(c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) != "Mn")


def _double(alts: tuple[str, ...]) -> tuple[str, ...]:
    out = list(alts)
    for a in alts:
        if len(a) == 1 and a not in "aeiou":
            out.append(a + a)
    return tuple(out)


def _table_lattice(word: str, table: dict[str, tuple[str, ...]], script: str,
                   initial: dict[str, tuple[str, ...]] | None = None,
                   abjad: bool = False) -> list[Lattice]:
    w = word.lower()
    if script in ("Greek", "Hebrew"):
        w = _strip_marks(w)
    if script == "Cyrillic":
        # NFC so that й/ё keep their identity (do not strip their marks)
        w = unicodedata.normalize("NFC", w)
    keys = sorted(table, key=len, reverse=True)
    slots: list[tuple[str, ...]] = []
    i = 0
    prev_letter = False
    while i < len(w):
        for k in keys:
            if w.startswith(k, i):
                alts = table[k]
                if i == 0 and initial and k in initial:
                    alts = initial[k]
                if abjad:
                    if prev_letter:
                        slots.append(V)
                    if not (set(k) & HEBREW_VOWEL_LETTERS):
                        alts = _double(alts)
                else:
                    alts = _double(alts) if script != "Greek" else alts
                slots.append(alts)
                i += len(k)
                prev_letter = True
                break
        else:
            i += 1  # unknown mark/punctuation: skip
    return [Lattice(slots, source=word, script=script)] if slots else []


def cyrillic(word: str) -> list[Lattice]:
    return _table_lattice(word, CYRILLIC, "Cyrillic", CYRILLIC_INITIAL)


def greek(word: str) -> list[Lattice]:
    return _table_lattice(word, GREEK, "Greek")


def armenian(word: str) -> list[Lattice]:
    return _table_lattice(word, ARMENIAN, "Armenian", ARMENIAN_INITIAL)


def georgian(word: str) -> list[Lattice]:
    return _table_lattice(word, GEORGIAN, "Georgian")


def hebrew(word: str) -> list[Lattice]:
    return _table_lattice(word.replace("׳", "׳"), HEBREW, "Hebrew", abjad=True)
