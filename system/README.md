# system/

The organisers' entry point:

```sh
system/run <data folder> <output file>      # e.g. system/run data/dev output/dev.jsonl
```

`<data folder>` is laid out like the data room's `dev/` (alerts.jsonl, hits.jsonl, customers.jsonl,
accounts.jsonl, onboarding.jsonl, kyc_checks.jsonl, notes.jsonl, search_results.jsonl,
name_variants.json). The output has one JSON line per hit, in the fields of `output.schema.json`.

- **Engine:** the SOP rules engine in `engine/screening`. `ingest.py` reads the official files and
  derives the parsed dates, normalised countries and the hit's tied countries in memory.
- **Standard library only.** No packages to install, no language model, no network.
- **Reads only the data folder** (and the engine's own country table). A missing
  `practice_labels.jsonl` is fine.
- **Deterministic:** no model calls, a fixed hash seed, and output in `hits.jsonl` order. Two runs
  give byte-identical files.
- **Safe on bad data:** an alert the engine can't process gets `REVIEW / INSUFFICIENT_DATA` for its
  hits instead of stopping the run. Every hit gets exactly one line.
- **Time:** about 4 seconds on the dev set (819 hits, 72k customer records).

Dev set, scored with the organisers' `validate.py --score`:
- 819 lines, 0 problems
- practice labels: 50/50 right decisions, 0 unsafe clearances, decision score 100.0
- reason code 100%, customer record 100%
