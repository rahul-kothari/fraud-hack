# Output format (inferred from practice labels)

The practice labels are the closest thing we have to the answer format and to the `dev/` JSONL
files. Our system should emit **one JSON object per hit**, in the same shape, so it can be
diffed directly against `tables/practice_labels.jsonl`.

```json
{
  "hit_id": "H-0181BD",
  "alert_id": "A-957E63",
  "decision": "SAME_ENTITY",
  "reason_codes": ["NAME_DOB_LOCATION_MATCH"],
  "customer_record_ids": ["CUS-775419"],
  "evidence": ["CUS-775419", "NOTE-CB2CB8", "SR-590704"],
  "reference_reason": "The customer's date of birth 1985-09-12 (NOTE-CB2CB8) agrees with ...",
  "path": "account_ref ACC-FB5DD0 -> accounts: ... → SAME_ENTITY [...]: ..."
}
```

## Fields

| Field | In labels | What we emit |
|---|---|---|
| `hit_id`, `alert_id` | always | same |
| `decision` | `DIFFERENT_ENTITY` / `SAME_ENTITY` / `REVIEW` | exactly one |
| `reason_codes` | 1 or 2 codes (13 of 50 give 2): **any listed code is accepted** (POLICY: "When several apply, any of them is accepted") | our main code first; may list every code that applies |
| `customer_record_ids` | 1 or 2 IDs: **any of them is accepted** (one person with several records), or `["AMBIGUOUS"]` | the resolved person's record IDs, `["AMBIGUOUS"]`, or `[]` when none is found (POLICY: `null`) |
| `evidence` | IDs the decision relied on: `CUS-`, `KYC-`, `NOTE-`, `SR-` prefixes seen; never empty in labels | IDs of the records that decided it, not everything looked at |
| `reference_reason` | one-sentence justification | a templated sentence |
| `path` | the lookup trail, steps joined by ` → ` | the same trail. It's not required for scoring, but it makes debugging against labels easy |

## Notes from the 50 labels

- Decisions: 28 `DIFFERENT_ENTITY`, 12 `SAME_ENTITY`, 10 `REVIEW`.
- `AMBIGUOUS` does not imply `AMBIGUOUS_CUSTOMER_RECORD`. In both labelled ambiguous cases the people
  who fit led to the same decision, so the label is `REVIEW` / `INSUFFICIENT_DATA` with
  `customer_record_ids = ["AMBIGUOUS"]`. The evidence then cites every person's records.
- Evidence always includes the customer record, plus the most recent approved KYC check or the KYC
  note that supplied the verified facts, plus any search result used for the hit's date of birth.

## Proposed scoring (until we know the official one)

Per hit: decision exact; reason code ∈ label's `reason_codes`; customer record ∈ label's
`customer_record_ids`; evidence precision/recall against label's `evidence`. Report
**SAME_ENTITY labelled hits that we cleared** as a separate number, because that's the worst error.
