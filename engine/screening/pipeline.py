"""Run the workflow over every alert and write one decision per hit.

    python -m screening.pipeline                       # all alerts, Grok if XAI_API_KEY is set
    python -m screening.pipeline --grok off            # regex only
    python -m screening.pipeline --alerts A-957E63     # one alert, prints the trail
    python -m screening.pipeline --labelled            # only alerts that have practice labels
"""
from __future__ import annotations

import argparse
import json
import time

from .config import OUTPUTS
from .dates import PDate
from .decide import combine, decide_one, hit_facts
from .grok import Grok
from .resolve import Resolver
from .store import Store


def run_alert(alert: dict, store: Store, resolver: Resolver, grok: Grok | None) -> list[dict]:
    res = resolver.resolve(alert)
    screened_at = PDate.from_iso(alert["screened_at"])
    out = []
    for hit_id in alert["hit_ids"]:
        hit = store.hits[hit_id]
        hf = hit_facts(hit, store, grok)
        verdicts = [(p, decide_one(p, hf, screened_at)) for p in res.people]
        v, cust_ids = combine(verdicts)
        if res.people[0].from_alert_only:
            cust_ids = []
        path = list(res.path)
        if hf.dobs:
            path.append(f"hit date of birth from {hf.dob_source_note}: "
                        f"{'; '.join(d.describe() for d in hf.dobs)}")
        path.append(f"{v.decision} [{v.reason}]: {v.explanation}")
        out.append({
            "hit_id": hit_id,
            "alert_id": alert["alert_id"],
            "decision": v.decision,
            "reason_codes": [v.reason] + v.also,
            "customer_record_ids": cust_ids,
            "evidence": list(dict.fromkeys(v.evidence)),
            "reference_reason": v.explanation,
            "path": " → ".join(path),
            "extraction_methods": hf.methods,
        })
    return out


def alert_outcome(decisions: list[str]) -> str:
    """POLICY: an alert is cleared only when every hit is DIFFERENT_ENTITY; any SAME_ENTITY goes to compliance."""
    if "SAME_ENTITY" in decisions:
        return "ESCALATE"
    if all(d == "DIFFERENT_ENTITY" for d in decisions):
        return "CLEARED"
    return "REVIEW"


def write_casebook(rows: list[dict], alerts: list[dict], store: Store, path: str, engine: str) -> None:
    """Write window.DECISIONS for visual/casebook.html. A script, not JSON, so the page opens from disk."""
    from datetime import datetime, timezone
    from .evaluate import load_labels, score

    by_hit = {r["hit_id"]: r for r in rows}
    s = score(load_labels(), by_hit)
    per = s.pop("per_hit", {})
    hits = {}
    for r in rows:
        hits[r["hit_id"]] = {
            "decision": r["decision"], "reason_codes": r["reason_codes"],
            "customer_record_ids": r["customer_record_ids"], "evidence": r["evidence"],
            "reason": r["reference_reason"], "path": r["path"].split(" → "),
            "methods": r["extraction_methods"],
            **({"vs_label": per[r["hit_id"]]} if r["hit_id"] in per else {}),
        }
    outcomes = {a["alert_id"]: alert_outcome([by_hit[h]["decision"] for h in a["hit_ids"] if h in by_hit])
                for a in alerts}
    counts = {}
    for r in rows:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
    data = {
        "meta": {"built": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "engine": engine,
                 "hits": len(rows), "alerts": len(alerts), "decisions": counts,
                 "outcomes": {k: list(outcomes.values()).count(k) for k in ("CLEARED", "REVIEW", "ESCALATE")},
                 "labels": s},
        "hits": hits, "alerts": outcomes,
    }
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("window.DECISIONS = ")
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")
    print(f"casebook decisions -> {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--grok", choices=["auto", "off", "cache"], default="auto",
                    help="auto: call Grok when a key is set; cache: use cached answers only; off: regex only")
    ap.add_argument("--alerts", nargs="*", help="only these alert IDs")
    ap.add_argument("--labelled", action="store_true", help="only alerts with practice labels")
    ap.add_argument("--out", default=str(OUTPUTS / "decisions.jsonl"))
    ap.add_argument("--casebook", help="also write the decisions for visual/casebook.html (e.g. ../visual/decisions.js)")
    args = ap.parse_args()

    t0 = time.time()
    store = Store()
    grok = None if args.grok == "off" else Grok(offline=args.grok == "cache")
    resolver = Resolver(store, grok)
    print(f"loaded in {time.time() - t0:.1f}s; {grok.stats() if grok else 'grok off'}")

    alerts = store.alerts
    if args.alerts:
        alerts = [a for a in alerts if a["alert_id"] in set(args.alerts)]
    if args.labelled:
        wanted = {l["alert_id"] for l in store.labels.values()}
        alerts = [a for a in alerts if a["alert_id"] in wanted]

    rows = []
    for a in alerts:
        rows += run_alert(a, store, resolver, grok)
    OUTPUTS.mkdir(exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if args.alerts and len(rows) <= 10:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False, indent=1))
    counts = {}
    for r in rows:
        counts[r["decision"]] = counts.get(r["decision"], 0) + 1
    print(f"{len(rows)} hits from {len(alerts)} alerts -> {args.out}  {counts}")
    if grok:
        print(grok.stats())
    if args.casebook:
        engine = "regex only" if grok is None else ("regex + Grok cache" if grok.offline else f"regex + Grok ({grok.model})")
        write_casebook(rows, alerts, store, args.casebook, engine)
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
