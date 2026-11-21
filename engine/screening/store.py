"""Loads processed/tables/*.jsonl and builds the lookup indexes the workflow needs."""
from __future__ import annotations

import json
import re
from collections import defaultdict

from .config import TABLES


def _load(name: str) -> list[dict]:
    with open(TABLES / f"{name}.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def norm_phone(p: str | None) -> str | None:
    return re.sub(r"\D", "", p) if p else None


class Store:
    def __init__(self) -> None:
        self.alerts = _load("alerts")
        self.hits = {h["hit_id"]: h for h in _load("hits")}
        self.customers = {c["record_id"]: c for c in _load("customers")}
        accounts = _load("accounts")
        onboarding = _load("onboarding")
        kyc = _load("kyc_checks")
        notes = _load("notes")
        search = _load("search_results")
        self.labels = {l["hit_id"]: l for l in _load("practice_labels")}

        self.customers_by_email = defaultdict(list)
        for c in self.customers.values():
            if c["email"]:
                self.customers_by_email[c["email"].lower()].append(c["record_id"])

        self.accounts_by_id = defaultdict(list)
        self.accounts_by_login = defaultdict(list)
        for a in accounts:
            self.accounts_by_id[a["account_id"]].append(a)
            if a["login_handle"]:
                self.accounts_by_login[a["login_handle"].lower()].append(a)

        self.onboarding_by_customer = defaultdict(list)
        self.onboarding_by_applicant = defaultdict(list)
        for o in onboarding:
            self.onboarding_by_customer[o["customer_id"]].append(o)
            self.onboarding_by_applicant[o["kyc_applicant_id"]].append(o)

        self.kyc_by_applicant = defaultdict(list)
        for k in kyc:
            self.kyc_by_applicant[k["applicant_id"]].append(k)
        self.kyc = kyc

        self.notes_by_email = defaultdict(list)
        for n in notes:
            if n["requester_email"]:
                self.notes_by_email[n["requester_email"].lower()].append(n)

        self.search_by_query = defaultdict(list)
        for s in search:
            self.search_by_query[s["query"]].append(s)

        # by ID, for describing evidence
        self.kyc_by_id = {k["check_id"]: k for k in kyc}
        self.notes_by_id = {n["note_id"]: n for n in notes}
        self.search_by_id = {s["result_id"]: s for s in search}

    # ---------------------------------------------------------------- helpers

    def kyc_checks_for(self, record_id: str) -> list[dict]:
        out = []
        for o in self.onboarding_by_customer.get(record_id, []):
            out += self.kyc_by_applicant.get(o["kyc_applicant_id"], [])
        return out

    def notes_for(self, record_id: str) -> list[dict]:
        email = self.customers[record_id]["email"]
        return self.notes_by_email.get(email.lower(), []) if email else []
