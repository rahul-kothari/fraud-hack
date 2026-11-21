"""Read an official data folder (the organisers' JSON Lines layout, e.g. screening/dev/).

The organisers run `system/run <data folder> <output file>` against folders laid out like
dev/: alerts.jsonl, hits.jsonl, customers.jsonl, accounts.jsonl, onboarding.jsonl,
kyc_checks.jsonl, notes.jsonl, search_results.jsonl, name_variants.json and, for the dev set
only, practice_labels.jsonl. This module turns those rows into the shape the engine uses
(the shape prepare.py writes to processed/tables), deriving the same extra fields in memory:

    <field>_iso    a date parsed to partial ISO ("1980", "1980-05", "1980-05-19")
    <field>_norm   a country mapped to one canonical name
    countries_tied the hit's countries (POLICY principle 5)

Nothing is written to disk, and nothing outside the folder is read except the engine's own
country table. A file the folder lacks (practice_labels.jsonl on the unseen set) loads empty.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import countries

TABLES = ("alerts", "hits", "customers", "accounts", "onboarding", "kyc_checks", "notes",
          "search_results", "practice_labels")

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
_M = r"([A-Za-z]+)"


def parse_date(value: str | None) -> str | None:
    """A field date to partial ISO. dd/mm/yyyy is day-first, as in the bank's export
    (the first number exceeds 12 in thousands of rows, the second never does)."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if m := re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", v):
        y, mo, d = m.groups()
    elif m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v):
        d, mo, y = m.groups()
    elif m := re.fullmatch(rf"(\d{{1,2}}) {_M},? (\d{{4}})", v):
        d, mo, y = m.group(1), _MONTHS.get(m.group(2).lower()), m.group(3)
    elif m := re.fullmatch(rf"{_M} (\d{{1,2}}),? (\d{{4}})", v):
        mo, d, y = _MONTHS.get(m.group(1).lower()), m.group(2), m.group(3)
    elif m := re.fullmatch(rf"{_M},? (\d{{4}})", v):
        mo, d, y = _MONTHS.get(m.group(1).lower()), None, m.group(2)
    else:
        return None
    if mo is None and d is not None:
        return None
    if mo and not 1 <= int(mo) <= 12 or d and not 1 <= int(d) <= 31:
        return None
    out = f"{int(y):04d}"
    if mo:
        out += f"-{int(mo):02d}"
        if d:
            out += f"-{int(d):02d}"
    return out


def _last_part_country(value: str | None) -> str | None:
    """'Belgrade, Serbia' -> 'Serbia'; '..., Canada [Business]' -> 'Canada'."""
    v = re.sub(r"\[[^\]]*\]", "", value or "").strip()
    return countries.norm(v.split(",")[-1].strip()) if v else None


def split_top(value: str | None, sep: str = ";") -> list[str]:
    """Split on `sep` outside (...) and [...] so 'X (AffiliatedCompany; SOE)' stays whole."""
    if not value:
        return []
    out, depth, cur = [], 0, []
    for ch in value:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur).strip())
    return [x for x in out if x]


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ------------------------------------------------------------------ per table

def alert(r: dict) -> dict:
    c = r.get("customer") or {}
    return {
        "alert_id": r["alert_id"],
        "screened_at": r.get("screened_at"),
        "customer_name": c.get("name"),
        "entity_type": c.get("entity_type"),
        "dob": c.get("dob"), "dob_iso": parse_date(c.get("dob")),
        "country": c.get("country"), "country_norm": countries.norm(c.get("country")),
        "city": c.get("city"),
        "account_ref": r.get("account_ref"),
        "login_handle": r.get("login_handle"),
        "email": r.get("email"),
        "hit_ids": list(r.get("hit_ids") or []),
    }


HIT_LIST_FIELDS = ("aliases", "dobs", "place_of_birth", "nationality", "citizenship", "countries",
                   "addresses", "identifiers", "categories", "subcategories", "relationships",
                   "sources", "source_urls")


def hit(r: dict) -> dict:
    h = dict(r)
    for f in HIT_LIST_FIELDS:
        h[f] = [x for x in _as_list(r.get(f)) if x not in (None, "")]
    h["dobs"] = [str(d) for d in h["dobs"]]
    # the file splits these on every ";", even inside brackets ("X (Motherinlaw", "PEP)"),
    # and gives place of birth as one "a; b; c" string: split both at the top level only
    h["relationships"] = split_top("; ".join(h["relationships"]))
    h["place_of_birth"] = split_top("; ".join(h["place_of_birth"]))
    h["details"] = r.get("details") or {}
    h["dobs_iso"] = [parse_date(d) for d in h["dobs"]]
    h["deceased_date_iso"] = parse_date(r.get("deceased_date"))
    h["profile_notes_truncated"] = False  # the JSON Lines files carry the whole text
    tied = [_last_part_country(x) for f in ("countries", "nationality", "citizenship", "addresses",
                                              "place_of_birth") for x in h[f]]
    h["countries_tied"] = sorted({c for c in tied if c})
    return h


def customer(r: dict) -> dict:
    c = dict(r)
    c["dob_iso"] = parse_date(r.get("dob"))
    c["nationality_norm"] = countries.norm(r.get("nationality"))
    c["residence_country_norm"] = countries.norm(r.get("residence_country"))
    return c


def kyc_check(r: dict) -> dict:
    k = dict(r)
    k["verified_dob_iso"] = parse_date(r.get("verified_dob"))
    k["document_country_norm"] = countries.norm(r.get("document_country"))
    return k


def practice_label(r: dict) -> dict:
    steps = r.get("path") or []
    if isinstance(steps, str):
        steps = [s.strip() for s in steps.split("→")]
    return {**r, "path": " → ".join(steps), "path_steps": steps}


CONVERT = {"alerts": alert, "hits": hit, "customers": customer, "kyc_checks": kyc_check,
           "practice_labels": practice_label}


def is_official(folder: str | Path) -> bool:
    """True for a folder in the organisers' layout (alerts carry a nested `customer`)."""
    p = Path(folder) / "alerts.jsonl"
    if not p.exists():
        return False
    with open(p, encoding="utf-8") as f:
        first = next((line for line in f if line.strip()), "{}")
    return "customer" in json.loads(first)


def load(folder: str | Path, name: str) -> list[dict]:
    """One table from an official data folder, in the engine's shape."""
    rows = _read_jsonl(Path(folder) / f"{name}.jsonl")
    conv = CONVERT.get(name)
    return [conv(r) for r in rows] if conv else rows


def name_variants_path(folder: str | Path) -> Path | None:
    p = Path(folder) / "name_variants.json"
    return p if p.exists() else None
