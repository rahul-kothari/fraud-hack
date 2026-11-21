"""Step 3: decide one hit against one person (POLICY principles 5-8), then combine people (principle 3)."""
from __future__ import annotations

from dataclasses import dataclass, field

from .dates import BirthSpec, PDate, dob_agrees, dob_contradicts, max_age_at
from .extract import earliest_dated_report, profile_dob, search_dobs, search_query
from .grok import Grok
from .names import compare_parts, parts
from .resolve import Person
from .store import Store

DIFFERENT, SAME, REVIEW = "DIFFERENT_ENTITY", "SAME_ENTITY", "REVIEW"


@dataclass
class HitFacts:
    hit_id: str
    entity_type: str
    names: list[str]
    dobs: list[BirthSpec]
    dob_source_note: str
    countries: set[str]
    earliest_report: tuple[PDate, str] | None
    deceased: PDate | None
    methods: list[str] = field(default_factory=list)   # how each extracted fact was obtained


def hit_facts(hit: dict, store: Store, grok: Grok | None) -> HitFacts:
    company = hit["entity_type"] == "Company"
    dobs: list[BirthSpec] = []
    note, methods = "", []
    for raw, iso in zip(hit["dobs"], hit["dobs_iso"]):
        if p := PDate.from_iso(iso):
            dobs.append(BirthSpec.exact(p, "dobs", raw))
    if dobs:
        note = "dobs field"
    elif not company:  # for companies only the dobs field is an incorporation date
        if pd := profile_dob(hit, grok):
            dobs.append(pd.spec)
            note, methods = "profile notes", [f"profile_dob:{pd.method}"]
        else:
            results = store.search_by_query.get(search_query(hit["name"]), [])
            for sd in search_dobs(hit, results, grok):
                dobs.append(sd.spec)
                methods.append(f"search:{sd.method}")
            if dobs:
                note = "search results"
    deceased = PDate.from_iso(hit["deceased_date_iso"])
    return HitFacts(hit["hit_id"], hit["entity_type"], [hit["name"]] + list(hit["aliases"]), dobs, note,
                    set(hit["countries_tied"]), earliest_dated_report(hit), deceased, methods)


@dataclass
class Verdict:
    decision: str
    reason: str
    evidence: list[str]
    explanation: str
    also: list[str] = field(default_factory=list)   # other reason codes that also apply


def _name_check(person: Person, hf: HitFacts, use_verified: bool) -> tuple[bool | None, list[str]]:
    """True/False whether a customer name agrees with any hit name; None when the customer's name has
    fewer than two real parts (individuals cannot be confirmed or cleared on name then)."""
    company = person.is_company
    if use_verified:
        if not person.verified_name:
            return None, []
        cust = [(person.verified_name.value, person.verified_name.source)]
    else:
        cust = [(person.verified_name.value, person.verified_name.source)] if person.verified_name else \
            [(f.value, f.source) for f in person.record_names]
    hit_parts = [parts(n, company) for n in hf.names]
    usable = False
    for cname, src in cust:
        cp = parts(cname, company)
        if not company and len(cp) < 2:
            continue
        usable = True
        for hp in hit_parts:
            if compare_parts(cp, hp).agrees:
                return True, [src]
    return (False if usable else None), [c[1] for c in cust]


def decide_one(person: Person, hf: HitFacts, screened_at: PDate) -> Verdict:
    recs = list(person.record_ids)
    p_company = person.is_company
    h_company = hf.entity_type == "Company"
    dob = person.dob.value if person.dob else None
    dob_src = [person.dob.source] if person.dob else []
    sr_src = [d.source for d in hf.dobs if d.source.startswith("SR-")]

    # --- contradictions (principle 6). Collect every one that applies: each code is accepted, and the
    # evidence cites what backs each of them (the labels do the same).
    found: list[tuple[str, list[str], str]] = []    # (code, evidence, explanation)
    if p_company != h_company:
        found.append(("ENTITY_TYPE_MISMATCH", recs,
                      f"The customer is {'a company' if p_company else 'a person'} and the hit is "
                      f"{'a company' if h_company else 'a person'}."))
    if hf.deceased and hf.deceased.latest() < screened_at.earliest():
        found.append(("DECEASED", recs,
                      f"The hit died on {hf.deceased} before the customer was screened on {screened_at}."))
    if hf.earliest_report and dob:
        at, line = hf.earliest_report
        if p_company and dob.earliest() > at.latest():
            found.append(("TEMPORAL_IMPOSSIBILITY", recs + dob_src,
                          f"The company was incorporated on {dob}, after the earliest report dated {at}."))
        elif not p_company and max_age_at(dob, at) < 16:
            found.append(("TEMPORAL_IMPOSSIBILITY", recs + dob_src,
                          f"The customer (born {dob}) was under 16 at the earliest report dated {at}."))
    if dob and hf.dobs and all(dob_contradicts(dob, h) for h in hf.dobs):
        # cite the customer's DOB source and any search result that gave the hit's DOB
        found.append(("DOB_MISMATCH", dob_src + sr_src,
                      f"The customer's date of birth {dob} contradicts every date the hit gives "
                      f"({'; '.join(h.describe() for h in hf.dobs)})."))
    verified_agree, v_src = _name_check(person, hf, use_verified=True)
    if verified_agree is False:
        found.append(("NAME_MISMATCH_VERIFIED", v_src,                 # the verified check only
                      f"The customer's verified name {person.verified_name.value} agrees with none of the "
                      f"hit's names."))

    name_agree, n_src = _name_check(person, hf, use_verified=False)
    dob_agree = bool(dob and any(dob_agrees(dob, h) for h in hf.dobs))
    cc, hc = person.country_set(), hf.countries
    shared = cc & hc
    countries_differ = bool(cc and hc and not shared)
    if countries_differ and not (name_agree and dob_agree):
        c_src = sorted({f.source for f in person.countries} - set(recs))
        found.append(("LOCATION_MISMATCH", recs + c_src,
                      f"Every country tied to the customer ({', '.join(sorted(cc))}) differs from every "
                      f"country tied to the hit ({', '.join(sorted(hc))})."))
    if found:
        return Verdict(DIFFERENT, found[0][0], list(dict.fromkeys(e for f in found for e in f[1])),
                       " ".join(f[2] for f in found), also=[f[0] for f in found[1:]])
    if countries_differ:   # name and DOB agree: a country difference alone does not clear
        return Verdict(REVIEW, "INSUFFICIENT_DATA", recs + dob_src + sr_src,
                       "Name and date of birth agree but the countries differ.")

    # --- agreement (principle 7)
    if not p_company and name_agree and dob_agree:
        code = "NAME_DOB_LOCATION_MATCH" if shared else "NAME_DOB_MATCH"
        return Verdict(SAME, code, recs + dob_src + sr_src + [s for s in n_src if s not in recs],
                       f"The customer's date of birth {dob} agrees with the hit's "
                       f"{'; '.join(h.describe() for h in hf.dobs)}; the names agree"
                       f"{'; both are linked to ' + ', '.join(sorted(shared)) if shared else ''}.")
    if p_company and name_agree and shared:
        return Verdict(SAME, "NAME_LOCATION_MATCH", recs + [s for s in n_src if s not in recs],
                       f"The company names agree and both are linked to {', '.join(sorted(shared))}.")
    # REVIEW: cite what ties the customer to the hit's countries (records, checks or residence notes)
    shared_src = list(dict.fromkeys(f.source for f in person.countries if f.value in shared))
    missing = []
    if not name_agree:
        missing.append("name")
    if not p_company and not dob_agree:
        missing.append("date of birth" if hf.dobs and dob else "a date of birth to compare")
    if p_company and not shared:
        missing.append("country")
    return Verdict(REVIEW, "INSUFFICIENT_DATA", shared_src or (recs + dob_src + sr_src),
                   f"No contradiction, but no agreement on {' and '.join(missing) or 'enough facts'}.")


def combine(verdicts: list[tuple[Person, Verdict]]) -> tuple[Verdict, list[str]]:
    """Principle 3: several people fit -> same decision for all, or REVIEW / AMBIGUOUS_CUSTOMER_RECORD."""
    if len(verdicts) == 1:
        person, v = verdicts[0]
        return v, list(person.record_ids)
    evidence = list(dict.fromkeys(e for _, v in verdicts for e in v.evidence))
    decisions = {v.decision for _, v in verdicts}
    if len(decisions) == 1:
        first = verdicts[0][1]
        return Verdict(first.decision, first.reason, evidence,
                       f"{len(verdicts)} people fit and every one leads to {first.decision}. "
                       + first.explanation), ["AMBIGUOUS"]
    return Verdict(REVIEW, "AMBIGUOUS_CUSTOMER_RECORD", evidence,
                   f"{len(verdicts)} people fit the alert and they lead to different decisions "
                   f"({', '.join(sorted(decisions))})."), ["AMBIGUOUS"]
