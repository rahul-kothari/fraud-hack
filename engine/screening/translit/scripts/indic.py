"""Brahmic abugidas -> romanization lattice.

Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil, Telugu, Kannada and
Malayalam share one layout (offsets from the block start line up), so a
single offset table drives all of them, with per-script overrides.

Each consonant carries an inherent vowel unless a vowel sign or virama
follows. Whether that vowel is pronounced (schwa deletion) and how it is
spelled (Hindi a/e, Bengali o/a) varies, so it is an optional slot.
"""
from __future__ import annotations

from ..lattice import Lattice

BLOCKS = {
    0x0900: "Devanagari", 0x0980: "Bengali", 0x0A00: "Gurmukhi", 0x0A80: "Gujarati",
    0x0B00: "Oriya", 0x0B80: "Tamil", 0x0C00: "Telugu", 0x0C80: "Kannada", 0x0D00: "Malayalam",
}

# offset -> alternatives
INDEPENDENT_VOWELS = {
    0x05: ("a", "o"), 0x06: ("a", "aa"), 0x07: ("i", "e"), 0x08: ("i", "ee"), 0x09: ("u", "o"),
    0x0A: ("u", "oo"), 0x0B: ("ri", "ru", "r"), 0x0C: ("li",), 0x0D: ("e", "ai"), 0x0E: ("e",),
    0x0F: ("e", "a", "ay"), 0x10: ("ai", "oi", "e"), 0x11: ("o",), 0x12: ("o",), 0x13: ("o",),
    0x14: ("au", "ou", "ow"),
}
CONSONANTS = {
    0x15: ("k", "c", "q"), 0x16: ("kh", "k"), 0x17: ("g",), 0x18: ("gh", "g"), 0x19: ("ng", "n"),
    0x1A: ("ch", "c"), 0x1B: ("chh", "ch"), 0x1C: ("j", "z"), 0x1D: ("jh", "j", "z"),
    0x1E: ("ny", "n"), 0x1F: ("t",), 0x20: ("th", "t"), 0x21: ("d", "r"), 0x22: ("dh", "d", "rh"),
    0x23: ("n",), 0x24: ("t",), 0x25: ("th", "t"), 0x26: ("d",), 0x27: ("dh", "d"), 0x28: ("n",),
    0x29: ("n",), 0x2A: ("p",), 0x2B: ("ph", "f"), 0x2C: ("b", "v", "w"), 0x2D: ("bh", "b", "v"),
    0x2E: ("m",), 0x2F: ("y", "j"), 0x30: ("r",), 0x31: ("r",), 0x32: ("l",), 0x33: ("l",),
    0x34: ("l", "zh"), 0x35: ("v", "w", "b"), 0x36: ("sh", "s"), 0x37: ("sh", "s"),
    0x38: ("s", "sh"), 0x39: ("h",),
    # nukta / extra letters (Devanagari 0x58.., Bengali 0x5C..)
    0x58: ("q", "k"), 0x59: ("kh",), 0x5A: ("gh", "g"), 0x5B: ("z", "j"), 0x5C: ("r", "d"),
    0x5D: ("rh",), 0x5E: ("f", "ph"), 0x5F: ("y", ""), 0x4E: ("t",),
}
VOWEL_SIGNS = {
    0x3E: ("a", "aa"), 0x3F: ("i", "e"), 0x40: ("i", "ee", "e"), 0x41: ("u", "o"),
    0x42: ("u", "oo"), 0x43: ("ri", "ru", "r"), 0x44: ("ri",), 0x45: ("e", "ai"), 0x46: ("e",),
    0x47: ("e", "ay", "ai", "a", "ae"), 0x48: ("ai", "ae", "e", "oi"), 0x49: ("o",),
    0x4A: ("o",), 0x4B: ("o", "u"), 0x4C: ("au", "ou", "ow"), 0x57: ("au",),
    0x62: ("li",), 0x63: ("li",),
}
NUKTA_MAP = {0x15: ("q", "k"), 0x16: ("kh",), 0x17: ("gh", "g"), 0x1C: ("z", "j"),
             0x21: ("r", "d"), 0x22: ("rh",), 0x2B: ("f", "ph"), 0x2F: ("y", "")}
VIRAMA = 0x4D
NUKTA = 0x3C
ANUSVARA, CANDRABINDU, VISARGA = 0x02, 0x01, 0x03

INHERENT = {
    "Devanagari": ("a", "e", ""), "Gurmukhi": ("a", "e", ""), "Bengali": ("o", "a", ""),
    "Oriya": ("o", "a", ""), "Gujarati": ("a", ""), "Tamil": ("a", ""), "Telugu": ("a", ""),
    "Kannada": ("a", ""), "Malayalam": ("a", ""),
}
SCRIPT_OVERRIDES = {
    # Bengali has no separate va; ব is b; য is j/z; জ often z in Muslim names; ে often ai/a
    "Bengali": {0x2F: ("j", "z", "y"), 0x1C: ("j", "z"), 0x38: ("s", "sh"), 0x36: ("sh", "s"),
                0x2C: ("b", "v", "w"), 0x1B: ("chh", "ch", "s"), 0x5F: ("y", "")},
    "Tamil": {0x15: ("k", "g", "h"), 0x1A: ("ch", "s", "c"), 0x1F: ("t", "d"), 0x24: ("t", "th", "d"),
              0x2A: ("p", "b"), 0x31: ("r", "t", "tr")},
}
# common abbreviations: Bengali মো./মোঃ and Hindi मो. for Mohammad, written "Md"
# (romanized as "Md", exactly as the Latin abbreviation, which the SOP does not
# list as a variant of Muhammad)
ABBREVIATIONS = {"মো": ("md",), "মোঃ": ("md",), "मो": ("md",), "मोह": ("md",)}


def block_of(ch: str) -> int | None:
    cp = ord(ch)
    base = cp & ~0x7F
    return base if base in BLOCKS else None


def word_lattices(word: str) -> list[Lattice]:
    stripped = word.rstrip(".").strip()
    if stripped in ABBREVIATIONS and ABBREVIATIONS[stripped]:
        return [Lattice([ABBREVIATIONS[stripped]], source=word, script="Indic")]
    chars = [c for c in stripped if block_of(c) is not None]
    if not chars:
        return []
    script = BLOCKS[block_of(chars[0])]  # type: ignore[index]
    overrides = SCRIPT_OVERRIDES.get(script, {})
    inherent = INHERENT.get(script, ("a", ""))
    slots: list[tuple[str, ...]] = []
    i = 0
    n = len(chars)
    while i < n:
        off = ord(chars[i]) - block_of(chars[i])  # type: ignore[operator]
        nxt = ord(chars[i + 1]) - block_of(chars[i + 1]) if i + 1 < n else None  # type: ignore[operator]
        if off in CONSONANTS or (script == "Bengali" and off == 0x4E):
            alts = overrides.get(off, CONSONANTS.get(off, ("t",)))
            if nxt == NUKTA:
                alts = NUKTA_MAP.get(off, alts)
                i += 1
                nxt = ord(chars[i + 1]) - block_of(chars[i + 1]) if i + 1 < n else None  # type: ignore[operator]
            # Latin often doubles a consonant written once (Hussain, Muhammad)
            slots.append(tuple(alts) + tuple(a + a[-1] for a in alts if len(a) == 1))
            if nxt == VIRAMA:
                i += 2
                continue
            if nxt is not None and nxt in VOWEL_SIGNS:
                slots.append(VOWEL_SIGNS[nxt])
                i += 2
                continue
            if off == 0x4E:  # khanda ta has no vowel
                i += 1
                continue
            # inherent vowel; at the end of a word it is usually silent
            slots.append(("",) + inherent[:-1] if nxt is None else inherent)
            i += 1
            continue
        if off in INDEPENDENT_VOWELS:
            slots.append(INDEPENDENT_VOWELS[off])
        elif off in (ANUSVARA,):
            slots.append(("n", "m", "ng", ""))
        elif off == CANDRABINDU:
            slots.append(("n", "", "m"))
        elif off == VISARGA:
            slots.append(("", "h"))
        elif off in VOWEL_SIGNS:  # stray sign
            slots.append(VOWEL_SIGNS[off])
        i += 1
    return [Lattice(slots, source=word, script=script)] if slots else []
