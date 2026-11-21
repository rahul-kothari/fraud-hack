# fraud-hack

Tools for Track 1, "Same Person or Not?", of the GB FinCrime hackathon (November 2026).

## engine/

A rules engine that decides every hit (`DIFFERENT_ENTITY`, `SAME_ENTITY` or `REVIEW`) with reason codes,
customer record and evidence, by applying the SOP. On the 50 practice labels it matches every
decision, reason code, customer record and evidence citation. See [`engine/README.md`](engine/README.md).

```
cd engine
python prepare.py --xlsx "../Screening Dev Set - browse.xlsx"
python -m screening.pipeline --casebook ../visual/decisions.js
```

The second command writes `visual/decisions.js`, which the casebook shows as a separate layer. Each
case opens with the selected hit's predicted result beside its true result from the practice labels,
and each piece of evidence is described: what the record says and what it was used for. The alert
list and the hit tabs show each predicted decision.

## visual/

A casebook of every screening alert in the dev set. Each alert is laid out as a story: the customer and the watchlist hit side by side, the SOP's steps to an answer, a hint for each rule, and the raw rows. The hints are mechanical checks of single rules. The casebook itself makes no decisions. The engine's decisions are a separate, optional layer.

- `build_casebook.py` reads the dev-set workbook and writes `data.js`.
- `casebook.html` is the page. It loads `data.js` from the same folder, and `decisions.js` if present.
- `data.js` is the built data, so the page works straight from a clone.
- `decisions.js` holds the engine's decisions (written by `engine/`). Without it the page shows only the hints.

### View

Double-click `visual/casebook.html`, or run `open visual/casebook.html`. No server needed.

### Rebuild

The dev-set workbook, `Screening Dev Set - browse.xlsx`, sits in the repo root.

```
cd visual
python3 -m venv .venv && .venv/bin/pip install pandas openpyxl
.venv/bin/python build_casebook.py --xlsx "../Screening Dev Set - browse.xlsx" --out data.js --cache .cache --check
```

The first run reads the workbook in about 45 seconds. Later runs reuse `.cache` and take about 12.

`--check` tests the plumbing against the 50 practice labels: did it find the labelled customer records, and does it surface every record the answer cites. It does not compare decisions.
