"""Compare the engine's decisions with a decision derived from the casebook's own hints.

The casebook (visual/build_casebook.py) was written independently. Its per-fact hints are turned into
a decision with the SOP's rules, then compared with the engine. Disagreements go to manual review.

    python engine/review/second_opinion.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent


def load_js(path, prefix):
    s = path.read_text(encoding="utf-8")
    return json.loads(s[len(prefix):].rstrip().rstrip(";"))


book = load_js(REPO / "visual/data.js", "window.CASEBOOK = ")
eng = load_js(REPO / "visual/decisions.js", "window.DECISIONS = ")


def hint_decision(cmp, company):
    """SOP principles 6 and 7 applied to the casebook's hint states for one person."""
    name, dob, ctry = cmp["name"]["state"], cmp["dob"]["state"], cmp["country"]["state"]
    name_ok, dob_ok = name == "agrees", dob == "agrees"
    if cmp["type"]["state"] == "contradicts":
        return "DIFFERENT_ENTITY", "ENTITY_TYPE_MISMATCH"
    if cmp["time"]["state"] == "contradicts":
        return "DIFFERENT_ENTITY", "TEMPORAL_IMPOSSIBILITY/DECEASED"
    if dob == "contradicts":
        return "DIFFERENT_ENTITY", "DOB_MISMATCH"
    if name == "contradicts":
        return "DIFFERENT_ENTITY", "NAME_MISMATCH_VERIFIED"
    if ctry == "contradicts" and not (name_ok and dob_ok):
        return "DIFFERENT_ENTITY", "LOCATION_MISMATCH"
    if ctry == "contradicts":
        return "REVIEW", "INSUFFICIENT_DATA"
    if not company and name_ok and dob_ok:
        return "SAME_ENTITY", "NAME_DOB_*"
    if company and name_ok and ctry == "agrees":
        return "SAME_ENTITY", "NAME_LOCATION_MATCH"
    return "REVIEW", "INSUFFICIENT_DATA"


rows = []
for aid, case in book["cases"].items():
    company = case["alert"].get("entity_type") == "Company"
    for h in case["hits"]:
        per = [hint_decision(c, company) for c in h["compare"]]
        decs = {d for d, _ in per}
        if len(per) > 1 and len(decs) > 1:
            hint = ("REVIEW", "AMBIGUOUS_CUSTOMER_RECORD")
        else:
            hint = per[0]
        e = eng["hits"][h["id"]]
        rows.append({
            "hit_id": h["id"], "alert_id": aid, "engine": e["decision"], "engine_reason": e["reason_codes"][0],
            "hint": hint[0], "hint_reason": hint[1], "people_book": len(case["people"]),
            "engine_customer": e["customer_record_ids"],
            "book_records": sorted({r for p in case["people"] for r in p["records"]}),
            "label": (h.get("label") or {}).get("decision"),
        })

agree = [r for r in rows if r["engine"] == r["hint"]]
dis = [r for r in rows if r["engine"] != r["hint"]]
cust_dis = [r for r in rows if r["engine_customer"] not in ([], ["AMBIGUOUS"])
            and not set(r["engine_customer"]) <= set(r["book_records"])]
print(f"hits: {len(rows)}  agree: {len(agree)}  disagree: {len(dis)}")
print("disagreements (engine -> hint):", Counter((r["engine"], r["hint"]) for r in dis).most_common())
print("customer record differs from casebook's people:", len(cust_dis))
(OUT / "second_opinion.json").write_text(json.dumps({"disagree": dis, "customer_differs": cust_dis}, indent=1),
                                         encoding="utf-8")
