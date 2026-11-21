"""Screening alert resolver implementing the identity SOP (POLICY.md + name_variants.json)."""
import sys, csv, re, unicodedata
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")
import argparse, os
_ap = argparse.ArgumentParser(description="Label screening hits per the identity SOP.")
_ap.add_argument("--data-dir", default=os.path.join(os.path.expanduser("~"), "Downloads"),
                 help="folder holding the 'Screening Dev Set - browse - *.csv' files (default: your Downloads)")
_ap.add_argument("--prefix", default="Screening Dev Set - browse - ", help="file name prefix of the CSV exports")
_ap.add_argument("--first", type=int, default=100, help="label the hits of the first N alerts (0 = all alerts)")
_ap.add_argument("--alert-ids", default="", help="comma-separated alert IDs to label instead of --first")
_ap.add_argument("--out", default="100_labels.csv", help="output CSV")
_ap.add_argument("--check", action="store_true", help="only score the rules against the practice labels")
ARGS, _ = _ap.parse_known_args()
D = os.path.join(ARGS.data_dir, ARGS.prefix)
def load(n):
    with open(D + n + ".csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))
alerts = load("Alerts"); hits = load("Hits"); cust = load("Customers"); onb = load("Onboarding"); accts = load("Accounts")
kyc = load("KYC checks"); notes = load("Notes"); sr = load("Search results"); pl = load("Practice labels")

# ---------------- name_variants.json (from Policy tab) ----------------
VARIANT_GROUPS = """muhammad, mohammed, mohammad, mohamed, muhammed, mohamad, mohd, muhamad
ahmed, ahmad, ahmet
abdul, abdel, abd
abdullah, abdallah, abdulla
abubakar, abubakr, aboubakar, bubakar
ibrahim, ebrahim, ibraheem, brahim
yusuf, yousef, youssef, yousuf, josef, joseph, joe
umar, omar, omer
usman, uthman, othman, osman
hussein, hussain, husain, hossain, hosein
hassan, hasan
ali, aly
faruk, farouk, faruq, farooq, faroq
sulaiman, suleiman, sulayman, suleman, solomon
aminu, amin, ameen
anthony, antony, tony, antonio
robert, rob, robbie, bob, bobby, roberto
william, will, bill, billy, liam, guillermo
richard, rick, ricky, dick, ricardo
james, jim, jimmy, jamie, jaime
john, johnny, jon, jack, juan, jean, johann, johannes
michael, mike, mick, mikey, miguel, michel, michele
daniel, dan, danny, dani
david, dave, davey, davit
christopher, chris, kristopher, cristobal
matthew, matt, mateo, matteo, mathieu
andrew, andy, drew, andres, andrea, andreas
thomas, tom, tommy, tomas, tomasz
joshua, josh
nicholas, nick, nicolas, nicola, nikola, nikolai
alexander, alex, alejandro, alessandro, aleksandr, sasha
peter, pete, pedro, pietro, pierre
paul, pablo, paolo
stephen, steven, steve, stefan, esteban, stefano
joseph, joe, jose, giuseppe, jozef
francis, frank, francisco, francesco, franco, francois
charles, charlie, chuck, carlos, carlo, karl, karol
edward, ed, eddie, ted, eduardo, edoardo
henry, harry, enrique, enrico, henrik, heinrich
mark, marc, marco
markus, marcus, marcos
catherine, katherine, kathryn, kate, katie, cathy, catalina, katarzyna
elizabeth, liz, beth, betty, elisabeth, isabel
margaret, maggie, meg, peggy, margarita
jennifer, jen, jenny
rebecca, becky
susan, sue, susanna, susana
maria, mary, marie, mariya
olumide, mide
oluwaseun, seun
babatunde, tunde
oluwatobiloba, tobi
chukwuemeka, emeka
ifeanyichukwu, ifeanyi
nnamdi, namdi"""
VAR = defaultdict(set)
for line in VARIANT_GROUPS.splitlines():
    g = [x.strip() for x in line.split(",")]
    for x in g: VAR[x] |= set(g)
LEGAL = set("ab, ag, as, asa, bv, co, company, corp, corporation, gmbh, inc, kg, limited, llc, llp, lp, ltd, na, nv, oy, oyj, plc, sa, sarl, sas, se, sf, sl, spa, srl".split(", "))
PLACEHOLDER = {"na", "n/a", "test", "unknown", "xxx", "none", "null", "nil", "tbd", "nn", "xx", "x"}

def fold(s):
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).replace("ß", "ss").replace("ø", "o").replace("æ", "ae").replace("ł", "l").replace("đ", "d")
def parts(name, company=False):
    t = fold(name).lower()
    t = re.sub(r"\(.*?\)|\[.*?\]", " ", t)
    t = re.sub(r"[^a-z0-9 ]+", lambda m: "" if m.group(0) in ("'", ".") and False else " ", t)
    out = []
    for p in t.split():
        if len(p) == 1 or p in PLACEHOLDER or re.search(r"\d", p): continue
        if company and p in LEGAL: continue
        if p not in out: out.append(p)
    return out
def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
def part_eq(a, b):
    if a == b: return True
    if b in VAR.get(a, ()): return True
    n = min(len(a), len(b))
    if n < 4: return False
    return lev(a, b) <= (1 if n <= 6 else 2)
def match_count(A, B):
    """max one-to-one matches between part lists A and B, allowing a joined pair on either side to match one part.
    returns (matched parts counted on the shorter side's terms, covered_A, covered_B)"""
    best = (0, set(), set())
    # candidate units: single parts and adjacent joined pairs
    def units(P):
        u = [((i,), P[i]) for i in range(len(P))]
        u += [((i, i + 1), P[i] + P[i + 1]) for i in range(len(P) - 1)]
        return u
    UA, UB = units(A), units(B)
    edges = [(ua, ub) for ua in UA for ub in UB if part_eq(ua[1], ub[1]) and not (len(ua[0]) > 1 and len(ub[0]) > 1)]
    # greedy-with-backtracking (names are short)
    def rec(k, usedA, usedB, cnt):
        nonlocal best
        if cnt > best[0] or (cnt == best[0] and len(usedA) + len(usedB) > len(best[1]) + len(best[2])):
            best = (cnt, set(usedA), set(usedB))
        for idx in range(k, len(edges)):
            (ia, _), (ib, _) = edges[idx]
            if usedA & set(ia) or usedB & set(ib): continue
            rec(idx + 1, usedA | set(ia), usedB | set(ib), cnt + 1)
    if len(edges) <= 40: rec(0, set(), set(), 0)
    else:
        uA, uB, c = set(), set(), 0
        for (ia, _), (ib, _) in edges:
            if not (uA & set(ia) or uB & set(ib)): uA |= set(ia); uB |= set(ib); c += 1
        best = (c, uA, uB)
    return best
def names_agree(n1, n2, company=False):
    A, B = parts(n1, company), parts(n2, company)
    if not A or not B: return False
    cnt, cA, cB = match_count(A, B)
    if cnt >= 2: return True
    short, cov = (A, cA) if len(A) <= len(B) else (B, cB)
    return len(cov) == len(short)
def any_agree(names1, names2, company=False):
    return any(names_agree(a, b, company) for a in names1 for b in names2 if a and b)

# ---------------- countries ----------------
CODES = {"US": "United States", "NG": "Nigeria", "GB": "United Kingdom", "UK": "United Kingdom", "ES": "Spain", "DE": "Germany",
         "FR": "France", "BD": "Bangladesh", "IT": "Italy", "IE": "Ireland", "CA": "Canada", "NL": "Netherlands", "AU": "Australia",
         "KE": "Kenya", "PK": "Pakistan", "ZA": "South Africa", "SG": "Singapore", "SE": "Sweden", "RS": "Serbia", "BR": "Brazil",
         "AT": "Austria", "PL": "Poland", "DK": "Denmark", "PT": "Portugal", "NO": "Norway", "GH": "Ghana", "IN": "India",
         "PE": "Peru", "MX": "Mexico", "RO": "Romania", "AR": "Argentina", "CH": "Switzerland", "EC": "Ecuador", "TH": "Thailand",
         "VN": "Vietnam", "PA": "Panama", "CN": "China", "RU": "Russia", "BE": "Belgium", "FI": "Finland", "ME": "Montenegro",
         "HT": "Haiti", "CI": "Cote D'Ivoire", "DZ": "Algeria", "CZ": "Czech Republic", "ID": "Indonesia", "NZ": "New Zealand",
         "KP": "North Korea", "CO": "Colombia", "AM": "Armenia", "MA": "Morocco", "JM": "Jamaica", "IL": "Israel", "SY": "Syria",
         "LB": "Lebanon", "SI": "Slovenia", "MD": "Moldova", "HU": "Hungary", "AE": "United Arab Emirates"}
DEMONYM = {"Nigerian": "Nigeria", "American": "United States", "Spanish": "Spain", "British": "United Kingdom", "German": "Germany",
           "French": "France", "Bangladeshi": "Bangladesh", "Italian": "Italy", "Irish": "Ireland", "Polish": "Poland",
           "Indian": "India", "Canadian": "Canada", "Dutch": "Netherlands", "Australian": "Australia", "Kenyan": "Kenya",
           "South African": "South Africa", "Swedish": "Sweden", "Singaporean": "Singapore", "Austrian": "Austria",
           "Pakistani": "Pakistan", "Portuguese": "Portugal", "Serbian": "Serbia", "Danish": "Denmark", "Norwegian": "Norway",
           "Ghanaian": "Ghana", "Brazilian": "Brazil", "Mexican": "Mexico", "Indonesian": "Indonesia", "Swiss": "Switzerland",
           "Peruvian": "Peru", "Romanian": "Romania", "Finnish": "Finland", "Chinese": "China", "Russian": "Russia",
           "Ecuadorian": "Ecuador", "Thai": "Thailand", "Vietnamese": "Vietnam", "Panamanian": "Panama", "Colombian": "Colombia",
           "Argentine": "Argentina", "Argentinian": "Argentina", "Moldovan": "Moldova", "Slovenian": "Slovenia", "Hungarian": "Hungary",
           "Montenegrin": "Montenegro", "Haitian": "Haiti", "Ivorian": "Cote D'Ivoire", "Algerian": "Algeria", "Czech": "Czech Republic",
           "Armenian": "Armenia", "Moroccan": "Morocco", "Jamaican": "Jamaica", "Israeli": "Israel", "Syrian": "Syria",
           "Lebanese": "Lebanon", "Emirati": "United Arab Emirates", "Belgian": "Belgium", "North Korean": "North Korea", "New Zealander": "New Zealand"}
ALIASC = {"côte d'ivoire": "Cote D'Ivoire", "cote d'ivoire": "Cote D'Ivoire", "usa": "United States", "united states of america": "United States",
          "russian federation": "Russia", "czechia": "Czech Republic", "great britain": "United Kingdom", "england": "United Kingdom",
          "the netherlands": "Netherlands", "korea, democratic people's republic of": "North Korea", "viet nam": "Vietnam"}
NOTCOUNTRY = {"international", "europe", "unknown", "none", "n/a", ""}
def normc(x):
    x = (x or "").strip().strip(".").strip()
    if x in CODES: return CODES[x]
    if x in DEMONYM: return DEMONYM[x]
    if x.lower() in ALIASC: return ALIASC[x.lower()]
    return x
def hit_countries(h):
    out = set()
    for f in ("countries", "nationality", "citizenship", "addresses", "place_of_birth"):
        for p in h[f].split(";"):
            p = re.sub(r"\[.*?\]", "", p).strip()
            if not p: continue
            c = normc(p.split(",")[-1])
            if c.lower() not in NOTCOUNTRY and not re.search(r"\d", c): out.add(c)
    return out
KNOWN = set(CODES.values()) | set(DEMONYM.values())
for h in hits: KNOWN |= hit_countries(h)
for c in cust: KNOWN |= {normc(c["nationality"]), normc(c["residence_country"])}
for k in kyc: KNOWN.add(normc(k["document_country"]))
KNOWN = {k for k in KNOWN if k and k.lower() not in NOTCOUNTRY and len(k) > 2}
KNOWN_SORTED = sorted(KNOWN, key=len, reverse=True); DEM_SORTED = sorted(DEMONYM, key=len, reverse=True)
def countries_in_text(t):
    found = set(); tt = t
    for c in KNOWN_SORTED:
        pat = r"\b" + re.escape(c) + r"\b"
        if re.search(pat, tt, re.I): found.add(c); tt = re.sub(pat, " ", tt, flags=re.I)
    for d in DEM_SORTED:
        if re.search(r"\b" + re.escape(d) + r"\b", tt): found.add(DEMONYM[d])
    return found

# ---------------- dates ----------------
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                          "september", "october", "november", "december"])}
MRE = "(January|February|March|April|May|June|July|August|September|October|November|December)"
def parse_date(s):
    s = (s or "").strip().rstrip(".")
    if not s: return None
    for pat, f in ((r"(\d{4})-(\d{1,2})-(\d{1,2})", lambda m: (int(m[1]), int(m[2]), int(m[3]))),
                   (r"(\d{4})-(\d{1,2})", lambda m: (int(m[1]), int(m[2]), None)),
                   (r"(\d{1,2})/(\d{1,2})/(\d{4})", lambda m: (int(m[3]), int(m[2]), int(m[1]))),
                   (r"(\d{1,2})\.(\d{1,2})\.(\d{4})", lambda m: (int(m[3]), int(m[2]), int(m[1]))),
                   (MRE + r" (\d{1,2}),? (\d{4})", lambda m: (int(m[3]), MONTHS[m[1].lower()], int(m[2]))),
                   (r"(\d{1,2}) " + MRE + r",? (\d{4})", lambda m: (int(m[3]), MONTHS[m[2].lower()], int(m[1]))),
                   (MRE + r",? (\d{4})", lambda m: (int(m[2]), MONTHS[m[1].lower()], None)),
                   (r"(\d{4})", lambda m: (int(m[1]), None, None))):
        m = re.fullmatch(pat, s, re.I)
        if m: return f(m)
    return None
DATE_PAT = r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|" + MRE + r" \d{1,2},? \d{4}|\d{1,2} " + MRE + r",? \d{4}"
DATE_RE = re.compile(DATE_PAT, re.I)
def fmt(d):
    if not d: return ""
    return "-".join(["%04d" % d[0]] + (["%02d" % d[1]] if d[1] else []) + (["%02d" % d[2]] if d[1] and d[2] else []))
def date_key(d): return (d[0], d[1] or 0, d[2] or 0)

# ---------------- indexes ----------------
C = {c["record_id"]: c for c in cust}
acc_by_id = defaultdict(list); acc_by_login = defaultdict(list); acc_by_cust = defaultdict(list)
for a in accts:
    acc_by_id[a["account_id"]].append(a); acc_by_login[a["login_handle"].lower()].append(a); acc_by_cust[a["customer_id"]].append(a)
onb_c = defaultdict(list)
for o in onb: onb_c[o["customer_id"]].append(o)
kyc_a = defaultdict(list)
for k in kyc: kyc_a[k["applicant_id"]].append(k)
notes_e = defaultdict(list)
for n in notes: notes_e[n["requester_email"].lower()].append(n)
by_email = defaultdict(list); by_phone = defaultdict(list); by_part = defaultdict(set)
for c in cust:
    by_email[c["email"].lower()].append(c["record_id"])
    if c["phone"]: by_phone[c["phone"]].append(c["record_id"])
    for nm in (c["full_name"], c["preferred_name"], c["login_name"]):
        for p in parts(nm, c["entity_type"] == "Company"): by_part[p].add(c["record_id"])
for a in accts:
    if a["login_handle"] and a["customer_id"] in C:
        pass
def approved_checks(cid):
    out = []
    for o in onb_c[cid]:
        if o["account_id"] and any(a["customer_id"] == cid for a in acc_by_id.get(o["account_id"], [])) or True:
            for k in kyc_a[o["kyc_applicant_id"]]:
                if k["result"] == "approved": out.append(k)
    return out
by_doc = defaultdict(set)
for c in cust:
    for k in approved_checks(c["record_id"]):
        if k["document_number"]: by_doc[k["document_number"]].add(c["record_id"])
def full_dob(c):
    d = parse_date(c["dob"])
    return d if d and d[1] and d[2] else None
def cluster(cid):
    seen = {cid}; stack = [cid]
    while stack:
        x = stack.pop(); c = C[x]; nb = set()
        d = full_dob(c)
        if d and c["phone"]:
            nb |= {y for y in by_phone[c["phone"]] if full_dob(C[y]) == d}
        for k in approved_checks(x):
            if k["document_number"]: nb |= by_doc[k["document_number"]]
        for y in nb - seen: seen.add(y); stack.append(y)
    return sorted(seen)

# ---------------- customer facts ----------------
def parse_kyc_note(t, created):
    dob = None
    m = re.search(r"(?:DOB|born|date of birth|birth date)\D{0,20}?(" + DATE_PAT + ")", t, re.I)
    if m: dob = parse_date(m.group(1))
    if not dob:
        m = re.search(r"\((" + DATE_PAT + r")\)", t, re.I)
        if m: dob = parse_date(m.group(1))
    if not dob:
        ds = [parse_date(x.group(0)) for x in DATE_RE.finditer(t)]
        ds = [d for d in ds if d and fmt(d) != created]
        if ds: dob = ds[0]
    caps = re.findall(r"\b[A-Z][A-Z'\-]+(?: [A-Z][A-Z'\-]+)+\b", t)
    caps = [x for x in caps if not re.fullmatch(r"(DOB|ID)( [A-Z]+)?", x)]
    name = max(caps, key=len) if caps else None
    return dob, name, countries_in_text(t)

def facts(cids):
    """latest approved identity check across the person (KYC table or KYC note) + declared data"""
    f = {"checks": [], "countries": defaultdict(list), "record_names": [], "record_dobs": []}
    for cid in cids:
        c = C[cid]
        f["record_names"] += [x for x in (c["full_name"], c["preferred_name"], c["login_name"]) if x]
        d = parse_date(c["dob"])
        if d: f["record_dobs"].append((d, cid))
        for fld in ("nationality", "residence_country"):
            if c[fld]: f["countries"][normc(c[fld])].append(cid)
        for k in approved_checks(cid):
            f["checks"].append(dict(date=k["checked_at"], id=k["check_id"], name=k["verified_name"], dob=parse_date(k["verified_dob"]),
                                    country=normc(k["document_country"]) if k["document_country"] else None))
        for n in notes_e[c["email"].lower()]:
            if n["channel"] == "kyc":
                d2, nm, cs = parse_kyc_note(n["text"], n["created_at"])
                f["checks"].append(dict(date=n["created_at"], id=n["note_id"], name=nm, dob=d2, country=sorted(cs)[0] if len(cs) == 1 else None, all_c=cs))
            else:
                for x in countries_in_text(n["text"]): f["countries"][x].append(n["note_id"])
    f["latest"] = max(f["checks"], key=lambda x: x["date"]) if f["checks"] else None
    L = f["latest"]
    if L:
        cs = {L["country"]} if L.get("country") else L.get("all_c", set())
        for x in cs: f["countries"][x].append(L["id"])
    return f

# ---------------- hit facts ----------------
ROLE = {"Sanctions": "sanctioned individual", "PEP": "politically exposed person", "Enforcement": "subject of enforcement action",
        "Adverse Media": "named in adverse media", "SOE": "state-owned enterprise official"}
sr_q = defaultdict(list)
for s in sr: sr_q[s["query"]].append(s)
AGE_RE = re.compile(r"\b(?:aged |age of )(\d{1,3})\b|\b(\d{1,3})[- ]year[- ]old\b|\b(?:he|she|they) (?:was|were) (\d{1,3})\b|, (\d{1,3}),|\b(\d{1,3}) year old\b|\bat (\d{1,3})\b")
def age_at(text):
    for sent in re.split(r"(?<=[.;!?])\s+|\n", text):
        am = AGE_RE.search(sent); ym = re.search(MRE + r",? (?:\d{1,2},? )?(\d{4})", sent)
        if am and ym:
            a = int(next(g for g in am.groups() if g)); y = int(ym.group(2))
            if 0 < a < 120: return y, a, sent.strip()
    return None
def hit_facts(h):
    hf = {"countries": hit_countries(h), "dobs": [], "dob_src": None, "dob_txt": "", "sr": None}
    person = h["entity_type"] == "Individual"
    if h["dobs"].strip():
        hf["dobs"] = [d for d in (parse_date(x) for x in h["dobs"].split(";")) if d]
        if hf["dobs"]: hf["dob_src"] = "listed"; hf["dob_txt"] = ", ".join(fmt(d) for d in hf["dobs"])
    if not hf["dobs"] and person:
        first_para = re.split(r"\n\s*\n", h["profile_notes"].strip())[0] if h["profile_notes"].strip() else ""
        m = re.search(r"born (?:on |in )?(" + DATE_PAT + r"|\d{4})", first_para, re.I)
        if m and parse_date(m.group(1)):
            hf["dobs"] = [parse_date(m.group(1))]; hf["dob_src"] = "profile"; hf["dob_txt"] = fmt(hf["dobs"][0])
        else:
            r = age_at(first_para)
            if r:
                y, a, _ = r
                hf["dobs"] = [(y - a - 1, None, None), (y - a, None, None)]; hf["dob_src"] = "profile"; hf["dob_txt"] = "%d or %d" % (y - a - 1, y - a)
    if not hf["dobs"] and person and hf["countries"]:
        q = " ".join(sorted(fold(h["name"]).lower().replace(",", " ").split()))
        cat = h["primary_category"] or (h["categories"].split(";")[0].strip() if h["categories"] else "")
        role = ROLE.get(cat, "named on a watchlist")
        for s in sr_q.get(q, []):
            if role in s["snippet"] and countries_in_text(s["snippet"]) & hf["countries"]:
                r = age_at(s["snippet"])
                if r:
                    y, a, _ = r
                    hf["dobs"] = [(y - a - 1, None, None), (y - a, None, None)]; hf["dob_src"] = "search"; hf["sr"] = s["result_id"]
                    hf["dob_txt"] = "%d or %d" % (y - a - 1, y - a)
                    break
    # dated reports: "According to ...; <date>: ..."
    rep = []
    for m in re.finditer(r"According to [^;\n]*; ([^:\n]+):", h["profile_notes"]):
        d = parse_date(m.group(1).strip())
        if d: rep.append(d)
    hf["earliest_report"] = min(rep, key=date_key) if rep else None
    hf["deceased"] = parse_date(h["deceased_date"]) if h["deceased_date"] else None
    return hf

def dob_agree(cd, hd):
    if cd[0] != hd[0]: return False
    if cd[1] and hd[1] and cd[1] != hd[1]: return False
    if cd[2] and hd[2] and cd[1] == hd[1] and cd[2] != hd[2]: return False
    return True
def dob_contradicts(cd, hd):
    if abs(cd[0] - hd[0]) > 1: return True
    if cd[0] == hd[0] and cd[1] and hd[1] and (cd[1] != hd[1] or (cd[2] and hd[2] and cd[2] != hd[2])): return True
    return False
def age_on(birth, when):
    """minimum possible age at date `when` (conservative: largest birth date consistent with partial birth)"""
    by, bm, bd = birth[0], birth[1] or 12, birth[2] or 31
    wy, wm, wd = when[0], when[1] or 1, when[2] or 1
    return wy - by - (1 if (wm, wd) < (bm, bd) else 0)

# ---------------- alert -> candidate customers ----------------
def fits_screen(c, a):
    comp = a["entity_type"] == "Company"
    if c["entity_type"] != a["entity_type"]: return False
    nm = [x for x in (c["full_name"], c["preferred_name"], c["login_name"]) if x]
    nm += [x["login_handle"] for x in acc_by_cust.get(c["record_id"], [])]
    if not any(names_agree(a["customer_name"], x, comp) for x in nm): return False
    ad, cd = parse_date(a["dob"]), parse_date(c["dob"])
    if ad and cd:
        for i in range(3):
            if ad[i] is not None and cd[i] is not None and ad[i] != cd[i]: return False
    if a["country"] and normc(a["country"]) not in {normc(c["nationality"]), normc(c["residence_country"])}: return False
    if a["city"]:
        ct = fold(a["city"]).lower()
        if ct not in fold(c["city"]).lower() and ct not in fold(c["address"]).lower(): return False
    return True

def resolve(a):
    comp = a["entity_type"] == "Company"
    if a["account_ref"] or a["login_handle"]:
        rows = acc_by_id.get(a["account_ref"], []) if a["account_ref"] else acc_by_login.get(a["login_handle"].lower(), [])
        linked = sorted({r["customer_id"] for r in rows if r["customer_id"] in C})
        key = ("account_ref " + a["account_ref"]) if a["account_ref"] else ("login_handle " + a["login_handle"])
        if len(linked) > 1:
            fit = [x for x in linked if fits_screen(C[x], a)]
            path = "%s -> accounts: holders %s -> the screened details fit %s" % (key, ", ".join(linked), ", ".join(fit) or "none")
            roots = fit
        else:
            roots = linked
            path = "%s -> accounts -> customer %s" % (key, ", ".join(linked) or "none")
    elif a["email"]:
        roots = sorted(by_email.get(a["email"].lower(), []))
        path = "email %s -> customers -> %s" % (a["email"], ", ".join(roots) or "none")
    else:
        cand = set()
        for p in parts(a["customer_name"], comp): cand |= by_part.get(p, set())
        roots = sorted(x for x in cand if fits_screen(C[x], a))
        path = "name, date of birth, country and city -> customers -> %s" % (", ".join(roots) or "none")
    clusters, seen = [], set()
    for r in roots:
        if r in seen: continue
        cl = cluster(r); seen |= set(cl); clusters.append(cl)
    return clusters, path

# ---------------- decision for one person ----------------
def decide(a, h, cids):
    hf = hit_facts(h); f = facts(cids)
    cust_comp = C[cids[0]]["entity_type"] == "Company"; hit_comp = h["entity_type"] != "Individual"
    comp = cust_comp
    hit_names = [h["name"]] + [re.sub(r"\(.*?\)", "", x).strip() for x in h["aliases"].split(";") if x.strip()]
    L = f["latest"]
    codes, why, ev = [], [], set()
    if cust_comp != hit_comp:
        return "DIFFERENT_ENTITY", ["ENTITY_TYPE_MISMATCH"], {cids[0]}, "The customer is a %s but the hit is a %s." % (
            "company" if cust_comp else "person", "company" if hit_comp else "person")
    # customer DOB: verified beats declared
    if L and L["dob"]: cd, cdsrc = L["dob"], L["id"]
    elif f["record_dobs"]: cd, cdsrc = f["record_dobs"][0]
    else: cd, cdsrc = None, None
    # customer names
    if L and L["name"]: vnames, vsrc = [L["name"]], L["id"]
    else: vnames, vsrc = [], None
    names_for_agree = vnames or f["record_names"] or [a["customer_name"]]
    real_parts = max((len(parts(n, comp)) for n in names_for_agree), default=0)
    name_usable = comp or real_parts >= 2
    name_ok = any_agree(names_for_agree, hit_names, comp)
    # --- contradictions ---
    rep = hf["earliest_report"]
    if rep and cd:
        if not comp and age_on(cd, rep) < 16:
            codes.append("TEMPORAL_IMPOSSIBILITY"); ev.add(cdsrc)
            why.append("The customer was born %s (%s), so they were younger than 16 at the hit's earliest dated report (%s)." % (fmt(cd), cdsrc, fmt(rep)))
        elif comp and date_key(cd) > date_key(rep) and not (cd[1] is None and cd[0] == rep[0]):
            codes.append("TEMPORAL_IMPOSSIBILITY"); ev.add(cdsrc)
            why.append("The customer was incorporated %s (%s), after the hit's earliest dated report (%s)." % (fmt(cd), cdsrc, fmt(rep)))
    if hf["deceased"] and a["screened_at"]:
        sd = parse_date(a["screened_at"])
        if date_key(hf["deceased"]) < date_key(sd):
            codes.append("DECEASED")
            why.append("The hit's profile gives a date of death %s, before the customer was screened on %s." % (fmt(hf["deceased"]), a["screened_at"]))
    dob_ok = False
    if cd and hf["dobs"]:
        dob_ok = any(dob_agree(cd, d) for d in hf["dobs"])
        if hf["sr"]: ev.add(hf["sr"])
        if all(dob_contradicts(cd, d) for d in hf["dobs"]):
            ev.add(cdsrc); codes.append("DOB_MISMATCH")
            src = {"listed": "listed date of birth is", "profile": "profile notes put its birth year at", "search": "search results put its birth year at"}[hf["dob_src"]]
            if comp: why.append("The customer's incorporation date is %s (%s) but the hit's is %s." % (fmt(cd), cdsrc, hf["dob_txt"]))
            else: why.append("The customer's date of birth is %s (%s) but the hit's %s %s." % (fmt(cd), cdsrc, src, hf["dob_txt"]))
    ccs, hcs = set(f["countries"]), hf["countries"]
    loc_ok = bool(ccs & hcs)
    loc_mismatch = bool(ccs) and bool(hcs) and not loc_ok
    if loc_mismatch and not (name_ok and dob_ok and name_usable):
        codes.append("LOCATION_MISMATCH")
        for x in ccs: ev |= set(f["countries"][x])
        why.append("The customer is linked only to %s but the hit is linked only to %s." % (", ".join(sorted(ccs)), ", ".join(sorted(hcs))))
    if vnames and name_usable and not any_agree(vnames, hit_names, comp):
        codes.append("NAME_MISMATCH_VERIFIED"); ev.add(vsrc)
        why.append("The customer's verified name is %s (%s), which does not agree with the hit's name %s or its aliases." % (vnames[0], vsrc, h["name"]))
    if codes:
        return "DIFFERENT_ENTITY", codes, ev, " ".join(why)
    # --- confirmation ---
    loc_txt = "Both the customer and the hit are linked to %s." % ", ".join(sorted(ccs & hcs)) if loc_ok else ""
    name_txt = "The customer's name agrees with the hit's name %s." % h["name"]
    if loc_ok:
        for x in ccs & hcs: ev |= set(f["countries"][x])
    if vsrc and name_ok: ev.add(vsrc)
    if name_ok and name_usable:
        if comp and loc_ok:
            ev.add(cids[0])
            return "SAME_ENTITY", ["NAME_LOCATION_MATCH"], ev, loc_txt + " " + name_txt
        if not comp and dob_ok:
            ev.add(cdsrc)
            if loc_mismatch:
                return "REVIEW", ["INSUFFICIENT_DATA"], ev, "The customer's date of birth %s (%s) agrees with the hit's %s and the names agree, but the customer is linked only to %s and the hit only to %s, so a country difference cannot clear it." % (fmt(cd), cdsrc, hf["dob_txt"], ", ".join(sorted(ccs)), ", ".join(sorted(hcs)))
            dtxt = "The customer's date of birth %s (%s) agrees with the hit's %s." % (fmt(cd), cdsrc, hf["dob_txt"])
            return "SAME_ENTITY", (["NAME_DOB_LOCATION_MATCH"] if loc_ok else []) + ["NAME_DOB_MATCH"], ev, " ".join(x for x in (dtxt, loc_txt, name_txt) if x)
    gaps = []
    if not name_usable: gaps.append("the customer's name has fewer than two real parts")
    elif not name_ok: gaps.append("the names do not agree")
    if comp and not loc_ok: gaps.append("the country cannot be compared with it")
    if not comp and not dob_ok: gaps.append("the date of birth cannot be compared with it" if not (cd and hf["dobs"]) else "the dates of birth neither agree nor contradict")
    pre = " ".join(x for x in (loc_txt, name_txt if name_ok else "") if x)
    return "REVIEW", ["INSUFFICIENT_DATA"], ev, (pre + " " if pre else "") + "Nothing in the customer's records contradicts the hit, but %s, so the hit can be neither cleared nor confirmed." % " and ".join(gaps)

H = {h["hit_id"]: h for h in hits}; A = {a["alert_id"]: a for a in alerts}
RES_CACHE = {}
def run_hit(hid):
    h = H[hid]; a = A[h["alert_id"]]
    if a["alert_id"] not in RES_CACHE: RES_CACHE[a["alert_id"]] = resolve(a)
    clusters, path = RES_CACHE[a["alert_id"]]
    if not clusters:
        return dict(decision="REVIEW", reason_codes="INSUFFICIENT_DATA", customer_record_ids="null", evidence="",
                    reference_reason="No customer record fits the alert, so the hit can be neither cleared nor confirmed.",
                    path=path + " -> no customer found -> REVIEW ['INSUFFICIENT_DATA']")
    res = [(cl, decide(a, h, cl)) for cl in clusters]
    if len(res) == 1:
        cl, (dec, codes, ev, why) = res[0]
        ids = "; ".join(cl)
        if len(cl) > 1: path += " -> same phone and date of birth, or same document number on approved checks -> one person: " + ", ".join(cl)
    else:
        decs = {r[1][0] for r in res}
        ids = "AMBIGUOUS"
        path += " -> %d different people fit (records %s); each is decided separately" % (len(res), ", ".join(x for cl, _ in res for x in cl))
        ev = set().union(*[r[1][2] for r in res])
        if len(decs) == 1:
            dec = decs.pop(); codes = sorted({c for r in res for c in r[1][1]}); why = res[0][1][3]
        else:
            dec, codes = "REVIEW", ["AMBIGUOUS_CUSTOMER_RECORD"]
            why = "%d different people fit the alert and they lead to different decisions (%s)." % (len(res), "; ".join("%s: %s" % (cl[0], r[0]) for cl, r in res))
    ev = sorted(x for x in ev if x)
    return dict(decision=dec, reason_codes="; ".join(codes), customer_record_ids=ids, evidence="; ".join(ev), reference_reason=why,
                path=path + " -> %s %s: %s" % (dec, codes, why))


# ---------------- command line ----------------
def main():
    import time
    from collections import Counter
    t0 = time.time()
    if ARGS.check:
        ok = 0
        for p in pl:
            r = run_hit(p["hit_id"])
            good = r["decision"] == p["decision"]
            ok += good
            if not good:
                print("MISS", p["hit_id"], "got", r["decision"], "want", p["decision"])
        print("practice labels: %d/%d decisions correct" % (ok, len(pl)))
        return
    chosen = [a for a in alerts if a["alert_id"] in {x.strip() for x in ARGS.alert_ids.split(",")}] if ARGS.alert_ids \
        else (alerts[:ARGS.first] if ARGS.first else alerts)
    rows = []
    for i, a in enumerate(chosen, 1):
        for hid in [x.strip() for x in a["hit_ids"].split(";") if x.strip()]:
            r = run_hit(hid); r.update(hit_id=hid, alert_id=a["alert_id"]); rows.append(r)
        if i % 25 == 0: print("  %d/%d alerts done" % (i, len(chosen)))
    cols = ["hit_id", "alert_id", "decision", "reason_codes", "customer_record_ids", "evidence", "reference_reason", "path"]
    with open(ARGS.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({k: r[k] for k in cols})
    by_alert = defaultdict(set)
    for r in rows: by_alert[r["alert_id"]].add(r["decision"])
    print("hits  :", dict(Counter(r["decision"] for r in rows)))
    print("alerts:", dict(Counter("SAME_ENTITY" if "SAME_ENTITY" in d else "REVIEW" if "REVIEW" in d else "DIFFERENT_ENTITY" for d in by_alert.values())))
    print("wrote %d rows to %s in %.0fs" % (len(rows), ARGS.out, time.time() - t0))

if __name__ == "__main__":
    main()