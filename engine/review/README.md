# Manual review of the engine's decisions

A hit-by-hit review of the engine's 819 dev-set decisions, as published in PR #1. The aim was to find
hits that might be mislabelled. The 15 flagged hits, with the evidence for each, are in
[`flagged_hits.csv`](flagged_hits.csv).

## How it was reviewed

1. **Second opinion.** `second_opinion.py` turns the casebook's independently written hints
   (`visual/build_casebook.py`) into SOP decisions and compares them with the engine. They agreed on
   801 of 819 hits, and on the customer records for all of them. Every one of the 18 disagreements was
   read in full with `dossier.py`.
2. **Group reads.** `scan.py` prints the deciding facts, one line per hit. Every line was read for:
   - SAME_ENTITY (124)
   - NAME_MISMATCH_VERIFIED (126)
   - LOCATION_MISMATCH (216)
   - DOB_MISMATCH (96, including all 60 search results used as a hit's DOB)
   - TEMPORAL_IMPOSSIBILITY (22), DECEASED (4) and ENTITY_TYPE_MISMATCH (1)
   - every REVIEW not caused by a missing DOB (43)
3. **Backstops.**
   - For every LOCATION clearance: all customer text (address, city, notes, checks) searched for the
     hit's countries.
   - Every hit whose free text the engine could not parse: checked by hand for a missed DOB.
   - Every first paragraph with a DOB phrase: checked that it was used.

```
python engine/review/second_opinion.py         # engine vs casebook hints
python engine/review/dossier.py H-2C6B2E       # everything known about one hit
python engine/review/scan.py SAME_ENTITY       # one line per hit with that decision or reason code
```

## Findings

**15 hits flagged:**
- 14 with high confidence, caused by 4 engine gaps
- 1 policy judgement call

| Cause | Hits | Effect |
|---|---|---|
| "born in YYYY" not read | 10 | 7 REVIEW → DIFFERENT_ENTITY, 3 REVIEW → SAME_ENTITY |
| "DOB: 6/20/1955" field not read | 1 | SAME_ENTITY → DIFFERENT_ENTITY (H-2C6B2E) |
| Name matcher joined parts on both sides | 1 | REVIEW → DIFFERENT_ENTITY (H-B47A06) |
| "X was 27." / "A 1996 profile from October" not read | 2 | REVIEW → DIFFERENT_ENTITY, REVIEW → SAME_ENTITY |
| Territory city vs country (policy reading) | 1 | DIFFERENT_ENTITY; REVIEW is arguably safer (H-BC0D0C) |

The engine fixes in this branch resolve the 14 high-confidence flags. H-BC0D0C still follows the
letter of the SOP: the customer's countries (United States, Brazil) differ from the hit's (Northern
Mariana Islands, a territory). But one of the customer's records has the city "Saipan, Northern Mariana
Islands", and no DOB exists on either side. This is left for a human decision.

None of the flagged hits was a customer wrongly cleared. H-2C6B2E was a false escalation: the hit's
own profile gives a DOB that contradicts the customer's.

## Reviewed and left as they are

- **18 disagreements with the casebook.** The casebook misses "was born on …", "then 37", "at 24"
  and "was 48 when …", so it lacked a DOB where the engine had one.
- **Placeholder names** (TEST, NA, XXX, UNKNOWN). These are neither confirmed nor cleared on name,
  but their DOB still clears them.
- **Joint accounts.** The screened details pick the right holder.
- **"Verified beats declared."** An approved check with a different legal name clears the hit on
  NAME_MISMATCH_VERIFIED.

## Follows the rules, but doubtful in reality (not flagged)

These company hits are SAME_ENTITY because the SOP's name rule is met by generic words, and no
incorporation date or dated report contradicts them:

| Hit | Customer vs hit |
|---|---|
| H-9F5114 | Nikola Corporation vs Nikolas, LLC |
| H-F37DDF | Bluegrass Craft Coffee Roasters vs Blue Grass, LLC |
| H-711F4D | Global Relief Supplies Inc. vs Global Relief Foundation |
| H-64D096 | Industrial Technologies Services France vs France Technology Services |
| H-43F74B | Danske Bank A/S vs Danske Andelskassers Bank A/S |
| H-0CF782 | TD Bank, N.A. vs TD Bank US Holding Company |
| H-24D490, H-3DBE33 | N26 Bank AG vs N26 Bank SE |
