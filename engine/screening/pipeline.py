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
from .evidence import describe
from .grok import Grok
from .resolve import Resolver
from .store import Store


def evidence_steps(evidence: list[str], store: Store, several: bool) -> list[str]:
    """One path step per cited check, note and search result, worded and ordered as the labels do."""
    steps = []
    for kid in (e for e in evidence if e.startswith("KYC-")):
        k = store.kyc_by_id.get(kid)
        rows = store.onboarding_by_applicant.get(k["applicant_id"], []) if k else []
        if several or not rows:
            steps.append(f"customer -> accounts  -> onboarding  -> latest approved check {kid}")
        else:
            o = rows[0]
            steps.append(f"{o['customer_id']} -> accounts {o['account_id']} -> onboarding {o['kyc_applicant_id']} "
                         f"-> latest approved check {kid}")
    steps += [f"customer email -> notes -> {n}" for n in evidence if n.startswith("NOTE-")]
    steps += [f"search results for the hit's name -> {r} (same role and country as the hit)"
              for r in evidence if r.startswith("SR-")]
    return steps


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
        evidence = list(dict.fromkeys(v.evidence))
        path = list(res.path) + evidence_steps(evidence, store, several=len(res.people) > 1)
        path.append(f"{v.decision} {[v.reason] + v.also}: {v.explanation}")
        label = store.labels.get(hit_id)
        people = [] if res.people[0].from_alert_only else res.people
        # describe our evidence, and the label's too, so the page can explain both side by side
        # with several people, each may rest on a different reason: judge relevance by all of them
        all_codes = list(dict.fromkeys([v.reason] + v.also + [c for _, pv in verdicts for c in [pv.reason] + pv.also]))
        detail = describe(store, evidence + (label["evidence"] if label else []), people, hf, all_codes)
        out.append({
            "hit_id": hit_id,
            "alert_id": alert["alert_id"],
            "decision": v.decision,
            "reason_codes": [v.reason] + v.also,
            "customer_record_ids": cust_ids,
            "evidence": evidence,
            "reference_reason": v.explanation,
            "path": " → ".join(path),
            "extraction_methods": hf.methods,
            "evidence_detail": detail,
        })
    return out


LABEL_COLUMNS = ["hit_id", "alert_id", "decision", "reason_codes", "customer_record_ids", "evidence",
                 "reference_reason", "path"]


def write_csv(rows: list[dict], path: str) -> None:
    """The practice labels' table format: same columns, lists joined with '; '."""
    import csv
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(LABEL_COLUMNS)
        for r in rows:
            w.writerow(["; ".join(r[c]) if isinstance(r[c], list) else r[c] for c in LABEL_COLUMNS])
    print(f"csv -> {path}")


def alert_outcome(decisions: list[str]) -> str:
    """The alert's result, in the hits' own terms (POLICY): SAME_ENTITY if any hit is the customer
    (the alert goes to compliance); DIFFERENT_ENTITY only when every hit is cleared; otherwise REVIEW."""
    if "SAME_ENTITY" in decisions:
        return "SAME_ENTITY"
    if decisions and all(d == "DIFFERENT_ENTITY" for d in decisions):
        return "DIFFERENT_ENTITY"
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
            "methods": r["extraction_methods"], "evidence_detail": r["evidence_detail"],
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
                 "alert_results": {k: list(outcomes.values()).count(k)
                                   for k in ("DIFFERENT_ENTITY", "REVIEW", "SAME_ENTITY")},
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
    ap.add_argument("--csv", help="also write the decisions as a CSV in the practice labels' columns and format")
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
    if args.csv:
        write_csv(rows, args.csv)
    if args.casebook:
        engine = "regex only" if grok is None else ("regex + Grok cache" if grok.offline else f"regex + Grok ({grok.model})")
        write_casebook(rows, alerts, store, args.casebook, engine)
    print(f"done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
