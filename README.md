# fraud-hack

Tools for Track 1, "Same Person or Not?", of the GB FinCrime hackathon (November 2026).

## visual/

A casebook of every screening alert in the dev set. Each alert is laid out as a story: the customer and the watchlist hit side by side, the SOP's steps to an answer, a hint for each rule, and the raw rows. The hints are mechanical checks of single rules. The casebook makes no decisions.

- `build_casebook.py` reads the dev-set workbook and writes `data.json`.
- `casebook.html` is the page. It loads `data.json` from the same folder.
- `data.json` is the built data, so the page works straight from a clone.

### View

The page fetches `data.json`, so serve the folder rather than opening the file directly:

```
cd visual
python3 -m http.server 8000
```

Then open http://localhost:8000/casebook.html.

### Rebuild

The dev-set workbook, `Screening Dev Set - browse.xlsx`, sits in the repo root.

```
cd visual
python3 -m venv .venv && .venv/bin/pip install pandas openpyxl
.venv/bin/python build_casebook.py --xlsx "../Screening Dev Set - browse.xlsx" --out data.json --cache .cache --check
```

The first run reads the workbook in about 45 seconds. Later runs reuse `.cache` and take about 12.

`--check` tests the plumbing against the 50 practice labels: did it find the labelled customer records, and does it surface every record the answer cites. It does not compare decisions.
