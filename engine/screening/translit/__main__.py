"""Command line: compare names or romanize text.

    python -m screening.translit compare "Harunur Roshud" "Rashid, Harunur" "হারুনুর রশিদ"
    python -m screening.translit compare --type Company "Danske Bank A/S" "АО Данске банк"
    python -m screening.translit romanize "Олексій Володимирович Григор'єв"
"""
from __future__ import annotations

import argparse
import json

from . import NameMatcher, parse_name, spellings


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m screening.translit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("compare", help="customer name vs hit name and aliases")
    c.add_argument("customer")
    c.add_argument("hit_names", nargs="+", help="the hit's name followed by its aliases")
    c.add_argument("--type", default="Individual", help="Individual or Company")
    c.add_argument("--json", action="store_true")
    r = sub.add_parser("romanize", help="show the romanization of a name in any script")
    r.add_argument("text")
    r.add_argument("--n", type=int, default=5)
    args = ap.parse_args()

    if args.cmd == "compare":
        a = NameMatcher().assess([args.customer], args.hit_names, entity_type=args.type)
        if args.json:
            print(json.dumps({
                "status": a.status, "can_clear_on_name": a.can_clear, "supports_confirm": a.supports_confirm,
                "explanation": a.explain(), "independent_aliases": a.independent_aliases,
                "redundant_aliases": a.redundant_aliases,
                "matches": [m.__dict__ for m in a.best.matches],
            }, ensure_ascii=False, indent=2))
        else:
            print(f"status:            {a.status}")
            print(f"can clear on name: {a.can_clear}")
            print(f"supports confirm:  {a.supports_confirm}")
            print(f"why:               {a.explain()}")
            if a.redundant_aliases:
                print(f"redundant aliases: {a.redundant_aliases}")
            if a.independent_aliases:
                print(f"independent:       {a.independent_aliases}")
    else:
        p = parse_name(args.text)
        for part in p.parts:
            alts = part.lattice.spellings(args.n) if part.lattice else [part.text]
            print(f"{part.source:20s} -> {part.text:18s} [{part.script}] e.g. {', '.join(alts)}")
        for tok, why in p.dropped:
            print(f"{tok:20s} -> (dropped: {why})")
        print("spellings:", " | ".join(spellings(args.text, args.n)))


if __name__ == "__main__":
    main()
