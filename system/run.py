"""Entry point for the organisers: python run.py <data folder> <output file>.

Runs the rules engine in engine/screening over an official data folder and writes one line
per hit in the organisers' format (output.schema.json). Standard library only, no language
model: the same input gives the same output on every run.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent / "engine"
sys.path.insert(0, str(ENGINE))

from screening import ingest  # noqa: E402
from screening.pipeline import official_row, run_alert  # noqa: E402
from screening.resolve import Resolver  # noqa: E402
from screening.store import Store  # noqa: E402


def fallback(hit_id: str, alert_id: str, why: str) -> dict:
    """The safe answer when the engine cannot process an alert: send the hit to a human."""
    return {"hit_id": hit_id, "alert_id": alert_id, "decision": "REVIEW", "reason_code": "INSUFFICIENT_DATA",
            "customer_record_id": None, "evidence": [],
            "reason": f"The system could not process this alert ({why}), so the hit is left for an analyst to review."}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: system/run <data folder> <output file>", file=sys.stderr)
        return 2
    data, out = Path(argv[1]), Path(argv[2])
    t0 = time.time()
    if not ingest.is_official(data):
        print(f"{data} does not look like an official data folder (no alerts.jsonl with a customer)", file=sys.stderr)
        return 2
    store = Store(data)
    resolver = Resolver(store, None)
    hit_alert = {h["hit_id"]: h["alert_id"] for h in store.hits.values()}

    answers: dict[str, dict] = {}
    failed = 0
    for alert in store.alerts:
        try:
            for r in run_alert(alert, store, resolver, None):
                answers[r["hit_id"]] = official_row(r)
        except Exception as e:  # one bad record must not sink the run
            failed += 1
            print(f"{alert['alert_id']}: {type(e).__name__}: {e}", file=sys.stderr)
            traceback.print_exc(limit=3, file=sys.stderr)
            for h in alert["hit_ids"]:
                answers.setdefault(h, fallback(h, alert["alert_id"], type(e).__name__))
    # every hit gets exactly one line, in hits.jsonl order, even one no alert lists
    rows = [answers.get(h) or fallback(h, a, "no alert lists this hit") for h, a in hit_alert.items()]

    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts = {d: sum(r["decision"] == d for r in rows) for d in ("DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW")}
    print(f"{len(rows)} hits -> {out}  {counts}  ({failed} alerts fell back to REVIEW)  {time.time() - t0:.1f}s",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
