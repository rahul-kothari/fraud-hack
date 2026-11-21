"""Facts from free text: KYC notes, residence notes, hit profile notes, search snippets.

Each extractor tries deterministic regex first. When regex can't fill a required field and a Grok
client is available, it asks Grok (see grok.py). Every fact records how it was obtained ("regex" or
"grok"), so the evaluation can show which method produced it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import countries
from .dates import BirthSpec, PDate, find_dates, parse_one
from .grok import Grok

PROVIDERS = ["Companies registry lookup", "Sumsub", "Veriff", "Persona", "Onfido"]
DOC_TYPES = ["driving licence", "national ID", "passport", "registry extract"]

# Principle 5: kind of listing by primary (or first) category. Worded the same in the unseen set.
LISTING_PHRASES = {
    "Sanctions": "a sanctioned individual",
    "PEP": "a politically exposed person",
    "Enforcement": "the subject of enforcement action",
    "Adverse Media": "named in adverse media",
    "SOE": "a state-owned enterprise official",
}
OTHER_LISTING = "named on a watchlist"
ALL_LISTING_PHRASES = list(LISTING_PHRASES.values()) + [OTHER_LISTING]

_MONTHS = ("January|February|March|April|May|June|July|August|September|October|November|December")
DATED_REPORT = re.compile(rf"^According to .+?; ((?:{_MONTHS}) \d{{1,2}}, \d{{4}}): ", re.M)


# ------------------------------------------------------------------ KYC notes

@dataclass
class KycNote:
    note_id: str
    name: str | None
    dob: PDate | None
    document_country: str | None
    checked_at: PDate | None
    approved: bool
    method: str


_NOT_NAME = {"ID", "DOB", "KYC", "AML", "US", "UK", "USA"}
_YEAR_DOB = re.compile(r"(?:dob|born|date of birth(?: of)?|birth date(?: of)?)\W{0,3}(\d{4})\b(?![-/])", re.I)


def _caps_name(text: str) -> str | None:
    """Longest run of consecutive all-capitals words (Unicode aware: keeps Ć, Ø, ...)."""
    best, run = None, []
    for tok in re.findall(r"[^\W\d_][^\W\d_'’\-]*(?:['’\-][^\W\d_]+)*(?:['’]s)?|\S+", text) + [""]:
        core = re.sub(r"['’]s$", "", tok)
        if len(core) >= 2 and core.isupper() and core not in _NOT_NAME and re.fullmatch(r"[^\W\d_'’\-]+(?:['’\-][^\W\d_]+)*", core):
            run.append(core)
            if not tok.endswith(("'s", "’s")):
                continue
        if run and (best is None or len(" ".join(run)) > len(best)):
            best = " ".join(run)
        run = []
    return best


def parse_kyc_note(note: dict, grok: Grok | None) -> KycNote | None:
    text = note["text"] or ""
    name = _caps_name(text)
    created = PDate.from_iso(note["created_at"])
    dob = checked = None
    dated = find_dates(text)
    for p, span, raw in dated:
        before = text[max(0, span[0] - 25):span[0]].lower()
        if p == created and checked is None:
            checked = p                      # the check date equals the note's filing date
        elif dob is None and re.search(r"(dob|born|birth date|date of birth)\W{0,3}(of\W)?(on\W)?$", before):
            dob = p
    if dob is None and (m := _YEAR_DOB.search(text)):
        dob = PDate(int(m.group(1)))         # year-only date of birth ("born 1966", "DOB 1960")
    if dob is None:                          # no keyword: the one date that is not the check date
        rest = [p for p, _, _ in dated if p != checked]
        dob = rest[0] if len(rest) == 1 else None
    found = countries.find_in_text(text)
    doc_country = found[0] if found else None
    method = "regex"
    if (not name or not dob or not doc_country) and grok is not None:
        g = grok.extract("kyc_note", text)
        if g:
            method = "grok"
            name = name or g.get("name")
            dob = dob or parse_one(g.get("dob"))
            doc_country = doc_country or countries.norm(g.get("document_country"))
            if g.get("approved") is False:
                return KycNote(note["note_id"], name, dob, doc_country, checked or created, False, method)
    if not name and not dob:
        return None
    return KycNote(note["note_id"], name, dob, doc_country, checked or created, True, method)


# ------------------------------------------------------------- residence notes

def parse_residence_note(note: dict, grok: Grok | None) -> list[str]:
    """Countries a support note ties the customer to. Every non-KYC note that names a country is a
    residence note in this data (routine notes never name one), so any country found counts. Erring
    this way is safe: an extra customer country can only block a LOCATION_MISMATCH clearance.
    Grok is asked only when regex finds no country but the text looks like a residence statement."""
    text = note["text"] or ""
    if note["channel"] == "kyc":
        return []
    found = countries.find_in_text(text)
    if found:
        return found
    if grok is not None and re.search(r"\b(19|20)\d\d\b", text) and not text.startswith("Customer "):
        g = grok.extract("residence_note", text)
        if g:
            return [c for c in (countries.norm(x) for x in g.get("countries", [])) if c]
    return []


# ---------------------------------------------------------------- ages in text

_AGE_PATTERNS = [
    r"\baged (\d{1,3})\b", r"\b(\d{1,3})[- ]years?[- ]old\b", r"\bage of (\d{1,3})\b",
    r"\b(?:he|she|they) (?:was|were) (\d{1,3})\b(?! (?:years|percent|million))",
    r"\bAt (\d{1,3}),", r"\(aged? ?(\d{1,3})\)", r"\((\d{1,3})\)",
    r"\bwho was (\d{1,3})\b", r"\btime (?:he|she|they) (?:was|were) (\d{1,3})\b",
    r"[^\W\d_\)], (\d{1,3}),",
    r"\bwas (\d{1,3}) (?:when|at the time)\b", r"\bsubject was (\d{1,3})\b", r"\bat (?:age )?(\d{1,3}),",
    r"\bthen (\d{1,3}),", r"\breached (\d{1,3}) years of age\b", r"\bThe age of [^.]{1,60}? was (\d{1,3})\b",
]
_AGE_RX = [re.compile(p) for p in _AGE_PATTERNS]


def _ages(text: str) -> list[int]:
    out = []
    for rx in _AGE_RX:
        for m in rx.finditer(text):
            a = int(m.group(1))
            if 1 <= a <= 120 and a not in out:
                out.append(a)
    return out


def _age_at_date(text: str) -> tuple[int, PDate] | None:
    ages = _ages(text)
    dates = [p for p, _, _ in find_dates(text)]
    if len(ages) == 1 and len(set(dates)) == 1:
        return ages[0], dates[0]
    return None


# --------------------------------------------------------------- hit profiles

@dataclass
class ProfileDob:
    spec: BirthSpec
    method: str
    sentence: str


def first_paragraph(profile_notes: str | None) -> str:
    if not profile_notes:
        return ""
    return re.split(r"\n\s*\n", profile_notes.strip(), maxsplit=1)[0].strip()


_BORN = re.compile(r"\bborn(?: on| in)? ", re.I)
_SKIP_PARA = re.compile(r"^(Career|Political Party|Description|Sanctions ownership|Partido|Trayectoria)", re.I)


def profile_dob(hit: dict, grok: Grok | None) -> ProfileDob | None:
    para = first_paragraph(hit.get("profile_notes"))
    if not para or _SKIP_PARA.match(para):
        return None
    if m := _BORN.search(para):
        ds = find_dates(para[m.end():m.end() + 30])
        if ds:
            return ProfileDob(BirthSpec.exact(ds[0][0], "profile_notes", para), "regex", para)
    if para.startswith(("According to", "On ")) and not _ages(para):
        return None  # a dated report or designation notice, no age in it
    if got := _age_at_date(para):
        age, at = got
        return ProfileDob(BirthSpec.from_age(age, at, "profile_notes", para), "regex", para)
    if grok is not None and len(para) < 600 and re.search(r"\b\d{1,3}\b", para):
        g = grok.extract("age_sentence", para)
        if g and g.get("kind") == "birth_date" and (p := parse_one(g.get("birth_date"))):
            return ProfileDob(BirthSpec.exact(p, "profile_notes", para), "grok", para)
        if g and g.get("kind") == "age_at_date" and g.get("age") and (p := parse_one(g.get("at_date"))):
            return ProfileDob(BirthSpec.from_age(int(g["age"]), p, "profile_notes", para), "grok", para)
    return None


def earliest_dated_report(hit: dict) -> tuple[PDate, str] | None:
    """Principle 5: only English lines 'According to …; Month D, YYYY: …' count."""
    best = None
    for m in DATED_REPORT.finditer(hit.get("profile_notes") or ""):
        p = parse_one(m.group(1))
        if p and (best is None or p < best[0]):
            line = (hit["profile_notes"][m.start():].split("\n", 1)[0])[:200]
            best = (p, line)
    return best


def listing_phrase(hit: dict) -> str:
    cat = hit.get("primary_category") or (hit.get("categories") or [None])[0]
    return LISTING_PHRASES.get(cat, OTHER_LISTING)


def search_query(name: str) -> str:
    """Search results are keyed by the name's lowercase words in alphabetical order (accents removed)."""
    import unicodedata
    plain = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    words = re.sub(r"[^\w\s]", " ", plain.lower()).split()
    return " ".join(sorted(w for w in words if len(w) > 1))   # initials are not name parts


@dataclass
class SnippetDob:
    result_id: str
    spec: BirthSpec
    country: str
    method: str


def search_dobs(hit: dict, results: list[dict], grok: Grok | None) -> list[SnippetDob]:
    """Search results about the hit (same listing kind in a country tied to the hit) -> birth years."""
    phrase = listing_phrase(hit)
    tied = set(hit.get("countries_tied") or [])
    out = []
    for r in results:
        snip = r["snippet"] or ""
        if phrase not in snip:
            continue
        place = [c for c in countries.find_in_text(snip) if c in tied]
        if not place:
            continue
        method = "regex"
        got = _age_at_date(snip)
        if got is None and grok is not None:
            g = grok.extract("search_snippet", snip)
            if g and g.get("age") and (p := parse_one(g.get("at_date"))):
                got, method = (int(g["age"]), p), "grok"
        if got:
            age, at = got
            out.append(SnippetDob(r["result_id"], BirthSpec.from_age(age, at, r["result_id"], snip),
                                  place[0], method))
    return out
