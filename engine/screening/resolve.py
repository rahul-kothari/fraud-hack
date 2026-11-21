"""Step 1 and the customer half of step 2: find who the alert is about and build their picture.

POLICY principle 2 (find the customer), 3 (one person, one picture) and 4 (verified beats declared).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from . import countries
from .dates import PDate
from .extract import KycNote, parse_kyc_note, parse_residence_note
from .grok import Grok
from .names import levenshtein, names_agree, part_match, parts, variant_groups
from .store import Store, norm_phone


# ------------------------------------------------------------- people (groups)

class People:
    """Union-find over customer records: same phone + same full DOB, or same document number on
    approved checks, means the same person; links chain (principle 3)."""

    def __init__(self, store: Store):
        self.parent = {rid: rid for rid in store.customers}
        by_phone_dob = defaultdict(list)
        for rid, c in store.customers.items():
            ph, dob = norm_phone(c["phone"]), c["dob_iso"]
            if ph and dob and len(dob) == 10:
                by_phone_dob[(ph, dob)].append(rid)
        for group in by_phone_dob.values():
            self._union_all(group)
        by_doc = defaultdict(set)
        for k in store.kyc:
            if k["result"] == "approved" and k["document_number"]:
                for o in store.onboarding_by_applicant.get(k["applicant_id"], []):
                    by_doc[k["document_number"]].add(o["customer_id"])
        for group in by_doc.values():
            self._union_all([g for g in group if g in self.parent])
        self.members = defaultdict(list)
        for rid in store.customers:
            self.members[self.find(rid)].append(rid)

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def _union_all(self, ids: list[str]) -> None:
        for other in ids[1:]:
            a, b = self.find(ids[0]), self.find(other)
            if a != b:
                self.parent[b] = a

    def records_of(self, rid: str) -> list[str]:
        return sorted(self.members[self.find(rid)])


# ----------------------------------------------------------- name search index

class NameIndex:
    """Name part -> customer records, for alerts with no link."""

    def __init__(self, store: Store):
        self.by_part = defaultdict(set)
        for rid, c in store.customers.items():
            company = c["entity_type"] == "Company"
            for n in (c["full_name"], c["preferred_name"], c["login_name"]):
                for p in parts(n, company):
                    self.by_part[p].add(rid)
        self.all_parts = list(self.by_part)

    def candidates(self, name: str, company: bool) -> set[str]:
        out: set[str] = set()
        q = parts(name, company)
        joined = [q[i] + q[i + 1] for i in range(len(q) - 1)]
        for p in list(q) + joined:
            for cand in self.all_parts:
                if abs(len(cand) - len(p)) <= 2 and (cand[0] == p[0] or variant_groups(p)) and part_match(p, cand):
                    out |= self.by_part[cand]
        return out


# --------------------------------------------------------------- the customer

@dataclass
class Fact:
    value: object
    source: str            # record or note/check ID


@dataclass
class Person:
    record_ids: list[str]
    entity_type: str
    record_names: list[Fact]
    verified: KycNote | dict | None = None       # most recent approved check (KYC row or parsed note)
    verified_name: Fact | None = None
    dob: Fact | None = None                      # PDate
    countries: list[Fact] = field(default_factory=list)
    from_alert_only: bool = False                # no customer record found

    @property
    def is_company(self) -> bool:
        return self.entity_type == "Company"

    def country_set(self) -> set[str]:
        return {f.value for f in self.countries}


def _fits(c: dict, alert: dict) -> bool:
    """Principle 2: a record fits the screened details when every screened field present agrees."""
    company = c["entity_type"] == "Company"
    name_ok = any(names_agree(alert["customer_name"], n, company).agrees
                  for n in (c["full_name"], c["preferred_name"], c["login_name"]) if n)
    if not name_ok:
        return False
    a_dob, c_dob = PDate.from_iso(alert["dob_iso"]), PDate.from_iso(c["dob_iso"])
    if a_dob and c_dob:
        if a_dob.year != c_dob.year or (a_dob.month and c_dob.month and a_dob.month != c_dob.month) \
                or (a_dob.day and c_dob.day and a_dob.day != c_dob.day):
            return False
    if alert["country_norm"] and alert["country_norm"] not in {c["residence_country_norm"], c["nationality_norm"]}:
        return False
    if alert["city"]:
        city = alert["city"].lower()
        if city not in (c["city"] or "").lower() and city not in (c["address"] or "").lower():
            return False
    return True


@dataclass
class Resolution:
    people: list[Person]
    linked_records: list[str]
    path: list[str]


class Resolver:
    def __init__(self, store: Store, grok: Grok | None):
        self.store = store
        self.grok = grok
        self.people = People(store)
        self._name_index: NameIndex | None = None

    @property
    def name_index(self) -> NameIndex:
        if self._name_index is None:
            self._name_index = NameIndex(self.store)
        return self._name_index

    def resolve(self, alert: dict) -> Resolution:
        s, path = self.store, []
        # Path steps use the practice labels' wording.
        linked: list[str] = []
        step = ""
        accounts = []
        if alert["account_ref"]:
            accounts = s.accounts_by_id.get(alert["account_ref"], [])
            linked = [a["customer_id"] for a in accounts]
            step = f"account_ref {alert['account_ref']} -> accounts"
        elif alert["login_handle"]:
            accounts = s.accounts_by_login.get(alert["login_handle"].lower(), [])
            linked = [a["customer_id"] for a in accounts]
            step = f"login_handle {alert['login_handle']} -> accounts {', '.join(dict.fromkeys(a['account_id'] for a in accounts)) or 'none'}"
        elif alert["email"]:
            linked = s.customers_by_email.get(alert["email"].lower(), [])
            step = f"email {alert['email']} -> customers"
        linked = [r for r in dict.fromkeys(linked) if r in s.customers]

        if linked:
            fits = [r for r in linked if _fits(s.customers[r], alert)]
            if len(linked) > 1 and alert["account_ref"]:
                holders = fits + [r for r in linked if r not in fits]     # the one who fits first
                step += f": joint holders {' and '.join(holders)}"
            else:
                step += f" -> {'customer ' if not alert['email'] else ''}{', '.join(linked)}"
            groups = {self.people.find(r) for r in linked}
            if len(groups) > 1:
                fitting = [r for r in linked if _fits(s.customers[r], alert)]
                if fitting:
                    step += f" -> the screened name and date of birth fit {', '.join(fitting)}"
                    linked = fitting
                else:
                    step += " -> the screened details fit none of them; all are kept"
            path.append(step)
            records = linked
        else:
            if step:
                path.append(step + " -> no customer")
            company = alert["entity_type"] == "Company"
            cands = self.name_index.candidates(alert["customer_name"], company)
            records = sorted(r for r in cands if _fits(s.customers[r], alert))
            path.append("name, date of birth, country and city -> customers")

        roots = list(dict.fromkeys(self.people.find(r) for r in records))
        people = [self.build_person(self.people.records_of(root)) for root in roots]
        if len(people) > 1:
            all_recs = sorted({r for p in people for r in p.record_ids})
            path.append(f"{len(people)} different people fit (records {', '.join(all_recs)}); "
                        f"each is decided separately")
        for p in people if len(people) == 1 else []:   # the labels skip this step when several people fit
            if len(p.record_ids) > 1:
                first = [r for r in records if r in p.record_ids]
                order = first + [r for r in p.record_ids if r not in first]
                path.append("same phone and date of birth, or same document number on approved checks "
                            f"-> one person: {', '.join(order)}")
        if not people:
            people = [self.person_from_alert(alert)]
        return Resolution(people, records, path)

    # ------------------------------------------------------------ profiles

    def build_person(self, record_ids: list[str]) -> Person:
        s = self.store
        recs = [s.customers[r] for r in record_ids]
        etype = recs[0]["entity_type"]
        p = Person(record_ids, etype,
                   [Fact(n, c["record_id"]) for c in recs for n in (c["full_name"], c["preferred_name"]) if n])

        # Verified identity: most recent approved check, from the KYC provider or an onboarding note.
        verified: list[tuple[tuple, str, str | None, PDate | None, str | None]] = []
        for c in recs:
            for k in s.kyc_checks_for(c["record_id"]):
                if k["result"] != "approved":
                    continue
                d = PDate.from_iso(k["checked_at"])
                verified.append((d.earliest() if d else (0, 0, 0), k["check_id"], k["verified_name"],
                                 PDate.from_iso(k["verified_dob_iso"]), k["document_country_norm"]))
            for n in s.notes_for(c["record_id"]):
                if n["channel"] == "kyc":
                    kn = parse_kyc_note(n, self.grok)
                    if kn and kn.approved:
                        d = kn.checked_at
                        verified.append((d.earliest() if d else (0, 0, 0), kn.note_id, kn.name, kn.dob,
                                         kn.document_country))
                else:
                    for ctry in parse_residence_note(n, self.grok):
                        p.countries.append(Fact(ctry, n["note_id"]))
        if verified:
            verified.sort(key=lambda v: (v[0], v[1]))
            _, src, vname, vdob, vctry = verified[-1]
            if vname:
                p.verified_name = Fact(vname, src)
            if vdob:
                p.dob = Fact(vdob, src)
            for _, s_id, _, _, ctry in verified:
                if ctry:
                    p.countries.append(Fact(ctry, s_id))
        if p.dob is None:
            for c in recs:
                if d := PDate.from_iso(c["dob_iso"]):
                    p.dob = Fact(d, c["record_id"])
                    break
        for c in recs:
            for ctry in (c["residence_country_norm"], c["nationality_norm"]):
                if ctry:
                    p.countries.append(Fact(ctry, c["record_id"]))
        return p

    def person_from_alert(self, alert: dict) -> Person:
        p = Person([], alert["entity_type"], [Fact(alert["customer_name"], alert["alert_id"])],
                   from_alert_only=True)
        if d := PDate.from_iso(alert["dob_iso"]):
            p.dob = Fact(d, alert["alert_id"])
        if alert["country_norm"]:
            p.countries.append(Fact(alert["country_norm"], alert["alert_id"]))
        return p
