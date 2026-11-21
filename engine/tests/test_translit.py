import random

import pytest

from screening.translit import Lattice, NameMatcher, hit_names, levenshtein, parse_name, romanize

M = NameMatcher()


def agree(a, b, et=None):
    return M.compare(a, b, entity_type=et).agree


# ------------------------------------------------------------------ lattice
def test_lattice_distance_matches_brute_force():
    rng = random.Random(0)
    for _ in range(400):
        slots = [tuple(rng.choice(["", "a", "b", "ab", "ba", "c"]) for _ in range(rng.randint(1, 3)))
                 for _ in range(rng.randint(1, 4))]
        lat = Lattice(slots)
        text = "".join(rng.choice("abc") for _ in range(rng.randint(0, 6)))
        brute = min(levenshtein(text, s) for s in lat.spellings(10_000)) if lat.slots else len(text)
        assert lat.distance(text) == brute


def test_vowel_free_distance():
    lat = Lattice([("m",), ("a",), ("h",), ("a",), ("m",), ("m",), ("a",), ("d",)])
    assert lat.distance("mohammed") == 2
    assert lat.distance("mohammed", vowel_free=True) == 0


# ---------------------------------------------------------------- normalise
def test_normalise_case_accents_punctuation_brackets():
    assert parse_name("Jérôme KERVIEL (AKA)").texts() == ["jerome", "kerviel"]
    assert parse_name("O'Brien, Seán").texts() == ["obrien", "sean"]
    assert parse_name("Ranković, Aleksandar").texts() == ["rankovic", "aleksandar"]
    assert parse_name("Müller Groß").texts() == ["muller", "gross"]


def test_placeholders_initials_and_duplicates():
    assert parse_name("N/A FAREEDUDDIN").texts() == ["fareeduddin"]
    assert parse_name("RAHMAN TEST TEST").texts() == ["rahman"]
    assert parse_name("Xxx 0000 Unknown Ali").texts() == ["ali"]
    assert parse_name("Carl E. Andersen").texts() == ["carl", "andersen"]
    assert parse_name("ABDULKADIR ABDULKADIR").texts() == ["abdulkadir"]


def test_company_legal_forms():
    assert parse_name("TD Bank, N.A. GmbH", "Company").texts() == ["td", "bank"]
    assert parse_name("Danske Bank A/S", "Company").texts() == ["danske", "bank"]
    assert parse_name("Pescanova S.A.", "Company").texts() == ["pescanova"]
    # legal forms are only dropped for companies
    assert parse_name("Ltd Smith", "Individual").texts() == ["ltd", "smith"]


# ------------------------------------------------------------- principle 8
def test_variants_from_name_variants_json():
    assert agree("Muhammad Nadeem", "Mohammed Nadeem")
    assert agree("Yusuf Ibrahim", "Joseph Ebrahim")


def test_joined_or_apart():
    assert agree("Abdulsalam Bello", "Abdul Salam Bello")
    assert agree("Abdul Rahman Yasin", "Yasin Abdulrahman")


def test_edit_budget():
    assert agree("Gianpiero Fiorani", "Giampiero Fiorani")          # 1 edit, 9 letters
    assert agree("Elvira Velasco Mooillo", "Elvira Velasco Morillo")
    assert not agree("Wyn Jones", "Wynn Jones")                      # 3-letter parts must be identical
    m = M.compare("Wyn Llewellyn", "Wynn Llewellyn")
    assert [x.customer for x in m.matches] == ["llewellyn"]
    # swap of two letters is two edits: too many for a 4-6 letter part
    assert M.part_match(parse_name("Omra").parts[0], parse_name("Omar").parts[0]) is None


def test_agreement_rule():
    assert not agree("Markus Gerhard Mueller", "Mark Mueller")         # practice label H-D9BBCC
    assert not agree("Jonathan Reyes Whitfield", "John Whitfield")     # H-CF173B
    assert not agree("TASLIMA RAHIM ISLAM", "Islam, Md Saidul")        # H-EDBB79
    assert agree("Carl E. ANDERSEN", "Carl E")                         # every part of the shorter name
    assert agree("Md Amin", "Amin, Md Al")


def test_customer_with_one_real_part_is_undecidable():
    assert M.compare("N/A FAREEDUDDIN", "Fareeduddin, Mohammed").agree is None
    # but a hit's single-part alias can still agree
    assert M.compare("Abdul Rahman Mani", "Mani").agree is True


# ----------------------------------------------------------- transliteration
@pytest.mark.parametrize("latin,native", [
    ("Armen Mkrtchyan", "Армен Мкртчян"),
    ("Oleksii Volodymyrovych Hryhoriev", "Олексій Володимирович Григор'єв"),
    ("Aleksandar Ranković", "Александар Ранковић"),
    ("Markus Gerhard Mueller", "Маркус Герхард Мюллер"),
    ("Davit Vahan Sargsyan", "Դավիթ Վահանի Սարգսյան"),
    ("Muhammad Nadeem", "محمد ندیم"),
    ("Ibrahim Ahmad Kasbah", "ابراهيم كسبة"),
    ("Abdul Rahman Yasin", "عبد الرحمن ياسين"),
    ("Asad Ullah Khan", "اسد اللہ خان"),
    ("Mohammed Ghabra", "מחמד ע'ברה"),
    ("Abdul Rahman Yasin", "עבד אלרחמן יאסין"),
    ("Badshah Mia", "বাদশা মিয়া"),
    ("Md Saidul Islam", "মোঃ সাইদুল ইসলাম"),
    ("Omar Hossain", "ওমর হোসেন"),
    ("Harwinder Singh", "हरविंदर सिंह"),
    ("Rajesh Kumar", "राजेश कुमार"),
    ("Mohammed Fareeduddin", "మహమ్మద ఫరీదుద్దీన"),
    ("Park Ji Min", "박지민"),
    ("Kim Jong Sik", "金正植"),
    ("Mei Lin", "梅林"),
    ("Abdul Rahman Yasin", "ヤシン・アブドゥル・ラフマン・サイド"),
    ("Omar Ali Hussain", "オマル・アリ・フセイン"),
])
def test_transliterated_alias_agrees(latin, native):
    r = M.compare(latin, native)
    assert r.agree, r.explain()


@pytest.mark.parametrize("latin,native", [
    ("Park Bello", "박지민"),
    ("Mohamed Mokaddem", "أنيس رحماني"),
    ("Mahmoud Muhammad Mufleh", "محمد بركات حسن أحمد"),
    ("Le Thuan Thi", "اسد اللہ خان"),
    ("Mohammed Al Ghabra", "মোঃ আল আমিন"),
])
def test_unrelated_names_do_not_agree(latin, native):
    r = M.compare(latin, native)
    assert not r.agree, r.explain()


def test_literal_mode_ignores_native_script():
    lit = NameMatcher(transliterate=False)
    assert lit.parse("Армен Мкртчян").parts == []


def test_romanize_display():
    assert romanize("Армен Мкртчян") == "armen mkrtchyan"
    assert romanize("محمد ندیم") == "muhammad nadeem"
    assert romanize("박지민") == "park jimin"


# ------------------------------------------------------------------ assess
def test_redundant_alias_defers_to_latin():
    # the Arabic alias is a rendering of "Gareth Wynn" and cannot tell Wyn from Wynn
    a = M.assess(["Garuth Wyn Llewellyn"], ["Gareth Wynn", "غاريث وين (None, Arabic)"])
    assert a.redundant_aliases and a.status == "disagree" and a.can_clear


def test_independent_alias_blocks_clearing():
    a = M.assess(["Anis Rahmani"], ["Mokaddem, Mohamed", "أنيس رحماني"])
    assert a.status == "agree_via_transliteration"
    assert not a.can_clear and not a.supports_confirm
    assert NameMatcher().assess(["Anis Rahmani"], ["Mokaddem, Mohamed", "أنيس رحماني"],
                                confirm_on_transliteration=True).supports_confirm


def test_literal_agreement_confirms():
    a = M.assess(["Elvira Velasco Morillo"], ["Elvira Velasco Morillo"])
    assert a.status == "agree" and a.supports_confirm and not a.can_clear


# ---------------------------------------------------------------- hit names
def test_hit_names_parsing():
    hit = {"name": "Lin Mei", "aliases": "梅林 (None, CJK Unified Ideographs); 2734 2651 (CCC); Mei Lin (AKA)"}
    names = hit_names(hit)
    assert [n.text for n in names] == ["Lin Mei", "梅林 (None, CJK Unified Ideographs)", "Mei Lin (AKA)"]
    assert names[1].kind == "None, CJK Unified Ideographs"
    hit2 = {"name": "X Y", "aliases": [{"name": "Z W", "type": "AKA"}, "Q R (Nickname)"]}
    assert [n.kind for n in hit_names(hit2)] == ["name", "AKA", "Nickname"]
