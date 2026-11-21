"""Build processed/ from the screening dev set: the workbook, or a folder of its CSV exports.

    python prepare.py --xlsx "../Screening Dev Set - browse.xlsx"      # needs openpyxl
    python prepare.py --csv-dir path/to/csvs                            # stdlib only

Outputs (all under engine/processed/):
  docs/POLICY.md, docs/START_HERE.md   the SOP and workbook guide as Markdown
  reference/name_variants.json         name-part variant groups + company legal forms
  reference/countries.json             code/demonym/spelling -> canonical country name
  tables/<table>.jsonl                 one JSON object per row, typed and normalised
  screening.sqlite                      the same tables, indexed on their join keys

Conventions in the tables:
  * empty strings become null
  * semicolon-separated multi-value fields become arrays
  * raw values are kept; derived fields get a suffix:
      <field>_iso   a date parsed to ISO, keeping only the parts given ("1980", "1980-05", "1980-05-19")
      <field>_norm  a country mapped to one canonical name

"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "processed"
PREFIX = "Screening Dev Set - browse - "
CSV_NAMES = {"Practice labels": ["Practice labels", "Practice labels (1)"]}

csv.field_size_limit(sys.maxsize if sys.maxsize < 2**31 else 2**31 - 1)


# --------------------------------------------------------------------------- io

class Source:
    """Reads one sheet as rows (header -> value) or as plain lines, from the workbook or CSV exports."""

    def __init__(self, xlsx: Path | None = None, csv_dir: Path | None = None):
        self.csv_dir = csv_dir
        self.wb = None
        if xlsx:
            try:
                import openpyxl
            except ImportError:
                sys.exit("Reading the workbook needs openpyxl: pip install openpyxl (or use --csv-dir)")
            print(f"reading {xlsx.name} ...", flush=True)
            self.wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)

    @staticmethod
    def _cell(v) -> str | None:
        if v is None:
            return None
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        s = str(v)
        return s if s != "" else None

    def _csv_path(self, sheet: str) -> Path:
        for n in CSV_NAMES.get(sheet, [sheet]):
            p = self.csv_dir / f"{PREFIX}{n}.csv"
            if p.exists():
                return p
        sys.exit(f"missing CSV for sheet {sheet!r} in {self.csv_dir}")

    def rows(self, sheet: str) -> list[dict]:
        if self.wb is not None:
            it = self.wb[sheet].iter_rows(values_only=True)
            header = [h for h in next(it) if h is not None]
            out = []
            for r in it:
                vals = [self._cell(v) for v in r[:len(header)]]
                if any(v is not None for v in vals):
                    out.append(dict(zip(header, vals + [None] * (len(header) - len(vals)))))
            return out
        with open(self._csv_path(sheet), encoding="utf-8", newline="") as f:
            return [{k: (v if v != "" else None) for k, v in row.items()} for row in csv.DictReader(f)]

    def lines(self, sheet: str) -> list[str]:
        """A single-column sheet: one cell per line (empty rows kept as empty strings)."""
        if self.wb is not None:
            out = [",".join(c for c in (self._cell(v) for v in r) if c) for r in self.wb[sheet].iter_rows(values_only=True)]
            while out and not out[-1]:
                out.pop()
            return out
        with open(self._csv_path(sheet), encoding="utf-8", newline="") as f:
            return [",".join(row) for row in csv.reader(f)]


SRC: Source   # set in main()


def read_csv(name: str) -> list[dict]:
    return SRC.rows(name)


def read_lines(name: str) -> list[str]:
    return SRC.lines(name)


def write_jsonl(name: str, rows: list[dict]) -> None:
    path = OUT / "tables" / f"{name}.jsonl"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------- splitting

def split_top(value: str | None, sep: str = ";") -> list[str]:
    """Split on `sep` outside (...) and [...] so 'X (AffiliatedCompany; SOE)' stays whole."""
    if not value:
        return []
    parts, depth, cur = [], 0, []
    for ch in value:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


# ----------------------------------------------------------------------- dates

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
_M = r"([A-Za-z]+)"


def parse_date(value: str | None) -> str | None:
    """Parse the export's date shapes to a partial ISO string. dd/mm/yyyy is day-first
    (verified: the first field exceeds 12 in thousands of rows, the second never does)."""
    if not value:
        return None
    v = value.strip()
    if m := re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", v):
        y, mo, d = m.groups()
    elif m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", v):
        d, mo, y = m.groups()
    elif m := re.fullmatch(rf"(\d{{1,2}}) {_M},? (\d{{4}})", v):
        d, mo, y = m.group(1), MONTHS.get(m.group(2).lower()), m.group(3)
    elif m := re.fullmatch(rf"{_M} (\d{{1,2}}),? (\d{{4}})", v):
        mo, d, y = MONTHS.get(m.group(1).lower()), m.group(2), m.group(3)
    elif m := re.fullmatch(rf"{_M},? (\d{{4}})", v):
        mo, d, y = MONTHS.get(m.group(1).lower()), None, m.group(2)
    else:
        UNPARSED_DATES[v] += 1
        return None
    if mo is None and d is not None:
        UNPARSED_DATES[v] += 1
        return None
    out = f"{int(y):04d}"
    if mo:
        out += f"-{int(mo):02d}"
        if d:
            out += f"-{int(d):02d}"
    return out


UNPARSED_DATES: Counter = Counter()


# ------------------------------------------------------------------- countries

CODES = {
    "AR": "Argentina", "AT": "Austria", "AU": "Australia", "BD": "Bangladesh", "BR": "Brazil",
    "CA": "Canada", "CI": "Côte d'Ivoire", "DE": "Germany", "DK": "Denmark", "ES": "Spain",
    "FI": "Finland", "FR": "France", "GB": "United Kingdom", "UK": "United Kingdom", "GH": "Ghana",
    "ID": "Indonesia", "IE": "Ireland", "IN": "India", "IT": "Italy", "KE": "Kenya", "MX": "Mexico",
    "NG": "Nigeria", "NL": "Netherlands", "NO": "Norway", "PE": "Peru", "PK": "Pakistan",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "RS": "Serbia", "SE": "Sweden",
    "SG": "Singapore", "US": "United States", "USA": "United States", "ZA": "South Africa",
}
DEMONYMS = {
    "American": "United States", "Australian": "Australia", "Austrian": "Austria",
    "Bangladeshi": "Bangladesh", "Brazilian": "Brazil", "British": "United Kingdom",
    "Canadian": "Canada", "Danish": "Denmark", "Dutch": "Netherlands", "French": "France",
    "German": "Germany", "Ghanaian": "Ghana", "Indian": "India", "Indonesian": "Indonesia",
    "Irish": "Ireland", "Italian": "Italy", "Kenyan": "Kenya", "Mexican": "Mexico",
    "Nigerian": "Nigeria", "Norwegian": "Norway", "Pakistani": "Pakistan", "Polish": "Poland",
    "Portuguese": "Portugal", "Serbian": "Serbia", "Singaporean": "Singapore",
    "South African": "South Africa", "Spanish": "Spain", "Swedish": "Sweden",
    "Vietnamese": "Vietnam", "Moroccan": "Morocco", "Algerian": "Algeria", "Egyptian": "Egypt",
    "Lebanese": "Lebanon", "Syrian": "Syria", "Russian": "Russia", "Ukrainian": "Ukraine",
    "Turkish": "Turkey", "Chinese": "China", "Japanese": "Japan", "Thai": "Thailand",
    "Filipino": "Philippines", "Malaysian": "Malaysia", "Swiss": "Switzerland", "Belgian": "Belgium",
    "Finnish": "Finland", "Romanian": "Romania", "Hungarian": "Hungary", "Czech": "Czech Republic",
    "Slovenian": "Slovenia", "Croatian": "Croatia", "Colombian": "Colombia", "Peruvian": "Peru",
    "Argentinian": "Argentina", "Argentine": "Argentina", "Ecuadorian": "Ecuador", "Jamaican": "Jamaica",
    "Israeli": "Israel", "Emirati": "United Arab Emirates", "New Zealander": "New Zealand",
}
SPELLINGS = {
    "Cote D'Ivoire": "Côte d'Ivoire", "Cote d'Ivoire": "Côte d'Ivoire", "Ivory Coast": "Côte d'Ivoire",
    "Palestina": "Palestine",
    "Macao Special Administrative Region of China": "Macao",
    "Hong Kong Special Administrative Region of China": "Hong Kong",
    "Czechia": "Czech Republic",
}
NOT_COUNTRIES = {"International", "Europe"}
COUNTRY_MAP = {**CODES, **DEMONYMS, **SPELLINGS}
UNMAPPED_COUNTRIES: Counter = Counter()


def norm_country(value: str | None) -> str | None:
    if not value:
        return None
    v = re.sub(r"\[[^\]]*\]", "", value).strip().rstrip(".").strip()
    if not v or v in NOT_COUNTRIES:
        return None
    return COUNTRY_MAP.get(v, v)


def last_part_country(value: str) -> str | None:
    """'Belgrade, Serbia' -> 'Serbia'; '..., Canada [Business]' -> 'Canada'."""
    v = re.sub(r"\[[^\]]*\]", "", value).strip()
    return norm_country(v.split(",")[-1].strip()) if v else None


# ---------------------------------------------------------------------- tables

def build_alerts() -> list[dict]:
    rows = []
    for r in read_csv("Alerts"):
        rows.append({
            "alert_id": r["alert_id"],
            "screened_at": r["screened_at"],
            "customer_name": r["customer_name"],
            "entity_type": r["entity_type"],
            "dob": r["dob"], "dob_iso": parse_date(r["dob"]),
            "country": r["country"], "country_norm": norm_country(r["country"]),
            "city": r["city"],
            "account_ref": r["account_ref"],
            "login_handle": r["login_handle"],
            "email": r["email"],
            "hit_ids": split_top(r["hit_ids"]),
        })
        assert int(r["hit_count"]) == len(rows[-1]["hit_ids"]), r["alert_id"]
    return rows


HIT_LIST_FIELDS = ["aliases", "dobs", "place_of_birth", "nationality", "citizenship", "countries",
                   "addresses", "identifiers", "categories", "relationships", "sources", "source_urls"]
TRUNC_MARK = "(cut; full text in the JSONL file)"


def build_hits() -> list[dict]:
    rows = []
    for r in read_csv("Hits"):
        h = {k: r[k] for k in r}
        h["match_score"] = int(r["match_score"]) if r["match_score"] else None
        for f in HIT_LIST_FIELDS:
            h[f] = split_top(r[f])
        h["dobs_iso"] = [parse_date(d) for d in h["dobs"]]
        h["deceased_date_iso"] = parse_date(r["deceased_date"])
        notes = r["profile_notes"] or ""
        h["profile_notes_truncated"] = TRUNC_MARK in notes
        # countries tied to the hit (POLICY principle 5): countries, nationality, citizenship,
        # last part of each address and place of birth; "International"/"Europe" dropped.
        tied = []
        for f in ("countries", "nationality", "citizenship"):
            tied += [last_part_country(x) for x in h[f]]
        tied += [last_part_country(x) for x in h["addresses"]]
        tied += [last_part_country(x) for x in h["place_of_birth"]]
        h["countries_tied"] = sorted({c for c in tied if c})
        rows.append(h)
    return rows


def build_customers() -> list[dict]:
    rows = []
    for r in read_csv("Customers"):
        c = dict(r)
        c["dob_iso"] = parse_date(r["dob"])
        c["nationality_norm"] = norm_country(r["nationality"])
        c["residence_country_norm"] = norm_country(r["residence_country"])
        rows.append(c)
    return rows


def build_kyc() -> list[dict]:
    rows = []
    for r in read_csv("KYC checks"):
        k = dict(r)
        k["verified_dob_iso"] = parse_date(r["verified_dob"])
        k["document_country_norm"] = norm_country(r["document_country"])
        rows.append(k)
    return rows


def build_practice_labels() -> list[dict]:
    rows = []
    for r in read_csv("Practice labels"):
        rows.append({
            "hit_id": r["hit_id"],
            "alert_id": r["alert_id"],
            "decision": r["decision"],
            "reason_codes": split_top(r["reason_codes"]),
            "customer_record_ids": split_top(r["customer_record_ids"]),
            "evidence": split_top(r["evidence"]),
            "reference_reason": r["reference_reason"],
            "path": r["path"],
            "path_steps": [s.strip() for s in (r["path"] or "").split("→")],
        })
    return rows


# ----------------------------------------------------------------------- docs

def close_blocks(text: str) -> str:
    """Ensure a blank line after a table or list block when plain text follows it."""
    is_block = lambda l: l.startswith("|") or l.lstrip().startswith("- ")
    out, lines = [], text.split("\n")
    for i, line in enumerate(lines):
        out.append(line)
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        if is_block(line) and nxt.strip() and not is_block(nxt):
            out.append("")
    return "\n".join(out)


def build_policy() -> None:
    lines = read_lines("Policy")
    split_at = lines.index("name_variants.json")
    md = []
    for i, line in enumerate(lines[:split_at]):
        s = line.rstrip()
        if i == 0:
            md += [f"# {s}", ""]
        elif s in ("Decisions", "Principles", "Reason codes"):
            md += ["", f"## {s}", ""]
        elif s.startswith("|"):
            md.append(s)
        elif s.lstrip().startswith("- "):
            md.append(s)
        elif s:
            md += [s, ""]
    md += ["", "## Name variants", "",
           "Groups of given-name forms that count as the same name part, and the company legal "
           "forms that are not name parts, are in [`../reference/name_variants.json`]"
           "(../reference/name_variants.json).", ""]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(md))
    # tables and the principle-6 bullet list must be contiguous blocks
    text = re.sub(r"(\|[^\n]*)\n\n(?=\|)", r"\1\n", text)
    text = re.sub(r"(\n   - [^\n]*)\n\n(?=   - )", r"\1\n", text)
    text = re.sub(r"(\n   - [^\n]*)\n\n(?=   - )", r"\1\n", text)
    text = close_blocks(text)
    (OUT / "docs" / "POLICY.md").write_text(text.strip() + "\n", encoding="utf-8")

    rest = [l for l in lines[split_at + 1:] if l.strip()]
    groups, forms = [], []
    for l in rest[1:]:  # rest[0] is the description sentence
        if l.startswith("Company legal forms:"):
            forms = [x.strip() for x in l.split(":", 1)[1].split(",")]
        else:
            groups.append([x.strip() for x in l.split(",")])
    (OUT / "reference" / "name_variants.json").write_text(json.dumps({
        "description": rest[0],
        "name_variant_groups": groups,
        "company_legal_forms": forms,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_start_here() -> None:
    lines = [l for l in read_lines("Start here")]
    md, in_links = [f"# {lines[0]}", ""], False
    for s in lines[1:]:
        s = s.rstrip()
        if s in ("Tabs", "How the tabs link", "Try it"):
            md += ["", f"## {s}", ""]
            in_links = s == "How the tabs link"
        elif not s:
            continue
        elif s.startswith(("Alerts (", "Hits (", "Customers (", "Accounts (", "KYC checks (",
                           "Notes (", "Search results (", "Practice labels (", "Policy:")):
            md.append(f"- {s}")
        elif in_links and ("→" in s):
            md.append(f"- `{s}`")
        else:
            md += [s, ""]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(md))
    text = close_blocks(text)
    (OUT / "docs" / "START_HERE.md").write_text(text.strip() + "\n", encoding="utf-8")


# --------------------------------------------------------------------- sqlite

INDEXES = {
    "alerts": ["alert_id", "account_ref", "login_handle", "email"],
    "hits": ["hit_id", "alert_id"],
    "customers": ["record_id", "email", "phone", "full_name"],
    "accounts": ["account_id", "customer_id", "login_handle", "phone"],
    "onboarding": ["account_id", "customer_id", "kyc_applicant_id"],
    "kyc_checks": ["check_id", "applicant_id", "document_number"],
    "notes": ["note_id", "requester_email"],
    "search_results": ["result_id", "query"],
    "practice_labels": ["hit_id", "alert_id"],
}


def build_sqlite(tables: dict[str, list[dict]]) -> None:
    path = OUT / "screening.sqlite"
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    for name, rows in tables.items():
        cols = list(rows[0].keys())
        con.execute(f'CREATE TABLE {name} ({", ".join(f"[{c}]" for c in cols)})')
        con.executemany(
            f'INSERT INTO {name} VALUES ({", ".join("?" * len(cols))})',
            [[json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
              for v in (r[c] for c in cols)] for r in rows])
        for c in INDEXES.get(name, []):
            con.execute(f"CREATE INDEX ix_{name}_{c} ON {name}([{c}])")
    con.commit()
    con.close()


# ----------------------------------------------------------------------- main

def main() -> None:
    global SRC
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--xlsx", type=Path, help="the dev-set workbook")
    g.add_argument("--csv-dir", type=Path, help="folder of the workbook's CSV exports")
    args = ap.parse_args()
    SRC = Source(xlsx=args.xlsx, csv_dir=args.csv_dir)
    for d in ("docs", "reference", "tables"):
        (OUT / d).mkdir(parents=True, exist_ok=True)

    build_policy()
    build_start_here()

    tables = {
        "alerts": build_alerts(),
        "hits": build_hits(),
        "customers": build_customers(),
        "accounts": read_csv("Accounts"),
        "onboarding": read_csv("Onboarding"),
        "kyc_checks": build_kyc(),
        "notes": read_csv("Notes"),
        "search_results": read_csv("Search results"),
        "practice_labels": build_practice_labels(),
    }
    for name, rows in tables.items():
        write_jsonl(name, rows)
    build_sqlite(tables)

    # countries seen after normalisation, for review
    seen = Counter()
    for c in tables["customers"]:
        seen[c["nationality_norm"]] += 1
        seen[c["residence_country_norm"]] += 1
    for k in tables["kyc_checks"]:
        seen[k["document_country_norm"]] += 1
    for a in tables["alerts"]:
        seen[a["country_norm"]] += 1
    for h in tables["hits"]:
        for c in h["countries_tied"]:
            seen[c] += 1
    seen.pop(None, None)
    (OUT / "reference" / "countries.json").write_text(json.dumps({
        "description": "Mapping applied to produce *_norm country fields. Values not listed map to "
                       "themselves. 'International' and 'Europe' are not countries and map to null.",
        "codes": CODES, "demonyms": DEMONYMS, "spellings": SPELLINGS,
        "not_countries": sorted(NOT_COUNTRIES),
        "canonical_values_seen": dict(sorted(seen.items())),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for name, rows in tables.items():
        print(f"{name:16} {len(rows):>7} rows")
    print("unparsed dates:", dict(UNPARSED_DATES) or "none")


if __name__ == "__main__":
    main()
