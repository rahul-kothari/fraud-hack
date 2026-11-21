"""Print everything known about a hit, for manual review.

    python engine/review/dossier.py H-0181BD [H-... ...]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screening.decide import hit_facts                      # noqa: E402
from screening.extract import first_paragraph, listing_phrase, search_query   # noqa: E402
from screening import countries                             # noqa: E402
from screening.resolve import Resolver                      # noqa: E402
from screening.store import Store                           # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ENG = {"hits": {}}
for _line in open(REPO / "engine/outputs/decisions.jsonl", encoding="utf-8"):
    _r = json.loads(_line)
    ENG["hits"][_r["hit_id"]] = {**_r, "reason": _r["reference_reason"]}
_b = (REPO / "visual/data.js").read_text(encoding="utf-8")
BOOK = json.loads(_b[len("window.CASEBOOK = "):].rstrip().rstrip(";"))

store = Store()
resolver = Resolver(store, None)
alerts = {a["alert_id"]: a for a in store.alerts}


def cut(t, n=220):
    t = (t or "").replace("\n", " / ")
    return t if len(t) <= n else t[:n] + "…"


def dossier(hid):
    h = store.hits[hid]
    a = alerts[h["alert_id"]]
    e = ENG["hits"][hid]
    print("=" * 110)
    print(f"{hid}  alert {a['alert_id']}  screened {a['screened_at']}  score {h['match_score']}")
    print(f"ALERT   {a['customer_name']} | {a['entity_type']} | dob {a['dob']} | {a['country']} | {a['city']} | "
          f"acct {a['account_ref']} login {a['login_handle']} email {a['email']}")
    res = resolver.resolve(a)
    for i, p in enumerate(res.people):
        print(f"PERSON {i + 1}: records {p.record_ids}  type {p.entity_type}")
        for rid in p.record_ids:
            c = store.customers[rid]
            print(f"   {rid} {c['full_name']} ({c['preferred_name']}) dob {c['dob']} nat {c['nationality']} "
                  f"res {c['residence_country']} {c['city']} | {c['address']} | {c['email']}")
            for k in store.kyc_checks_for(rid):
                print(f"     {k['check_id']} {k['result']:8} {k['checked_at']} {k['provider']}: {k['verified_name']} | "
                      f"{k['verified_dob']} | {k['document_type']} {k['document_country']}")
            for n in store.notes_for(rid):
                if n["channel"] == "kyc" or countries.find_in_text(n["text"]):
                    print(f"     {n['note_id']} {n['channel']} {n['created_at']}: {cut(n['text'], 170)}")
        print(f"   => verified name {p.verified_name and (p.verified_name.value, p.verified_name.source)}  "
              f"dob {p.dob and (str(p.dob.value), p.dob.source)}  countries {sorted(p.country_set())}")
    hf = hit_facts(h, store, None)
    print(f"HIT     {h['name']} | {h['entity_type']} | aliases {h['aliases'][:6]}")
    print(f"   dobs {h['dobs']}  pob {h['place_of_birth'][:2]}  nat {h['nationality']}  cit {h['citizenship']}  "
          f"life {h['life_status']} died {h['deceased_date']}")
    print(f"   countries_tied {h['countries_tied']}  category {h['primary_category'] or h['categories']}")
    print(f"   position: {cut(h['position_or_allegation'], 160)}")
    fp = first_paragraph(h["profile_notes"])
    if fp:
        print(f"   first para: {cut(fp, 300)}")
    print(f"   hit DOB used: {[d.describe() + ' (' + d.source + ')' for d in hf.dobs]}  earliest report "
          f"{hf.earliest_report and str(hf.earliest_report[0])}")
    phrase, tied = listing_phrase(h), set(h["countries_tied"])
    for r in store.search_by_query.get(search_query(h["name"]), []):
        ok = phrase in r["snippet"] and bool(set(countries.find_in_text(r["snippet"])) & tied)
        print(f"   {'*' if ok else ' '} {r['result_id']} {cut(r['snippet'], 170)}")
    case = BOOK["cases"][a["alert_id"]]
    bh = next(x for x in case["hits"] if x["id"] == hid)
    for c in bh["compare"]:
        print("   casebook hints: " + "  ".join(f"{k}={c[k]['state']}" for k in ("type", "name", "dob", "country", "time"))
              + f"  (name compared: {c['name']['match'] and c['name']['match']['a']} vs "
                f"{c['name']['match'] and c['name']['match']['b']})")
    print(f"ENGINE  {e['decision']} {e['reason_codes']}  customer {e['customer_record_ids']}")
    print(f"   {e['reason']}")
    if bh.get("label"):
        print(f"LABEL   {bh['label']['decision']} {bh['label']['reason_codes']}")


if __name__ == "__main__":
    for hid in sys.argv[1:]:
        dossier(hid)
