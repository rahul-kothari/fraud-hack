# engine/

A rules engine that decides every hit in the dev set: `DIFFERENT_ENTITY`, `SAME_ENTITY` or `REVIEW`.
Each decision comes with reason codes, the customer record and the evidence IDs it relied on.
It applies the SOP ([`processed/docs/POLICY.md`](processed/docs/POLICY.md)) step by step. The output
matches the practice labels' format ([`processed/docs/OUTPUT_FORMAT.md`](processed/docs/OUTPUT_FORMAT.md)).

Its decisions show up in the casebook (`../visual/casebook.html`) when `../visual/decisions.js` exists.

## Run

From this folder, with the repo's `.venv` (the only dependency is `openpyxl`, used to read the workbook):

```sh
python -m venv ../.venv && ../.venv/Scripts/pip install -r requirements.txt   # macOS/Linux: ../.venv/bin/pip

python prepare.py --xlsx "../Screening Dev Set - browse.xlsx"   # workbook -> processed/ (~20 s, once)
python -m screening.pipeline --casebook ../visual/decisions.js # decide all 819 hits (~4 s)
python -m screening.pipeline --csv outputs/decisions.csv       # same, plus a CSV in the practice labels' format
python -m screening.evaluate -v                                # score against the 50 practice labels
python -m screening.pipeline --alerts A-957E63                 # one alert, prints its trail
python -m unittest discover tests                              # rules from the SOP's own examples
```

`prepare.py --csv-dir DIR` reads the workbook's CSV exports instead, using only the standard library.

## Results (dev set, regex only)

| | |
|---|---|
| Hits | 819: 465 DIFFERENT_ENTITY, 230 REVIEW, 124 SAME_ENTITY |
| Alerts | 175 DIFFERENT_ENTITY (every hit cleared), 158 REVIEW, 107 SAME_ENTITY (at least one hit is the customer) |
| Practice labels | decision 50/50, reason 50/50, customer 50/50, evidence precision 100% / recall 100% |
| SAME_ENTITY predicted as DIFFERENT_ENTITY | 0 |

Fifty labels is a small answer key, so expect some misses on the unseen set. A manual review of all
819 decisions is in [`review/`](review/README.md). REVIEW is the safe
outcome: the engine only clears on a contradiction and only confirms on agreement.

## How it works

| Step | Module | SOP |
|---|---|---|
| Find the customer: follow the link, or search by name / DOB / country / city; group records into people | `resolve.py` | 2, 3 |
| Customer picture: all records, latest approved check (KYC tab or KYC note), places the notes say they lived | `resolve.py`, `extract.py` | 3, 4 |
| Hit picture: DOB from `dobs`, then the profile notes' first paragraph, then qualifying search results; countries; earliest dated report | `decide.py`, `extract.py` | 5 |
| Contradictions (all that apply), then agreement, then combine several people | `decide.py` | 6, 7, 3 |
| Name matching | `names.py` | 8 |

**Evidence.** Each decision cites the sources of the facts that settled it, the same way the practice
labels do:
- DOB_MISMATCH: the customer's DOB source, plus a search result if one gave the hit's DOB.
- NAME_MISMATCH_VERIFIED: the verified check.
- LOCATION_MISMATCH: the records, plus any check or note that adds a country.
- SAME_ENTITY: the records, the DOB source and any search result.
- REVIEW: whatever ties the customer to the hit's countries.

**Grok (optional).** Free text is parsed with regex. When regex can't fill a required field (an
unusually worded age sentence, residence note or search snippet), `grok.py` asks Grok to extract it
into a fixed JSON schema. Grok never makes the decision. Set `XAI_API_KEY` to enable it (and
`GROK_MODEL` to pick the model). Answers are cached in `.cache/grok/`. `--grok off` forces regex only.
On the dev set, regex alone reads all 22,575 KYC notes, and only about a dozen texts would go to Grok.

Each decision also carries `evidence_detail`. For every evidence ID, and for the practice label's
evidence too, it gives what the record is, a summary of what it says, and what the decision used it
for (e.g. "customer's date of birth: 1985-09-12", "ties the customer to Brazil"). This is built in
`evidence.py`, and the casebook shows it.

## Files

- `prepare.py` writes `processed/`. Generated, but `docs/` and `reference/` are kept in git:
  - `docs/`: POLICY.md, START_HERE.md and OUTPUT_FORMAT.md
  - `reference/`: name variants and the country mapping
  - `tables/*.jsonl` and `screening.sqlite`: gitignored, rebuilt by `prepare.py`
- `screening/`: the engine.
- `tests/`: unit tests for the name, date and extraction rules.
- `outputs/decisions.jsonl`: one decision per hit (gitignored).
