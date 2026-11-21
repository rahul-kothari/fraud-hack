"""Score decisions against the practice labels (see processed/docs/OUTPUT_FORMAT.md).

    python -m screening.evaluate [outputs/decisions.jsonl] [-v]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from .config import OUTPUTS, TABLES


def load_labels() -> dict[str, dict]:
    with open(TABLES / "practice_labels.jsonl", encoding="utf-8") as f:
        return {(l := json.loads(line))["hit_id"]: l for line in f}


def compare(label: dict, pred: dict) -> dict:
    """How one prediction compares with its label. Any listed reason code or customer record counts."""
    d = label["decision"] == pred["decision"]
    r = d and any(c in label["reason_codes"] for c in pred["reason_codes"][:1])
    c = bool(set(pred["customer_record_ids"]) & set(label["customer_record_ids"])) or \
        (not pred["customer_record_ids"] and not label["customer_record_ids"])
    le, pe = set(label["evidence"]), set(pred["evidence"])
    return {"decision": d, "reason": r, "customer": c,
            "evidence_precision": len(le & pe) / len(pe) if pe else 0.0,
            "evidence_recall": len(le & pe) / len(le) if le else 1.0,
            "worst": label["decision"] == "SAME_ENTITY" and pred["decision"] == "DIFFERENT_ENTITY"}


def score(labels: dict[str, dict], preds: dict[str, dict]) -> dict:
    common = [h for h in labels if h in preds]
    per = {h: compare(labels[h], preds[h]) for h in common}
    n = len(common)
    if not n:
        return {"scored": 0}
    return {
        "scored": n,
        "decision": sum(p["decision"] for p in per.values()),
        "reason": sum(p["reason"] for p in per.values()),
        "customer": sum(p["customer"] for p in per.values()),
        "evidence_precision": round(sum(p["evidence_precision"] for p in per.values()) / n, 3),
        "evidence_recall": round(sum(p["evidence_recall"] for p in per.values()) / n, 3),
        "worst": [h for h, p in per.items() if p["worst"]],
        "per_hit": per,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(OUTPUTS / "decisions.jsonl"))
    ap.add_argument("-v", "--verbose", action="store_true", help="print every mismatch with both paths")
    args = ap.parse_args()

    labels = load_labels()
    with open(args.path, encoding="utf-8") as f:
        preds = {(p := json.loads(line))["hit_id"]: p for line in f}
    s = score(labels, preds)
    n = s["scored"]
    if not n:
        print("no labelled hits in", args.path)
        return
    print(f"labelled hits scored: {n}")
    print(f"  decision          {s['decision']}/{n}  ({s['decision'] / n:.0%})")
    print(f"  decision+reason   {s['reason']}/{n}  ({s['reason'] / n:.0%})")
    print(f"  customer record   {s['customer']}/{n}  ({s['customer'] / n:.0%})")
    print(f"  evidence          precision {s['evidence_precision']:.0%}, recall {s['evidence_recall']:.0%}")
    print(f"  WORST (SAME cleared as DIFFERENT): {len(s['worst'])} {s['worst']}")
    confusion = Counter((labels[h]["decision"], preds[h]["decision"]) for h in s["per_hit"])
    print("\nconfusion (label -> predicted):")
    for (l, p), k in sorted(confusion.items()):
        print(f"  {l:17} -> {p:17} {k}")
    misses = [h for h, p in s["per_hit"].items() if not (p["decision"] and p["reason"] and p["customer"])]
    print(f"\nmismatches: {len(misses)}")
    for h in misses:
        L, P, p = labels[h], preds[h], s["per_hit"][h]
        flags = ",".join(k for k in ("decision", "reason", "customer") if not p[k])
        print(f"  {h} {L['alert_id']}  label {L['decision']}/{'|'.join(L['reason_codes'])} {L['customer_record_ids']}"
              f"  got {P['decision']}/{P['reason_codes'][0]} {P['customer_record_ids']}  [{flags}]")
        if args.verbose:
            print(f"      label: {L['path']}")
            print(f"      ours:  {P['path']}")


if __name__ == "__main__":
    main()
