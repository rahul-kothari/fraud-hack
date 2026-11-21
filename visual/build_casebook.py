#!/usr/bin/env python3
"""Build data.js for casebook.html from the Track 1 dev-set workbook.

    python build_casebook.py --xlsx "../Screening Dev Set - browse.xlsx" \
        --out data.js --cache .cache [--check]

For every alert it:
  1. finds the customer: follows the alert's link, or searches all customers
     on the screened name, date of birth, country and city (SOP principle 2);
  2. merges records the SOP calls one person: same phone and same full date
     of birth, or the same document number on approved checks (principle 3);
  3. collects that person's accounts, onboarding, KYC checks and notes, and
     picks the most recent approved identity check (principle 4);
  4. reads each hit: birth dates from the dobs field, an age in the first
     paragraph of the profile notes, or qualifying web search results; dated
     reports; countries; date of death (principle 5);
  5. compares customer and hit fact by fact (principles 6 to 8).

Everything it marks is a mechanical hint from the SOP's rules. It never makes
a decision. --check tests the plumbing against the practice labels.
"""
import argparse
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache

import pandas as pd

SHEETS = {
    'alerts': 'Alerts', 'hits': 'Hits', 'customers': 'Customers', 'accounts': 'Accounts',
    'onboarding': 'Onboarding', 'kyc': 'KYC checks', 'notes': 'Notes',
    'search': 'Search results', 'labels': 'Practice labels',
}


# ---------------------------------------------------------------- loading

def load(xlsx, cache):
    names = list(SHEETS) + ['policy']
    if cache and all(os.path.exists(os.path.join(cache, f'{k}.pkl')) for k in names):
        return {k: pd.read_pickle(os.path.join(cache, f'{k}.pkl')) for k in names}
    print('Reading the workbook. This takes a minute or two...', file=sys.stderr)
    frames = pd.read_excel(xlsx, sheet_name=list(SHEETS.values()), dtype=str)
    out = {k: frames[v] for k, v in SHEETS.items()}
    out['policy'] = pd.read_excel(xlsx, sheet_name='Policy', header=None, dtype=str)
    if cache:
        os.makedirs(cache, exist_ok=True)
        for k, df in out.items():
            df.to_pickle(os.path.join(cache, f'{k}.pkl'))
    return out


def clean(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    v = str(v).strip()
    if not v or v.lower() == 'nan':
        return None
    if re.fullmatch(r'\d+\.0', v):
        v = v[:-2]
    return v


def rows(df):
    out = []
    for r in df.to_dict('records'):
        d = {k: clean(v) for k, v in r.items()}
        out.append({k: v for k, v in d.items() if v is not None})
    return out


def parse_policy(df):
    """Return (SOP text lines, name variant groups, company legal forms)."""
    lines = [clean(x) for x in df[0].tolist()]
    lines = [x for x in lines if x]
    variants, legal, in_groups = [], set(), False
    for line in lines:
        if line.lower().startswith('company legal forms'):
            legal = {p.strip().lower() for p in line.split(':', 1)[1].split(',') if p.strip()}
            in_groups = False
        elif line.startswith('Groups of given-name forms'):
            in_groups = True
        elif in_groups and re.fullmatch(r"[a-z' -]+(, [a-z' -]+)+", line):
            variants.append([p.strip() for p in line.split(',')])
    if not variants or not legal:
        print('WARNING: could not read name variants or legal forms from the Policy tab', file=sys.stderr)
    return lines, variants, legal


# ---------------------------------------------------------------- text

def fold(s):
    """Lowercase without accents."""
    s = unicodedata.normalize('NFKD', str(s))
    return ''.join(c for c in s if not unicodedata.combining(c)).lower()


def key(s):
    return re.sub(r'[^a-z0-9]+', ' ', fold(s)).strip()


def digits(s):
    return re.sub(r'\D', '', s or '')


# ---------------------------------------------------------------- countries

CODES = {
    'AR': 'Argentina', 'AT': 'Austria', 'AU': 'Australia', 'BD': 'Bangladesh', 'BE': 'Belgium',
    'BR': 'Brazil', 'CA': 'Canada', 'CH': 'Switzerland', 'CI': "Côte d'Ivoire", 'CN': 'China',
    'DE': 'Germany', 'DK': 'Denmark', 'ES': 'Spain', 'FI': 'Finland', 'FR': 'France',
    'GB': 'United Kingdom', 'UK': 'United Kingdom', 'GH': 'Ghana', 'ID': 'Indonesia',
    'IE': 'Ireland', 'IN': 'India', 'IT': 'Italy', 'JP': 'Japan', 'KE': 'Kenya', 'MX': 'Mexico',
    'NG': 'Nigeria', 'NL': 'Netherlands', 'NO': 'Norway', 'PE': 'Peru', 'PK': 'Pakistan',
    'PL': 'Poland', 'PT': 'Portugal', 'RO': 'Romania', 'RS': 'Serbia', 'RU': 'Russia',
    'SE': 'Sweden', 'SG': 'Singapore', 'US': 'United States', 'ZA': 'South Africa',
    'AE': 'United Arab Emirates',
}
DEMONYMS = {
    'american': 'United States', 'argentine': 'Argentina', 'argentinian': 'Argentina',
    'australian': 'Australia', 'austrian': 'Austria', 'bangladeshi': 'Bangladesh',
    'belgian': 'Belgium', 'brazilian': 'Brazil', 'british': 'United Kingdom', 'canadian': 'Canada',
    'chinese': 'China', 'danish': 'Denmark', 'dutch': 'Netherlands', 'finnish': 'Finland',
    'french': 'France', 'german': 'Germany', 'ghanaian': 'Ghana', 'indian': 'India',
    'indonesian': 'Indonesia', 'irish': 'Ireland', 'italian': 'Italy', 'kenyan': 'Kenya',
    'mexican': 'Mexico', 'nigerian': 'Nigeria', 'norwegian': 'Norway', 'pakistani': 'Pakistan',
    'peruvian': 'Peru', 'polish': 'Poland', 'portuguese': 'Portugal', 'romanian': 'Romania',
    'russian': 'Russia', 'serbian': 'Serbia', 'singaporean': 'Singapore',
    'south african': 'South Africa', 'spanish': 'Spain', 'swedish': 'Sweden', 'swiss': 'Switzerland',
}
ALIASES = {
    'usa': 'United States', 'u s a': 'United States', 'united states of america': 'United States',
    'great britain': 'United Kingdom', 'cote d ivoire': "Côte d'Ivoire",
    'ivory coast': "Côte d'Ivoire", 'czechia': 'Czech Republic', 'russian federation': 'Russia',
}
NOT_COUNTRY = {'international', 'europe', 'unknown', 'n a', 'na', 'none'}
CANON = {}           # key -> display name, filled by register_country
_COUNTRY_RX = None   # built by build_country_rx


def register_country(name):
    if name:
        CANON.setdefault(key(name), name)


for _v in list(CODES.values()) + list(DEMONYMS.values()) + list(ALIASES.values()):
    register_country(_v)


def canon_country(v):
    """Map a code, demonym or name to one display name. None if not a country."""
    v = clean(v)
    if not v:
        return None
    v = re.sub(r'\[[^\]]*\]', '', v).strip().strip(',').strip()
    if not v:
        return None
    if len(v) == 2 and v.upper() in CODES:
        return CODES[v.upper()]
    k = key(v)
    if not k or k in NOT_COUNTRY:
        return None
    if k in DEMONYMS:
        return DEMONYMS[k]
    if k in ALIASES:
        return ALIASES[k]
    return CANON.get(k, v)


def build_country_rx():
    """Regex that finds country names and demonyms inside running text."""
    global _COUNTRY_RX
    words = set(CANON) | set(DEMONYMS) | set(ALIASES)
    words = sorted((w for w in words if len(w) > 3), key=len, reverse=True)
    _COUNTRY_RX = re.compile(r'(?<![a-z])(?<!new )(' + '|'.join(re.escape(w) for w in words) + r')(?![a-z])')


def countries_in_text(text):
    found = []
    for m in _COUNTRY_RX.finditer(key(text)):
        c = canon_country(m.group(1))
        if c and c not in found:
            found.append(c)
    return found


# ---------------------------------------------------------------- dates

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
          'September', 'October', 'November', 'December']
MONTH_NUM = {m.lower(): i for i, m in enumerate(MONTHS, 1)}
MONTH_NUM.update({m[:3].lower(): i for i, m in enumerate(MONTHS, 1)})
MONTH_RX = r'(?:' + '|'.join(MONTHS) + r'|' + '|'.join(m[:3] for m in MONTHS) + r')'
DATE_IN_TEXT = re.compile(
    r'\b(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4}|' + MONTH_RX + r'\.? \d{1,2},? \d{4}|\d{1,2} '
    + MONTH_RX + r'\.?,? \d{4})\b')


def _ok(y, m, d):
    if m is not None and not 1 <= m <= 12:
        return None
    if d is not None and not 1 <= d <= 31:
        return None
    return (y, m, d)


def parse_date(s):
    """Return (year, month, day) with None for parts the text does not give."""
    s = clean(s)
    if not s:
        return None
    m = re.fullmatch(r'(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?', s)
    if m:
        return _ok(int(m[1]), int(m[2]) if m[2] else None, int(m[3]) if m[3] else None)
    m = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', s)          # the data uses day/month/year
    if m:
        return _ok(int(m[3]), int(m[2]), int(m[1]))
    m = re.fullmatch(r'([A-Za-z]+)\.? (\d{1,2}),? (\d{4})', s)
    if m and m[1].lower() in MONTH_NUM:
        return _ok(int(m[3]), MONTH_NUM[m[1].lower()], int(m[2]))
    m = re.fullmatch(r'(\d{1,2}) ([A-Za-z]+)\.?,? (\d{4})', s)
    if m and m[2].lower() in MONTH_NUM:
        return _ok(int(m[3]), MONTH_NUM[m[2].lower()], int(m[1]))
    m = re.fullmatch(r'([A-Za-z]+) (\d{4})', s)
    if m and m[1].lower() in MONTH_NUM:
        return _ok(int(m[2]), MONTH_NUM[m[1].lower()], None)
    return None


def fmt(t):
    if not t:
        return None
    y, m, d = t
    return f'{y:04d}' + (f'-{m:02d}' if m else '') + (f'-{d:02d}' if m and d else '')


def full(t):
    return t if t and all(t) else None


def same_where_both_give(a, b):
    """SOP principle 2: equal in every part both give."""
    if not a or not b:
        return None
    return all(x == y for x, y in zip(a, b) if x is not None and y is not None)


def date_before(a, b):
    """True when date a is surely before date b, comparing the parts both give."""
    for x, y in zip(a, b):
        if x is None or y is None:
            return False
        if x != y:
            return x < y
    return False


# ---------------------------------------------------------------- ages

AGE_RX = [
    re.compile(r'\b(\d{1,3})[- ]years?[- ]old\b'),
    re.compile(r'\baged (\d{1,3})\b'),
    re.compile(r'\bat (?:the )?age (?:of )?(\d{1,3})\b'),
    re.compile(r'\bwho was (\d{1,3})\b'),
    re.compile(r'\bwas (\d{1,3})(?=\s*[.,;]|\s*$)'),
    re.compile(r'(?<=[^\W\d_]), (\d{1,3}),'),
    re.compile(r'(?<![\d,])\b(\d{1,3}), (?=[A-Z])'),
]
YEAR_RX = re.compile(r'\b(1[89]\d\d|20\d\d)\b')


def age_at(text):
    """Find 'aged N ... in YEAR'. Returns (age, year, [birth years]) or None."""
    for rx in AGE_RX:
        m = rx.search(text)
        if m:
            age = int(m.group(1))
            y = YEAR_RX.search(text)
            if y and 0 < age < 120:
                year = int(y.group(1))
                return age, year, [year - age - 1, year - age]
    return None


# ---------------------------------------------------------------- names (SOP principle 8)

PLACEHOLDERS = {'na', 'test', 'unknown', 'xxx', 'none', 'null', 'nil', 'tbd', 'xx', 'unk', 'nn'}
VARIANT_GROUPS = defaultdict(set)   # part -> group ids
LEGAL_FORMS = set()


def name_parts(name, company=False):
    s = re.sub(r'\([^)]*\)|\[[^\]]*\]|\{[^}]*\}', ' ', name or '')
    s = fold(s)
    s = re.sub(r"['’`.]", '', s)
    s = re.sub(r'[^\w\s]|_', ' ', s)
    out = []
    for t in s.split():
        if len(t) < 2 or any(c.isdigit() for c in t) or t in PLACEHOLDERS:
            continue
        if company and t in LEGAL_FORMS:
            continue
        if t not in out:
            out.append(t)
    return out


@lru_cache(maxsize=None)
def lev(a, b):
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:
        return 3
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


@lru_cache(maxsize=None)
def part_match(a, b):
    """How two name parts match, or None. Rules from SOP principle 8."""
    if a == b:
        return 'same'
    if VARIANT_GROUPS.get(a, set()) & VARIANT_GROUPS.get(b, set()):
        return 'listed variant'
    n = min(len(a), len(b))
    if n < 4:
        return None
    allowed = 1 if n <= 6 else 2
    e = lev(a, b)
    if e <= allowed:
        return f'{e} edit' + ('s' if e > 1 else '')
    return None


RANK = {'same': 0, 'listed variant': 1, '1 edit': 2, '2 edits': 3}


def name_agree(a_name, b_name, a_company=False, b_company=False):
    """Compare two names. Returns dict with agree, pairs, parts."""
    A, B = name_parts(a_name, a_company), name_parts(b_name, b_company)
    res = {'a': a_name, 'b': b_name, 'a_parts': A, 'b_parts': B, 'pairs': [], 'agree': False}
    if not A or not B:
        return res
    cands = []
    for i, x in enumerate(A):
        for j, y in enumerate(B):
            h = part_match(x, y)
            if h:
                cands.append((RANK[h], (i,), (j,), x, y, h))
    for i, x in enumerate(A):                       # written together vs apart
        for j in range(len(B) - 1):
            h = part_match(x, B[j] + B[j + 1])
            if h:
                cands.append((RANK[h] + .5, (i,), (j, j + 1), x, f'{B[j]} {B[j + 1]}', 'written together/apart'))
    for j, y in enumerate(B):
        for i in range(len(A) - 1):
            h = part_match(A[i] + A[i + 1], y)
            if h:
                cands.append((RANK[h] + .5, (i, i + 1), (j,), f'{A[i]} {A[i + 1]}', y, 'written together/apart'))
    usedA, usedB = set(), set()
    for _, ia, jb, x, y, h in sorted(cands, key=lambda c: c[0]):
        if usedA & set(ia) or usedB & set(jb):
            continue
        usedA |= set(ia)
        usedB |= set(jb)
        res['pairs'].append([x, y, h])
    units = len(res['pairs'])
    res['agree'] = (units >= 2
                    or (len(A) <= len(B) and len(usedA) == len(A))
                    or (len(B) <= len(A) and len(usedB) == len(B)))
    return res


def best_name_match(a_names, b_names, a_company=False, b_company=False):
    best = None
    for a in a_names:
        for b in b_names:
            r = name_agree(a, b, a_company, b_company)
            score = (r['agree'], len(r['pairs']))
            if best is None or score > best[0]:
                best = (score, r)
    return best[1] if best else None


# ---------------------------------------------------------------- the SOP's listing phrases

LISTING = {
    'sanctions': 'a sanctioned individual', 'pep': 'a politically exposed person',
    'enforcement': 'the subject of enforcement action', 'adverse media': 'named in adverse media',
    'soe': 'a state-owned enterprise official',
}
CATEGORY_HELP = {
    'PEP': 'Politically exposed person: holds or held public office. Not an accusation.',
    'Sanctions': 'On a government sanctions list. Dealings are restricted by law.',
    'Enforcement': 'Subject of action by a regulator, court or police.',
    'Adverse Media': 'Named in negative news coverage.',
    'SOE': 'An official of a state-owned enterprise.',
    'Registration': 'On a registry the screening provider tracks.',
    'Other Segment': 'On another watchlist segment.',
}
REPORT_RX = re.compile(r'^According to (.+?); (' + '|'.join(MONTHS) + r') (\d{1,2}), (\d{4}): ')
DOC_TYPES = ['passport', 'driving licence', 'national id', 'registry extract', 'residence permit']
CAPS_STOP = {'DOB', 'ID', 'KYC'}


def caps_name(text):
    """The longest run of ALL-CAPS words in a KYC note: the verified name."""
    best, run = None, []

    def close():
        nonlocal best, run
        cand = ' '.join(run)
        if len(cand) >= 3 and (best is None or len(cand) > len(best)):
            best = cand
        run = []
    for tok in text.split():
        core = tok.strip(',.;:()')
        if any(c.isalpha() for c in core) and core.isupper() and core not in CAPS_STOP:
            run.append(core)
            if tok != core and tok[-1] in ',.;:)':
                close()
        else:
            close()
    close()
    return best


# ---------------------------------------------------------------- the builder

class Casebook:
    def __init__(self, data):
        self.policy_lines, variants, legal = parse_policy(data['policy'])
        for gid, group in enumerate(variants):
            for p in group:
                VARIANT_GROUPS[p].add(gid)
        LEGAL_FORMS.update(legal)

        self.alerts = rows(data['alerts'])
        self.hits = {h['hit_id']: h for h in rows(data['hits'])}
        self.cust = {c['record_id']: c for c in rows(data['customers'])}
        accounts = rows(data['accounts'])
        onboarding = rows(data['onboarding'])
        kyc = rows(data['kyc'])
        notes = rows(data['notes'])
        search = rows(data['search'])
        self.labels = {l['hit_id']: l for l in rows(data['labels'])}

        # countries the data uses, so text search knows them
        for c in self.cust.values():
            for f in ('nationality', 'residence_country'):
                register_country(canon_country(c.get(f)))
        for h in self.hits.values():
            for _, c in self.hit_countries(h):
                register_country(c)
        build_country_rx()

        self.acc_by_id, self.acc_by_login, self.acc_by_cust = defaultdict(list), defaultdict(list), defaultdict(list)
        for a in accounts:
            self.acc_by_id[a.get('account_id')].append(a)
            self.acc_by_login[a.get('login_handle')].append(a)
            self.acc_by_cust[a.get('customer_id')].append(a)
        self.onb_by_cust, self.app_to_cust = defaultdict(list), defaultdict(set)
        for o in onboarding:
            self.onb_by_cust[o.get('customer_id')].append(o)
            self.app_to_cust[o.get('kyc_applicant_id')].add(o.get('customer_id'))
        self.kyc_by_app, self.doc_to_cust = defaultdict(list), defaultdict(set)
        for k in kyc:
            self.kyc_by_app[k.get('applicant_id')].append(k)
            if k.get('result') == 'approved' and k.get('document_number'):
                self.doc_to_cust[k['document_number']] |= self.app_to_cust.get(k['applicant_id'], set())
        self.notes_by_email = defaultdict(list)
        for n in notes:
            self.notes_by_email[n.get('requester_email')].append(n)
        self.search_by_query = defaultdict(list)
        for s in search:
            self.search_by_query[s.get('query')].append(s)
        self.providers = sorted({k['provider'] for k in kyc if k.get('provider')}, key=len, reverse=True)

        self.cust_by_email = defaultdict(list)
        self.phone_idx = defaultdict(set)
        self.token_idx = defaultdict(set)
        for rid, c in self.cust.items():
            if c.get('email'):
                self.cust_by_email[c['email']].append(rid)
            for p in self.phones(rid):
                self.phone_idx[p].add(rid)
            company = c.get('entity_type') == 'Company'
            for f in ('full_name', 'preferred_name'):
                for t in name_parts(c.get(f), company):
                    self.token_idx[t].add(rid)
        self.dob_cache = {rid: parse_date(c.get('dob')) for rid, c in self.cust.items()}

    # -------------------------------------------------- record helpers

    def phones(self, rid):
        ps = {digits(self.cust[rid].get('phone'))} | {digits(a.get('phone')) for a in self.acc_by_cust.get(rid, [])}
        return {p for p in ps if len(p) >= 6}

    def applicants(self, rid):
        return [o['kyc_applicant_id'] for o in self.onb_by_cust.get(rid, []) if o.get('kyc_applicant_id')]

    def approved_docs(self, rid):
        return {k['document_number'] for a in self.applicants(rid) for k in self.kyc_by_app.get(a, [])
                if k.get('result') == 'approved' and k.get('document_number')}

    def raw_phone(self, rid, d):
        """The phone as written on the record or its account, for display."""
        for x in [self.cust[rid].get('phone')] + [a.get('phone') for a in self.acc_by_cust.get(rid, [])]:
            if digits(x) == d:
                return x
        return d

    def doc_check(self, rid, doc):
        """The approved KYC check of rid that carries document number doc."""
        for app in self.applicants(rid):
            for k in self.kyc_by_app.get(app, []):
                if k.get('result') == 'approved' and k.get('document_number') == doc:
                    return {'app': app, 'check': k.get('check_id'), 'type': k.get('document_type'),
                            'country': k.get('document_country')}
        return None

    def screened_fit(self, rid, a):
        """Does this record fit what was screened? SOP principle 2."""
        c = self.cust[rid]
        company = a.get('entity_type') == 'Company'
        checks = {}
        checks['type'] = 'yes' if (c.get('entity_type') or a.get('entity_type')) == a.get('entity_type') else 'no'
        nm = best_name_match([a.get('customer_name', '')],
                             [x for x in (c.get('full_name'), c.get('preferred_name')) if x], company, company)
        checks['name'] = 'yes' if nm and nm['agree'] else 'no'
        sd = parse_date(a.get('dob'))
        rd = self.dob_cache.get(rid)
        same = same_where_both_give(sd, rd)
        checks['dob'] = 'n/a' if same is None else ('yes' if same else 'no')
        sc = canon_country(a.get('country'))
        if sc:
            mine = {canon_country(c.get('residence_country')), canon_country(c.get('nationality'))}
            checks['country'] = 'yes' if sc in mine else 'no'
        else:
            checks['country'] = 'n/a'
        city = clean(a.get('city'))
        if city:
            hay = key(f"{c.get('city', '')} {c.get('address', '')}")
            checks['city'] = 'yes' if re.search(r'(?<![a-z])' + re.escape(key(city)) + r'(?![a-z])', hay) else 'no'
        else:
            checks['city'] = 'n/a'
        return {'rid': rid, 'checks': checks, 'fits': all(v != 'no' for v in checks.values())}

    def closure(self, rid):
        """All records the SOP treats as the same person as rid."""
        members, edges, queue = {rid}, [], [rid]
        while queue:
            r = queue.pop()
            dob = full(self.dob_cache.get(r))
            if dob:
                for p in self.phones(r):
                    for o in sorted(self.phone_idx[p]):
                        if o not in members and full(self.dob_cache.get(o)) == dob:
                            members.add(o)
                            queue.append(o)
                            edges.append({'a': r, 'b': o, 'why': 'same phone and same full date of birth',
                                          'phone': [self.raw_phone(r, p), self.raw_phone(o, p)]})
            for doc in sorted(self.approved_docs(r)):
                for o in sorted(self.doc_to_cust.get(doc, ())):
                    if o not in members:
                        members.add(o)
                        queue.append(o)
                        edges.append({'a': r, 'b': o, 'why': f'same document number {doc} on approved checks',
                                      'doc': doc, 'checks': [self.doc_check(r, doc), self.doc_check(o, doc)]})
        return members, edges

    def name_search(self, a):
        """Customers whose full or preferred name could agree with the screened name."""
        company = a.get('entity_type') == 'Company'
        P = name_parts(a.get('customer_name', ''), company)
        toks = set()
        for p in P:
            for t in self.token_idx:
                if part_match(p, t) or (len(t) >= 3 and t != p and (p.startswith(t) or p.endswith(t))):
                    toks.add(t)
        for i in range(len(P) - 1):
            joined = P[i] + P[i + 1]
            toks |= {t for t in self.token_idx if part_match(joined, t)}
        rids = set()
        for t in toks:
            rids |= self.token_idx[t]
        return sorted(rids)

    # -------------------------------------------------- the customer side

    def parse_kyc_note(self, n):
        t = n.get('text', '')
        created = parse_date(n.get('created_at'))
        dob, dob_raw = None, None
        for m in DATE_IN_TEXT.finditer(t):
            d = parse_date(m.group(0))
            if d and d != created:
                dob, dob_raw = d, m.group(0)
                break
        name = caps_name(t)
        provider = next((p for p in self.providers if p.lower() in t.lower()), None)
        doc = next((d for d in DOC_TYPES if d in t.lower()), None)
        cs = countries_in_text(t)
        return {'src': n['note_id'], 'kind': 'note', 'date': fmt(created), 'provider': provider,
                'name': name, 'dob': fmt(dob), 'dob_raw': dob_raw, 'doc': doc, 'doc_number': None,
                'country': cs[0] if cs else None, 'result': 'approved', 'text': t}

    def build_person(self, members, edges):
        recs = sorted(members)
        rec_set = set(recs)
        accounts, coholders = [], []
        for r in recs:
            for acc in self.acc_by_cust.get(r, []):
                accounts.append(acc)
                for other in self.acc_by_id.get(acc['account_id'], []):
                    if other['customer_id'] not in rec_set:
                        coholders.append({'account_id': acc['account_id'], 'rid': other['customer_id']})
        onboarding = [o for r in recs for o in self.onb_by_cust.get(r, [])]
        kyc = [k for o in onboarding for k in self.kyc_by_app.get(o.get('kyc_applicant_id'), [])]
        emails = sorted({self.cust[r]['email'] for r in recs if self.cust[r].get('email')})
        notes = [n for e in emails for n in self.notes_by_email.get(e, [])]

        checks = []
        for k in kyc:
            checks.append({'src': k['check_id'], 'kind': 'kyc', 'date': fmt(parse_date(k.get('checked_at'))),
                           'provider': k.get('provider'), 'name': k.get('verified_name'),
                           'dob': fmt(parse_date(k.get('verified_dob'))), 'dob_raw': k.get('verified_dob'),
                           'doc': k.get('document_type'), 'doc_number': k.get('document_number'),
                           'country': canon_country(k.get('document_country')), 'result': k.get('result')})
        for n in notes:
            if n.get('channel') == 'kyc':
                checks.append(self.parse_kyc_note(n))
        approved = [c for c in checks if c['result'] == 'approved' and c['date']]
        verified = max(approved, key=lambda c: c['date']) if approved else None

        family = []
        for r in recs:
            for p in self.phones(r):
                for o in sorted(self.phone_idx[p]):
                    if o not in rec_set and o not in {f['rid'] for f in family}:
                        family.append({'rid': o, 'a': r, 'why': 'shares a phone number, different date of birth',
                                       'phone': [self.raw_phone(r, p), self.raw_phone(o, p)]})

        countries = []

        def add(c, src):
            if c and not any(x['c'] == c and x['src'] == src for x in countries):
                countries.append({'c': c, 'src': src})
        for r in recs:
            add(canon_country(self.cust[r].get('residence_country')), f'{r} residence')
            add(canon_country(self.cust[r].get('nationality')), f'{r} nationality')
        for c in approved:
            add(c['country'], f"{c['src']} document")
        for n in notes:
            if n.get('channel') != 'kyc':
                for c in countries_in_text(n.get('text', '')):
                    add(c, f"{n['note_id']} note")

        first = self.cust[recs[0]]
        dob_src, dob = None, None
        if verified and verified.get('dob'):
            dob, dob_src = verified['dob'], verified['src']
        else:
            for r in recs:
                if self.dob_cache.get(r):
                    dob, dob_src = fmt(self.dob_cache[r]), r
                    break
        return {
            'records': recs, 'merges': edges, 'family': family, 'coholders': coholders,
            'accounts': accounts, 'onboarding': onboarding, 'kyc': kyc, 'notes': notes,
            'checks': checks, 'verified': verified['src'] if verified else None,
            'name': (verified or {}).get('name') or first.get('full_name'),
            'record_names': sorted({x for r in recs for x in (self.cust[r].get('full_name'), self.cust[r].get('preferred_name')) if x}),
            'type': first.get('entity_type'),
            'dob': dob, 'dob_src': dob_src, 'countries': countries,
        }

    # -------------------------------------------------- the hit side

    @staticmethod
    def hit_countries(h):
        out = []
        for f in ('countries', 'nationality', 'citizenship', 'addresses', 'place_of_birth'):
            for p in (h.get(f) or '').split(';'):
                p = re.sub(r'\[[^\]]*\]', '', p).strip().strip(',').strip()
                if p:
                    c = canon_country(p.split(',')[-1])
                    if c and (f, c) not in out:
                        out.append((f, c))
        return out

    def build_hit(self, h):
        cats = [c.strip() for c in (h.get('categories') or '').split(';') if c.strip()]
        category = h.get('primary_category') or (cats[0] if cats else None)
        phrase = LISTING.get((category or '').lower(), 'named on a watchlist')
        countries = [{'c': c, 'src': f} for f, c in self.hit_countries(h)]
        hit_cs = {x['c'] for x in countries}
        names = [h['name']] + [a.strip() for a in (h.get('aliases') or '').split(';') if a.strip()]

        dobs = []
        for p in (h.get('dobs') or '').split(';'):
            d = parse_date(p)
            if d:
                dobs.append({'years': [d[0]], 'm': d[1], 'd': d[2], 'label': fmt(d), 'src': 'dobs field'})

        notes = h.get('profile_notes') or ''
        first_para = re.split(r'\n\s*\n', notes.strip())[0] if notes.strip() else ''
        profile_age = None
        if first_para:
            for sentence in re.split(r'(?<=[.!?])\s+', first_para):
                a = age_at(sentence)
                if a:
                    profile_age = {'age': a[0], 'year': a[1], 'years': a[2], 'text': sentence,
                                   'label': f'{a[2][0]} or {a[2][1]}', 'src': 'profile notes'}
                    break

        reports, other_wordings = [], 0
        for line in notes.split('\n'):
            line = line.strip()
            if not line.startswith('According to'):
                continue
            m = REPORT_RX.match(line)
            if m:
                reports.append({'date': fmt((int(m[4]), MONTH_NUM[m[2].lower()], int(m[3]))),
                                'source': m[1], 'line': line[:400]})
            else:
                other_wordings += 1
        earliest = min(reports, key=lambda r: r['date']) if reports else None

        query = ' '.join(sorted(re.findall(r'[^\W_]+', fold(h['name']))))   # the search tab drops accents
        results = []
        for s in self.search_by_query.get(query, []):
            snip = s.get('snippet', '')
            in_snip = countries_in_text(snip)
            a = age_at(snip)
            phrase_ok = phrase in snip.lower()
            country_ok = [c for c in in_snip if c in hit_cs]
            results.append({**s, 'countries': in_snip, 'phrase_ok': phrase_ok, 'country_ok': country_ok,
                            'age': a[0] if a else None, 'year': a[1] if a else None,
                            'years': a[2] if a else None, 'about_hit': bool(phrase_ok and country_ok)})

        if dobs:
            dob_source, entries = 'dobs field', dobs
        elif profile_age:
            dob_source, entries = 'profile notes', [profile_age]
        else:
            entries = [{'years': r['years'], 'm': None, 'd': None, 'label': f"{r['years'][0]} or {r['years'][1]}",
                        'src': r['result_id']} for r in results if r['about_hit'] and r['years']]
            dob_source = 'search results' if entries else None
        if h.get('entity_type') == 'Company':     # SOP: for companies only dobs is an incorporation date
            entries = dobs
            dob_source = 'dobs field' if dobs else None

        return {
            'id': h['hit_id'], 'row': h, 'names': names, 'category': category,
            'category_help': CATEGORY_HELP.get(category, 'On a watchlist.'), 'phrase': phrase,
            'countries': countries, 'dobs': dobs, 'first_para': first_para, 'profile_age': profile_age,
            'reports': reports, 'earliest': earliest, 'other_wordings': other_wordings,
            'deceased': fmt(parse_date(h.get('deceased_date'))), 'query': query, 'search': results,
            'dob_source': dob_source, 'dob_entries': entries,
            'source_urls': [u.strip() for u in (h.get('source_urls') or '').split(';') if u.strip()],
        }

    # -------------------------------------------------- comparing

    @staticmethod
    def compare_dob(cust_dob, entries):
        c = parse_date(cust_dob)
        if not c or not entries:
            return {'state': 'no data', 'per': []}
        cy, cm, cd = c
        per = []
        for e in entries:
            ys, m, d = e['years'], e.get('m'), e.get('d')
            agree = (cy in ys and (m is None or cm is None or m == cm)
                     and (d is None or cd is None or m != cm or d == cd))
            contra = (cy < min(ys) - 1 or cy > max(ys) + 1
                      or (len(ys) == 1 and cy == ys[0] and m and cm and m != cm)
                      or (len(ys) == 1 and cy == ys[0] and m and cm and m == cm and d and cd and d != cd))
            per.append({'label': e['label'], 'src': e['src'],
                        'state': 'agrees' if agree else ('contradicts' if contra else 'neither')})
        states = [p['state'] for p in per]
        state = 'agrees' if 'agrees' in states else ('contradicts' if all(s == 'contradicts' for s in states) else 'neither')
        return {'state': state, 'per': per}

    def compare(self, person, hit, alert, screened_at):
        company = (person or {}).get('type', alert.get('entity_type')) == 'Company'
        out = {}
        ctype = (person or {}).get('type') or alert.get('entity_type')
        htype = hit['row'].get('entity_type')
        out['type'] = {'state': 'agrees' if ctype == htype else 'contradicts', 'cust': ctype, 'hit': htype}

        hit_company = htype == 'Company'
        if person and person['verified']:
            vname = next(c['name'] for c in person['checks'] if c['src'] == person['verified'])
            cnames, verified = [vname], True
        elif person:
            cnames, verified = person['record_names'], False
        else:
            cnames, verified = [alert.get('customer_name', '')], False
        nm = best_name_match(cnames, hit['names'], company, hit_company)
        few = (not company) and nm and len(nm['a_parts']) < 2
        if few:
            state = 'too few parts'
        elif nm and nm['agree']:
            state = 'agrees'
        else:
            state = 'contradicts' if verified else 'differs (name not verified)'
        out['name'] = {'state': state, 'verified': verified, 'match': nm}

        cdob = (person or {}).get('dob') or fmt(parse_date(alert.get('dob')))
        out['dob'] = {**self.compare_dob(cdob, hit['dob_entries']), 'cust': cdob, 'cust_src': (person or {}).get('dob_src', 'screened'),
                      'hit_source': hit['dob_source']}

        ccs = {x['c'] for x in (person or {}).get('countries', [])} or ({canon_country(alert.get('country'))} - {None})
        hcs = {x['c'] for x in hit['countries']}
        shared = sorted(ccs & hcs)
        out['country'] = {'state': 'agrees' if shared else ('contradicts' if ccs and hcs else 'no data'),
                          'shared': shared, 'cust': sorted(ccs), 'hit': sorted(hcs)}

        reasons, checked = [], False
        c = parse_date(cdob)
        if hit['earliest'] and c:
            checked = True
            r = parse_date(hit['earliest']['date'])
            if company:
                if date_before(r, c):
                    reasons.append(f"incorporated {fmt(c)}, after the earliest dated report {hit['earliest']['date']}")
            else:
                cy, cm, cd = c
                max_age = r[0] - cy
                if cm and cd:
                    max_age = r[0] - cy - ((r[1], r[2]) < (cm, cd))
                if max_age < 16:
                    reasons.append(f"aged {max(max_age, 0)} at the earliest dated report {hit['earliest']['date']}")
        if hit['deceased']:
            checked = True
            if date_before(parse_date(hit['deceased']), parse_date(screened_at)):
                reasons.append(f"profile gives a date of death {hit['deceased']}, before screening on {screened_at}")
        out['time'] = {'state': 'contradicts' if reasons else ('no conflict' if checked else 'no data'),
                       'reasons': reasons}
        return out

    # -------------------------------------------------- one alert

    def build_alert(self, a):
        links = []
        seeds = []
        # each link keeps its path (account, customer) so the page can draw the chain
        hop = lambda rows: [{'account': x.get('account_id'), 'customer': x.get('customer_id')} for x in rows]
        if a.get('account_ref'):
            rows = self.acc_by_id.get(a['account_ref'], [])
            links.append({'kind': 'account_ref', 'value': a['account_ref'], 'path': hop(rows)})
            seeds += [x['customer_id'] for x in rows]
        if a.get('login_handle'):
            rows = self.acc_by_login.get(a['login_handle'], [])
            links.append({'kind': 'login_handle', 'value': a['login_handle'], 'path': hop(rows)})
            seeds += [x['customer_id'] for x in rows]
        if a.get('email'):
            custs = self.cust_by_email.get(a['email'], [])
            links.append({'kind': 'email', 'value': a['email'], 'path': [{'account': None, 'customer': c} for c in custs]})
            seeds += custs
        seeds = [s for s in dict.fromkeys(seeds) if s in self.cust]

        res = {'links': links, 'candidates': [], 'funnel': None, 'named_rows': [], 'named_total': 0, 'note': None}
        if links:
            res['mode'] = 'linked'
            res['candidates'] = [self.screened_fit(r, a) for r in seeds]
            groups, seen = [], set()
            for r in seeds:
                if r not in seen:
                    m, e = self.closure(r)
                    seen |= m
                    groups.append((m, e))
            if len(groups) > 1:
                fitting = {c['rid'] for c in res['candidates'] if c['fits']}
                chosen = [g for g in groups if g[0] & fitting]
                if not chosen:
                    chosen = groups
                    res['note'] = 'None of the linked people fits the screened details. All are shown.'
            else:
                chosen = groups
            if not seeds:
                res['note'] = 'The link leads to no customer record.'
        else:
            res['mode'] = 'search'
            pool = [self.screened_fit(r, a) for r in self.name_search(a)]
            named = [p for p in pool if p['checks']['name'] == 'yes']
            steps = [('name agrees', named)]
            cur = named
            for k, label in (('type', 'same type'), ('dob', 'date of birth fits'),
                             ('country', 'country fits'), ('city', 'city fits')):
                if k in ('country', 'city') and all(p['checks'][k] == 'n/a' for p in cur):
                    continue
                if k == 'dob' and not parse_date(a.get('dob')):
                    continue
                cur = [p for p in cur if p['checks'][k] != 'no']
                steps.append((label, cur))
            res['funnel'] = [{'label': l, 'n': len(x)} for l, x in steps]
            res['candidates'] = cur
            # same-name records for the page's table: fits first, then fewest failed checks
            fails = lambda p: sum(v == 'no' for v in p['checks'].values())
            ranked = sorted(named, key=lambda p: (fails(p), p['rid']))
            res['named_rows'] = ranked[:max(12, len(cur))]
            res['named_total'] = len(named)
            groups, seen = [], set()
            for p in cur:
                if p['rid'] not in seen:
                    m, e = self.closure(p['rid'])
                    seen |= m
                    groups.append((m, e))
            chosen = groups
            if not chosen:
                res['note'] = 'No customer record fits the screened details.'

        people = [self.build_person(m, e) for m, e in chosen]
        hits = []
        for hid in [x.strip() for x in (a.get('hit_ids') or '').split(';') if x.strip()]:
            h = self.hits.get(hid)
            if not h:
                continue
            hb = self.build_hit(h)
            hb['compare'] = [self.compare(p, hb, a, a.get('screened_at')) for p in people] or \
                            [self.compare(None, hb, a, a.get('screened_at'))]
            hb['label'] = self.labels.get(hid)
            hits.append(hb)

        rids = set(seeds) | {c['rid'] for c in res['candidates']} | {c['rid'] for c in res['named_rows']}
        for p in people:
            rids |= set(p['records']) | {f['rid'] for f in p['family']} | {c['rid'] for c in p['coholders']}
        return {'alert': a, 'resolution': res, 'people': people, 'hits': hits,
                'records': {r: self.cust[r] for r in sorted(rids) if r in self.cust}}

    def build(self):
        cases = [self.build_alert(a) for a in self.alerts]
        index = []
        for c in cases:
            a = c['alert']
            index.append({
                'id': a['alert_id'], 'name': a.get('customer_name'), 'type': a.get('entity_type'),
                'hits': len(c['hits']), 'link': c['resolution']['mode'],
                'people': len(c['people']), 'label': any(h['label'] for h in c['hits']),
                'hit_names': [h['row']['name'] for h in c['hits']],
            })
        return {'meta': {'built': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'),
                         'policy': self.policy_lines, 'alerts': len(cases),
                         'hits': sum(len(c['hits']) for c in cases)},
                'index': index, 'cases': {c['alert']['alert_id']: c for c in cases}}


# ---------------------------------------------------------------- checking against the practice labels

def check(book):
    """Does the plumbing find what the answer key cites? No verdicts are compared."""
    ok_cust = ok_evid = total = 0
    problems = []
    for case in book['cases'].values():
        for h in case['hits']:
            lab = h['label']
            if not lab:
                continue
            total += 1
            ours = sorted({r for p in case['people'] for r in p['records']})
            want = lab.get('customer_record_ids')
            if want == 'AMBIGUOUS':
                good = len(case['people']) > 1
            elif not want or want == 'null':
                good = not case['people']
            else:
                good = set(x.strip() for x in want.split(';')) <= set(ours)
            ok_cust += good
            seen = set(ours) | {c['src'] for p in case['people'] for c in p['checks']} \
                | {n['note_id'] for p in case['people'] for n in p['notes']} \
                | {s['result_id'] for s in h['search'] if s['about_hit']}
            missing = [e.strip() for e in (lab.get('evidence') or '').split(';')
                       if e.strip() and e.strip() not in seen]
            ok_evid += not missing
            if not good or missing:
                problems.append(f"  {h['id']} ({case['alert']['alert_id']}): customer {'ok' if good else 'MISS'}"
                                f" (label {want}, ours {ours or 'none'}); evidence not surfaced: {missing or 'none'}")
    print(f'Practice labels: {total}')
    print(f'  customer records found: {ok_cust}/{total}')
    print(f'  every cited record surfaced: {ok_evid}/{total}')
    if problems:
        print('Problems:')
        print('\n'.join(problems))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--xlsx', required=True, help='the dev-set workbook')
    ap.add_argument('--out', default='data.js', help='where to write the page data')
    ap.add_argument('--cache', help='folder for a fast-reload copy of the workbook')
    ap.add_argument('--check', action='store_true', help='test the plumbing against the practice labels')
    args = ap.parse_args()

    book = Casebook(load(args.xlsx, args.cache)).build()
    # a script, not plain JSON: browsers block fetch() from file://, so this lets the page open with a double-click
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('window.CASEBOOK = ')
        json.dump(book, f, ensure_ascii=False, separators=(',', ':'))
        f.write(';\n')
    size = os.path.getsize(args.out) / 1e6
    print(f"Wrote {args.out}: {book['meta']['alerts']} alerts, {book['meta']['hits']} hits, {size:.1f} MB")
    if args.check:
        check(book)


if __name__ == '__main__':
    main()
