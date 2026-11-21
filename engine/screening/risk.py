"""Fraud-risk score: how likely a listed person is behind this customer, and how much that matters.

This sits BESIDE the SOP decision and never changes it. The SOP asks "may this hit be cleared?";
the risk score asks "if we are wrong, how likely and how bad?". A hit can be DIFFERENT_ENTITY under
the SOP and still score high: strong name and DOB agreement with only a country difference, or a
customer whose own record matches the hit while the KYC document shows someone else.

Model: start from a prior log-odds that a screening hit is the customer, add a weight for each piece
of evidence, and turn it into a probability (logistic). The risk is that probability, as a percentage:
the modelled chance that the hit is the customer. The listing's severity does not change the
percentage; it sets the bands, so a sanctions hit is "high" at a lower percentage than adverse media.
Every weight and threshold is below so it can be tuned in one place.

The percentage comes from judgement-set weights, not from fitted data (there is no fraud ground truth),
so read it as a modelled likelihood for ranking and triage, not a calibrated probability.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .dates import BirthSpec, PDate, dob_agrees, dob_contradicts, max_age_at
from .names import compare_parts, parts
from .resolve import Person

WEIGHTS = {
    "prior": -1.7,                    # ~15% of screening hits are the customer before looking at evidence
    # names
    "name_identical": 2.5,            # same set of name parts as one of the hit's names
    "name_agrees": 1.5,               # SOP agreement (every part of the shorter name, or >= 2 parts)
    "name_fuzzy_penalty": -0.5,       # ...but only through an edit-distance or variant match
    "name_disagrees": -2.0,           # no customer name agrees with any hit name
    "identity_inconsistency": 1.0,    # record name agrees, KYC document name does not: a fraud signal
    "name_native_alias": 1.5,         # agrees only with a native-script alias that has no Latin form
    # dates of birth
    "dob_exact": 3.0,                 # full date identical
    "dob_agrees": 1.8,                # year among the hit's possible years, no part differs
    "dob_near": 0.3,                  # a year off: neither agrees nor contradicts
    "dob_contradicts": -3.0,
    # near-identical full dates: one part off looks like a typo or a format mix-up, not another person
    "dob_day_month_swapped": 2.2,     # 1962-06-10 vs 1962-10-06 (dd/mm vs mm/dd)
    "dob_day_close": 2.0,             # same year and month, day 1-2 apart or its digits swapped (15 vs 51)
    "dob_only_day": 1.2,              # same year and month, day differs
    "dob_only_month": 1.2,            # same year and day, month differs
    "dob_year_close": 1.8,            # same month and day, year 1 apart, one digit apart or digits swapped
    "dob_only_year": 0.3,             # same month and day, year further apart
    "dob_from_search_factor": 0.6,    # hit DOB only from a web search result: scale its weight down
    # countries (deliberately weak: people move, and listed people bank abroad)
    "country_shared": 0.8,
    "country_differs": -0.8,
    # facts that make it impossible
    "temporal_impossible": -4.0,
    "deceased": -5.0,
    "type_mismatch": -6.0,
    # the screening system's own fuzzy score (90-100)
    "match_score_per_point": 0.06,    # (score - 95) * this
}

# Band thresholds on the percentage, by listing type: (high at or above, medium at or above).
# The worse the listing, the less likelihood it takes to raise the alarm.
BANDS = {
    "Sanctions": (30, 10),
    "Enforcement": (40, 15),
    "PEP": (50, 20),
    "SOE": (50, 20),
    "Adverse Media": (60, 25),
}
BANDS_OTHER = (70, 30)


@dataclass
class RiskResult:
    pct: int                      # 0-100: modelled chance (%) that the hit is the customer
    band: str                     # high / medium / low, from the listing type's thresholds
    p_same: float                 # the same chance as a 0-1 probability
    category: str
    drivers: list[tuple[str, float]] = field(default_factory=list)   # (plain-language reason, log-odds)
    flags: list[str] = field(default_factory=list)


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _digits_close(a: int, b: int) -> bool:
    """One digit changed, or two digits swapped: 1985/1986, 1958/1985, 15/51, 12/21."""
    x, y = str(a), str(b)
    if len(x) != len(y) or x == y:
        return False
    diff = [i for i in range(len(x)) if x[i] != y[i]]
    return len(diff) == 1 or (len(diff) == 2 and x[diff[0]] == y[diff[1]] and x[diff[1]] == y[diff[0]])


def _near_identical(c: PDate, h: BirthSpec):
    """A full hit date that differs from the customer's in exactly one way that looks like a typo or a
    day/month format mix-up. Returns (weight key, hit date, description) or None."""
    if not (c.full and h.month and h.day and len(h.years) == 1):
        return None
    y = next(iter(h.years))
    hd = PDate(y, h.month, h.day).iso()
    same_y, same_m, same_d = c.year == y, c.month == h.month, c.day == h.day
    if same_y and same_m and same_d:
        return None
    if same_y and c.month == h.day and c.day == h.month:
        return "dob_day_month_swapped", hd, "day and month swapped"
    if same_y and same_m:
        if abs(c.day - h.day) <= 2 or _digits_close(c.day, h.day):
            return "dob_day_close", hd, "only the day differs, and only slightly"
        return "dob_only_day", hd, "only the day differs"
    if same_y and same_d:
        return "dob_only_month", hd, "only the month differs"
    if same_m and same_d:
        if abs(c.year - y) <= 1 or _digits_close(c.year, y):
            return "dob_year_close", hd, "only the year differs, and only slightly"
        return "dob_only_year", hd, "only the year differs"
    return None


def _best_name(cust_names: list[str], hit_names: list[str], company: bool):
    """(agrees, identical, fuzzy-only, customer name, hit name) for the best pair."""
    best = None
    for c in cust_names:
        cp = parts(c, company)
        if not company and len(cp) < 2:
            continue
        for h in hit_names:
            hp = parts(h, company)
            r = compare_parts(cp, hp)
            identical = bool(cp) and set(cp) == set(hp)
            fuzzy = r.agrees and any(x != y for x, y in r.pairs)
            key = (r.agrees, identical, not fuzzy, r.matched)
            if best is None or key > best[0]:
                best = (key, r.agrees, identical, fuzzy, c, h)
    return None if best is None else best[1:]


def assess(person: Person, hit: dict, hf, screened_at: PDate) -> RiskResult:
    w = WEIGHTS
    d: list[tuple[str, float]] = []
    flags: list[str] = []
    company = person.is_company
    h_company = hf.entity_type == "Company"

    if company != h_company:
        d.append(("one is a person and the other a company", w["type_mismatch"]))
    if hf.deceased and hf.deceased.latest() < screened_at.earliest():
        d.append((f"the hit died on {hf.deceased}", w["deceased"]))
    dob = person.dob.value if person.dob else None
    if hf.earliest_report and dob:
        at = hf.earliest_report[0]
        if (company and dob.earliest() > at.latest()) or (not company and max_age_at(dob, at) < 16):
            d.append((f"too young / not yet incorporated at the report of {at}", w["temporal_impossible"]))

    # names: verified name and record names separately, to spot identity inconsistencies
    verified = [person.verified_name.value] if person.verified_name else []
    records = [f.value for f in person.record_names]
    if company != h_company:              # a company's name and a person's name are never compared
        verified, records = [], []
    v = _best_name(verified, hf.names, company) if verified else None
    rec = _best_name(records, hf.names, company) if records else None
    primary = v or rec
    if primary is None:
        d.append(("the customer's name has under two real parts", 0.0))
    elif primary[0]:
        agrees, identical, fuzzy, c, h = primary
        if identical:
            d.append((f"name identical to the hit's ({h})", w["name_identical"]))
        else:
            d.append((f"name agrees with the hit's ({c} ~ {h})", w["name_agrees"]))
        if fuzzy:
            d.append(("the name agreement relies on a spelling variant or edit", w["name_fuzzy_penalty"]))
    elif v and rec and rec[0]:
        d.append((f"record name {rec[3]} matches the hit, but the KYC document shows {v[3]}",
                  w["identity_inconsistency"]))
        flags.append("identity_inconsistency")
    else:
        from .decide import native_alias_agreement
        native = native_alias_agreement(person, hf)
        if native:
            d.append((f"name agrees with the hit's native-script alias {native[0]} (read as {native[1]})",
                      w["name_native_alias"]))
            flags.append("native_alias_match")
        else:
            d.append(("no customer name agrees with the hit's names", w["name_disagrees"]))

    # dates of birth
    if dob and hf.dobs:
        from_search = all(x.source.startswith("SR-") for x in hf.dobs)
        k = w["dob_from_search_factor"] if from_search else 1.0
        src = " (from a web search result)" if from_search else ""
        hit_txt = ", ".join(x.describe() for x in hf.dobs)
        near = max((n for n in (_near_identical(dob, x) for x in hf.dobs) if n), key=lambda n: w[n[0]], default=None)
        if dob.full and any(x.month and x.day and dob_agrees(dob, x) for x in hf.dobs):
            d.append((f"date of birth identical ({dob})", w["dob_exact"] * k))
        elif near:
            d.append((f"date of birth {dob} vs the hit's {near[1]}: {near[2]}{src}", w[near[0]] * k))
            flags.append("dob_near_identical")
        elif any(dob_agrees(dob, x) for x in hf.dobs):
            d.append((f"date of birth {dob} agrees with the hit's {hit_txt}{src}", w["dob_agrees"] * k))
        elif all(dob_contradicts(dob, x) for x in hf.dobs):
            d.append((f"date of birth {dob} contradicts the hit's {hit_txt}{src}", w["dob_contradicts"] * k))
        else:
            d.append((f"date of birth {dob} is a year off the hit's {hit_txt}", w["dob_near"]))

    # countries
    cc, hc = person.country_set(), hf.countries
    if cc and hc:
        shared = cc & hc
        if shared:
            d.append((f"both linked to {', '.join(sorted(shared))}", w["country_shared"]))
        else:
            d.append((f"countries differ ({', '.join(sorted(cc))} vs {', '.join(sorted(hc))})", w["country_differs"]))

    ms = hit.get("match_score")
    if ms is not None:
        d.append((f"screening match score {ms}", (ms - 95) * w["match_score_per_point"]))

    logit = w["prior"] + sum(x for _, x in d)
    p = _sigmoid(logit)
    cat = hit.get("primary_category") or (hit.get("categories") or [None])[0] or "Other"
    pct = round(100 * p)
    high, medium = BANDS.get(cat, BANDS_OTHER)
    band = "high" if pct >= high else "medium" if pct >= medium else "low"
    drivers = sorted((x for x in d if abs(x[1]) >= 0.05), key=lambda x: -abs(x[1]))
    return RiskResult(pct, band, round(p, 3), cat, drivers, flags)


def combine(results: list[RiskResult]) -> RiskResult:
    """Several people fit: report the one most likely to be the hit."""
    return max(results, key=lambda r: r.pct)
