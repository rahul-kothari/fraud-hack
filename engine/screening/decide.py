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


def _name_check(person: Person, hf: HitFacts, use_verified: bool) -> tuple[bool | None, list[str], str]:
    """Whether a customer name agrees with any hit name: (agrees, customer-name sources, hit name used).
    agrees is None when the customer's name has fewer than two real parts (individuals cannot be
    confirmed or cleared on name then)."""
    company = person.is_company
    if use_verified:
        if not person.verified_name:
            return None, [], hf.names[0]
        cust = [(person.verified_name.value, person.verified_name.source)]
    else:
        cust = [(person.verified_name.value, person.verified_name.source)] if person.verified_name else \
            [(f.value, f.source) for f in person.record_names]
    if company != (hf.entity_type == "Company"):
        # A company's name never agrees with a person's: "Stadtwerke München GmbH" is not "Mun Chen",
        # however the letters line up.
        return False, [c[1] for c in cust], hf.names[0]
    usable = False
    for cname, src in cust:
        cp = parts(cname, company)
        if not company and len(cp) < 2:
            continue
        usable = True
        for hname in hf.names:
            if compare_parts(cp, parts(hname, company)).agrees:
                return True, [src], hname
    return (False if usable else None), [c[1] for c in cust], hf.names[0]


# --- wording: the practice labels' templates -------------------------------------------------------

def _list(xs) -> str:
    return ", ".join(sorted(xs))


_TRANSLIT = None


def native_alias_agreement(person: Person, hf: HitFacts) -> tuple[str, str] | None:
    """Safety net for NAME_MISMATCH_VERIFIED (screening/translit). If the verified name agrees with the
    hit only through a native-script alias that has no Latin counterpart on the profile (e.g. the alias
    أنيس رحماني, Anis Rahmani, on 'Mokaddem, Mohamed'), the name cannot clear the hit.
    Returns (alias, its romanised reading) or None. It never confirms a match."""
    global _TRANSLIT
    if not person.verified_name or person.is_company != (hf.entity_type == "Company"):
        return None                       # names of a company and a person are never compared
    if _TRANSLIT is None:
        from .translit import NameMatcher
        _TRANSLIT = NameMatcher()
    a = _TRANSLIT.assess([person.verified_name.value], hf.names, entity_type=hf.entity_type,
                         customer_entity_type=person.entity_type)
    if a.status != "agree_via_transliteration":
        return None
    t = a.transliterated
    reading = " ".join(t.hit_parts) if t.hit_parts else t.hit_name
    return t.hit_name, reading


def _hit_dob_text(hf: HitFacts) -> str:
    """How the labels name the hit's dates: '1976 or 1977', '1994, 1995', '1968-02'."""
    return ", ".join(h.describe() for h in hf.dobs)


def _hit_dob_clause(hf: HitFacts) -> str:
    """The hit side of a DOB_MISMATCH sentence."""
    if hf.dob_source_note == "dobs field":
        many = len(hf.dobs) > 1
        return f"the hit's listed date{'s' if many else ''} of birth {'are' if many else 'is'} {_hit_dob_text(hf)}"
    where = "profile notes" if hf.dob_source_note == "profile notes" else "search results"
    if all(h.month is None for h in hf.dobs):
        return f"the hit's {where} put its birth year at {_hit_dob_text(hf)}"
    return f"the hit's {where} put its date of birth at {_hit_dob_text(hf)}"


# the order the labels list contradictions in
_ORDER = ["ENTITY_TYPE_MISMATCH", "DECEASED", "TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH", "LOCATION_MISMATCH",
          "NAME_MISMATCH_VERIFIED"]


def decide_one(person: Person, hf: HitFacts, screened_at: PDate) -> Verdict:
    recs = list(person.record_ids)
    p_company = person.is_company
    h_company = hf.entity_type == "Company"
    dob = person.dob.value if person.dob else None
    dob_src = [person.dob.source] if person.dob else []
    dsrc = person.dob.source if person.dob else ""
    sr_src = [d.source for d in hf.dobs if d.source.startswith("SR-")]

    # --- contradictions (principle 6). Collect every one that applies: each code is accepted, and the
    # evidence cites what backs each of them (the labels do the same).
    found: list[tuple[str, list[str], str]] = []    # (code, evidence, sentence)
    if p_company != h_company:
        found.append(("ENTITY_TYPE_MISMATCH", recs,
                      f"The customer is {'a company' if p_company else 'a person'} but the hit is "
                      f"{'a company' if h_company else 'a person'}."))
    if hf.deceased and hf.deceased.latest() < screened_at.earliest():
        found.append(("DECEASED", recs,
                      f"The hit's profile gives a date of death of {hf.deceased}, before the customer was "
                      f"screened on {screened_at}."))
    if hf.earliest_report and dob:
        at, line = hf.earliest_report
        if p_company and dob.earliest() > at.latest():
            found.append(("TEMPORAL_IMPOSSIBILITY", recs + dob_src,
                          f"The customer was incorporated on {dob} ({dsrc}), after the hit's profile reports "
                          f"activity on {at}."))
        elif not p_company and max_age_at(dob, at) < 16:
            found.append(("TEMPORAL_IMPOSSIBILITY", recs + dob_src,
                          f"The customer was born in {dob.year} ({dsrc}), so they were at most "
                          f"{at.year - dob.year} when the hit's profile reports activity on {at}."))
    if dob and hf.dobs and all(dob_contradicts(dob, h) for h in hf.dobs):
        # cite the customer's DOB source and any search result that gave the hit's DOB
        found.append(("DOB_MISMATCH", dob_src + sr_src,
                      f"The customer's date of birth is {dob} ({dsrc}) but {_hit_dob_clause(hf)}."))
    verified_agree, v_src, _ = _name_check(person, hf, use_verified=True)
    native = native_alias_agreement(person, hf) if verified_agree is False else None
    if verified_agree is False and native is None:
        found.append(("NAME_MISMATCH_VERIFIED", v_src,                 # the verified check only
                      f"The customer's verified name is {person.verified_name.value} "
                      f"({person.verified_name.source}), which does not match the hit's name {hf.names[0]}."))

    name_agree, n_src, matched = _name_check(person, hf, use_verified=False)
    dob_agree = bool(dob and any(dob_agrees(dob, h) for h in hf.dobs))
    cc, hc = person.country_set(), hf.countries
    shared = cc & hc
    countries_differ = bool(cc and hc and not shared)
    if countries_differ and not (name_agree and dob_agree):
        c_src = sorted({f.source for f in person.countries} - set(recs))
        found.append(("LOCATION_MISMATCH", recs + c_src,
                      f"The customer is linked only to {_list(cc)} but the hit is linked only to {_list(hc)}."))
    if found:
        found.sort(key=lambda f: _ORDER.index(f[0]))
        return Verdict(DIFFERENT, found[0][0], list(dict.fromkeys(e for f in found for e in f[1])),
                       " ".join(f[2] for f in found), also=[f[0] for f in found[1:]])

    dob_sentence = (f"The customer's date of birth {dob} ({dsrc}) agrees with the hit's {_hit_dob_text(hf)}."
                    if dob_agree else "")
    name_sentence = f"The customer's name agrees with the hit's name {matched}."
    shared_sentence = f"Both the customer and the hit are linked to {_list(shared)}." if shared else ""

    if countries_differ:   # name and DOB agree: a country difference alone does not clear
        return Verdict(REVIEW, "INSUFFICIENT_DATA", recs + dob_src + sr_src,
                       f"{dob_sentence} {name_sentence} The customer is linked only to {_list(cc)} but the hit "
                       f"is linked only to {_list(hc)}. A country difference does not clear a hit whose name "
                       f"and date of birth agree, so the hit can be neither cleared nor confirmed.")

    # --- agreement (principle 7)
    if not p_company and name_agree and dob_agree:
        code, also = ("NAME_DOB_LOCATION_MATCH", ["NAME_DOB_MATCH"]) if shared else ("NAME_DOB_MATCH", [])
        return Verdict(SAME, code, recs + dob_src + sr_src + [s for s in n_src if s not in recs],
                       " ".join(x for x in (dob_sentence, shared_sentence, name_sentence) if x), also=also)
    if p_company and name_agree and shared:
        return Verdict(SAME, "NAME_LOCATION_MATCH", recs + [s for s in n_src if s not in recs],
                       f"{shared_sentence} {name_sentence}")

    # REVIEW: cite what ties the customer to the hit's countries (records, checks or residence notes)
    shared_src = list(dict.fromkeys(f.source for f in person.countries if f.value in shared))
    said = [shared_sentence]
    if native:
        alias, reading = native
        said.append(f"The customer's verified name {person.verified_name.value} ({person.verified_name.source}) "
                    f"does not match the hit's Latin names, but it agrees with the hit's alias {alias}, read as "
                    f"{reading}. That alias has no Latin counterpart, so the name cannot clear the hit.")
    elif name_agree:
        said.append(name_sentence)
    elif name_agree is None:
        said.append("The customer's name has fewer than two real parts, so it can neither confirm nor clear "
                    "the hit.")
    else:
        said.append(f"The customer's name does not agree with the hit's name {hf.names[0]}, but it is not a "
                    f"verified name, so it cannot clear the hit.")
    if p_company:
        why = "the countries cannot be compared" if not (cc and hc) else "nothing else confirms it"
    elif not hf.dobs or not dob:
        why = "the date of birth cannot be compared with it"
    else:
        why = f"the date of birth {dob} neither agrees with nor contradicts the hit's {_hit_dob_text(hf)}"
    said.append(f"Nothing in the customer's records contradicts the hit, and {why}, so the hit can be "
                f"neither cleared nor confirmed.")
    return Verdict(REVIEW, "INSUFFICIENT_DATA", shared_src or (recs + dob_src + sr_src),
                   " ".join(x for x in said if x))


def combine(verdicts: list[tuple[Person, Verdict]]) -> tuple[Verdict, list[str]]:
    """Principle 3: several people fit -> same decision for all, or REVIEW / AMBIGUOUS_CUSTOMER_RECORD."""
    if len(verdicts) == 1:
        person, v = verdicts[0]
        return v, list(person.record_ids)
    evidence = list(dict.fromkeys(e for _, v in verdicts for e in v.evidence))
    decisions = {v.decision for _, v in verdicts}
    if len(decisions) == 1:
        first = verdicts[0][1]
        also = list(dict.fromkeys(c for _, v in verdicts for c in [v.reason] + v.also if c != first.reason))
        return Verdict(first.decision, first.reason, evidence, first.explanation, also=also), ["AMBIGUOUS"]
    per = "; ".join(f"{', '.join(p.record_ids)}: {v.decision}" for p, v in verdicts)
    return Verdict(REVIEW, "AMBIGUOUS_CUSTOMER_RECORD", evidence,
                   f"{len(verdicts)} different people fit the alert and they lead to different decisions "
                   f"({per}), so the hit can be neither cleared nor confirmed."), ["AMBIGUOUS"]
