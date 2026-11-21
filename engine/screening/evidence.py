"""Plain-language descriptions of evidence IDs: what each record is, and what the decision used it for."""
from __future__ import annotations

from .decide import HitFacts
from .resolve import Person
from .store import Store


def _join(*parts) -> str:
    return ", ".join(p for p in parts if p)


def what(store: Store, eid: str) -> tuple[str, str]:
    """(kind, summary) for one evidence ID."""
    if c := store.customers.get(eid):
        born = "incorporated" if c["entity_type"] == "Company" else "born"
        places = " / ".join(dict.fromkeys(x for x in (c["nationality"], c["residence_country"]) if x))
        return "Customer record", _join(c["full_name"] + (f" ({c['preferred_name']})" if c["preferred_name"] else ""),
                                        f"{born} {c['dob']}" if c["dob"] else None, places or None, c["city"])
    if k := store.kyc_by_id.get(eid):
        return "KYC check", (f"{k['provider']} {k['result']} a {k['document_type']} on {k['checked_at']}: "
                             + _join(k["verified_name"], f"born {k['verified_dob']}" if k["verified_dob"] else None,
                                     f"document from {k['document_country']}" if k["document_country"] else None))
    if n := store.notes_by_id.get(eid):
        kind = "KYC note (onboarding team)" if n["channel"] == "kyc" else f"Support note ({n['channel']})"
        return kind, f"{n['created_at']}: {n['text']}"
    if s := store.search_by_id.get(eid):
        return "Web search result", f"{s['source']}: {s['snippet']}"
    return "Record", eid


def used_for(eid: str, people: list[Person], hf: HitFacts) -> list[str]:
    """What the engine took from this record, for any person who fits the alert."""
    roles: list[str] = []
    for p in people:
        if eid in p.record_ids:
            roles.append("one of the customer's records" if len(p.record_ids) > 1 else "the customer's record")
        if p.verified_name and p.verified_name.source == eid:
            roles.append(f"verified legal name: {p.verified_name.value}")
        if p.dob and p.dob.source == eid:
            roles.append(f"customer's {'incorporation date' if p.is_company else 'date of birth'}: {p.dob.value}")
        ctry = sorted({f.value for f in p.countries if f.source == eid})
        if ctry:
            shared = [c for c in ctry if c in hf.countries]
            roles.append(f"ties the customer to {', '.join(ctry)}"
                         + (f" (shared with the hit: {', '.join(shared)})" if shared else ""))
    for d in hf.dobs:
        if d.source == eid:
            roles.append(f"hit's date of birth: {d.describe()} (age at a date, in the hit's country and listing type)")
    return list(dict.fromkeys(roles))


# which facts each reason code rests on (role prefixes from used_for)
_RELEVANT = {
    "ENTITY_TYPE_MISMATCH": ("the customer's record", "one of the customer's records"),
    "DECEASED": ("the customer's record", "one of the customer's records"),
    "TEMPORAL_IMPOSSIBILITY": ("customer's date of birth", "customer's incorporation date", "the customer's record",
                               "one of the customer's records"),
    "DOB_MISMATCH": ("customer's date of birth", "customer's incorporation date", "hit's date of birth"),
    "NAME_MISMATCH_VERIFIED": ("verified legal name",),
    "LOCATION_MISMATCH": ("ties the customer", "the customer's record", "one of the customer's records"),
    "NAME_DOB_LOCATION_MATCH": ("the customer's record", "one of the customer's records", "verified legal name",
                                "customer's date of birth", "hit's date of birth", "ties the customer"),
    "NAME_DOB_MATCH": ("the customer's record", "one of the customer's records", "verified legal name",
                       "customer's date of birth", "hit's date of birth"),
    "NAME_LOCATION_MATCH": ("the customer's record", "one of the customer's records", "verified legal name",
                            "ties the customer"),
    "INSUFFICIENT_DATA": ("ties the customer",),
    "AMBIGUOUS_CUSTOMER_RECORD": (),
}


def describe(store: Store, ids: list[str], people: list[Person], hf: HitFacts,
             reason_codes: list[str]) -> dict[str, dict]:
    """For each ID: what it is, and what it contributed to this decision. Roles that don't bear on the
    given reason codes are listed separately as 'also_has', so nothing is hidden."""
    keep = tuple(p for code in reason_codes for p in _RELEVANT.get(code, ()))
    out = {}
    for eid in dict.fromkeys(ids):
        kind, summary = what(store, eid)
        roles = used_for(eid, people, hf)
        rel = [r for r in roles if r.startswith(keep)] if keep else roles
        out[eid] = {"kind": kind, "summary": summary, "used_for": rel,
                    "also_has": [r for r in roles if r not in rel]}
    return out
