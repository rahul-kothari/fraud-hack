"""One line per hit with the facts that decided it, for scanning a whole decision group by eye.

    python engine/review/scan.py SAME_ENTITY            # every hit with that decision
    python engine/review/scan.py LOCATION_MISMATCH      # every hit whose main reason code is that
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screening.decide import hit_facts                    # noqa: E402
from screening.names import compare_parts, levenshtein, parts, variant_groups   # noqa: E402
from screening.resolve import Resolver                    # noqa: E402
from screening.store import Store                         # noqa: E402

store = Store()
res = Resolver(store, None)
alerts = {a["alert_id"]: a for a in store.alerts}
dec = {json.loads(l)["hit_id"]: json.loads(l) for l in open(Path(__file__).resolve().parents[1] / "outputs/decisions.jsonl", encoding="utf-8")}


def how(x, y):
    if x == y:
        return "="
    if variant_groups(x) & variant_groups(y):
        return "~var"
    return f"~{levenshtein(x, y, 3)}ed"


def best_pairs(cnames, hnames, company):
    best = None
    for c in cnames:
        for h in hnames:
            r = compare_parts(parts(c, company), parts(h, company))
            if best is None or (r.agrees, r.matched) > (best[0].agrees, best[0].matched):
                best = (r, c, h)
    return best


want = sys.argv[1]
rows = [d for d in dec.values() if d["decision"] == want or d["reason_codes"][0] == want]
print(f"{len(rows)} hits")
for d in sorted(rows, key=lambda d: d["hit_id"]):
    h = store.hits[d["hit_id"]]
    a = alerts[h["alert_id"]]
    r = res.resolve(a)
    hf = hit_facts(h, store, None)
    for i, p in enumerate(r.people):
        company = p.is_company
        cn = [p.verified_name.value] if p.verified_name else [f.value for f in p.record_names]
        b = best_pairs(cn, hf.names, company)
        pairs = " ".join(f"{x}{how(x, y)}" if x != y else x for x, y in (b[0].pairs if b else ()))
        dob = str(p.dob.value) if p.dob else "-"
        hd = ";".join(x.describe() + ("@SR" if x.source.startswith("SR-") else "") for x in hf.dobs) or "-"
        shared = sorted(p.country_set() & hf.countries)
        tag = f"{d['hit_id']}{'' if i == 0 else f' p{i + 1}'}"
        print(f"{tag:12} {d['reason_codes'][0][:22]:22} sc{h['match_score']:<3} | cust '{cn[0][:30]}' vs hit '{(b[2] if b else h['name'])[:30]}' "
              f"[{pairs}] | dob {dob} vs {hd} | ctry {','.join(sorted(p.country_set()))[:30]} / {','.join(sorted(hf.countries))[:30]} "
              f"shared={','.join(shared) or '-'}")
