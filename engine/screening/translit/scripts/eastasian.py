"""Hangul, Japanese kana and Han characters -> romanization lattices.

* Hangul syllables are decomposed algorithmically into jamo and romanized
  with Revised Romanization and McCune-Reischauer alternatives; surnames use
  their conventional spellings (Park, Lee, Kim, Choi ...).
* Kana use Hepburn with Kunrei alternatives. Katakana transcriptions of
  foreign names add vowels after consonants (Abdul -> アブドゥル, a-bu-du-ru),
  so u/o-final syllables may drop their vowel and r may be l.
* Han characters get their Mandarin reading (from the optional ``anyascii``
  package) with Wade-Giles alternatives, Cantonese spellings of common
  surnames, and the Korean reading of hanja (optional ``hanja`` package).
  Chinese transcriptions of foreign names use syllables for lone consonants
  (卜 bu = b, 勒 le = l, 尔 er = r), which may drop their vowel.
"""
from __future__ import annotations

from ..lattice import Lattice

try:  # optional dependencies
    from anyascii import anyascii as _anyascii
except Exception:  # pragma: no cover
    _anyascii = None
try:  # pragma: no cover - optional
    import hanja as _hanja
except Exception:  # pragma: no cover
    _hanja = None

# ----------------------------------------------------------------- Hangul
_INITIALS = [("g", "k"), ("kk", "gg", "k"), ("n",), ("d", "t"), ("tt", "dd"), ("r", "l", "n"),
             ("m",), ("b", "p"), ("pp", "bb"), ("s", "sh"), ("ss", "s"), ("",), ("j", "ch"),
             ("jj", "tch"), ("ch",), ("k",), ("t",), ("p",), ("h",)]
_MEDIALS = [("a",), ("ae", "e"), ("ya",), ("yae", "ye"), ("eo", "o", "u"), ("e",), ("yeo", "yo"),
            ("ye",), ("o",), ("wa",), ("wae", "we"), ("oe", "oi", "we"), ("yo",), ("u", "oo", "woo"),
            ("wo", "weo"), ("we",), ("wi", "ui"), ("yu", "yoo"), ("eu", "u"), ("ui", "eui", "i"),
            ("i", "ee")]
_FINALS = [("",), ("k", "g"), ("k", "kk"), ("k",), ("n",), ("n",), ("n",), ("t", "d"), ("l", "r"),
           ("k", "l"), ("m", "l"), ("l", "p"), ("l",), ("l",), ("p", "l"), ("l",), ("m",), ("p", "b"),
           ("p",), ("t", "s"), ("t", "s"), ("ng",), ("t", "j"), ("t", "ch"), ("k",), ("t",), ("p",),
           ("t", "h")]
SURNAMES = {
    "김": ("kim", "gim"), "이": ("lee", "yi", "rhee", "i", "li", "rhie"), "리": ("lee", "ri", "li"),
    "박": ("park", "pak", "bak"), "최": ("choi", "choe", "chae"), "정": ("jung", "chung", "jeong", "cheong"),
    "강": ("kang", "gang"), "조": ("cho", "jo", "joe"), "윤": ("yoon", "yun"), "장": ("jang", "chang"),
    "임": ("lim", "im", "rim"), "한": ("han",), "오": ("oh", "o"), "서": ("seo", "suh", "so"),
    "신": ("shin", "sin"), "권": ("kwon", "gwon"), "황": ("hwang",), "안": ("ahn", "an"),
    "송": ("song",), "류": ("ryu", "yoo", "yu", "ryoo"), "유": ("yoo", "yu", "ryu"), "전": ("jeon", "jun", "chun", "chon"),
    "홍": ("hong",), "고": ("ko", "go"), "문": ("moon", "mun"), "양": ("yang",), "손": ("son", "sohn"),
    "배": ("bae", "pae"), "백": ("baek", "paik", "paek"), "허": ("heo", "huh", "hur"), "노": ("noh", "roh", "no"),
    "남": ("nam",), "심": ("shim", "sim"), "곽": ("kwak", "gwak"), "성": ("sung", "seong"),
    "차": ("cha",), "주": ("joo", "ju", "chu"), "우": ("woo", "u"), "구": ("koo", "gu", "ku"),
    "민": ("min",), "진": ("jin", "chin"), "지": ("ji", "chi"), "엄": ("eom", "um"), "채": ("chae", "chai"),
    "원": ("won",), "천": ("cheon", "chun"), "방": ("bang", "pang"), "공": ("kong", "gong"),
    "현": ("hyun", "hyeon"), "함": ("ham",), "변": ("byun", "byeon", "pyon"), "염": ("yeom", "yum"),
    "여": ("yeo", "yuh"), "추": ("choo", "chu"), "도": ("do", "doh"), "소": ("so",), "석": ("seok", "suk"),
    "선": ("sun", "seon"), "설": ("seol", "sul"), "마": ("ma",), "길": ("gil", "kil"), "연": ("yeon", "yun"),
    "위": ("wi", "wee"), "표": ("pyo",), "명": ("myung", "myeong"), "기": ("ki", "gi"), "반": ("ban", "pan"),
    "왕": ("wang",), "금": ("keum", "geum"), "옥": ("ok",), "육": ("yook", "yuk"), "인": ("in",),
    "맹": ("maeng",), "제": ("je",), "모": ("mo",), "탁": ("tak",), "국": ("kook", "guk"), "어": ("eo",),
    "은": ("eun",), "편": ("pyun",), "용": ("yong",), "예": ("ye",), "경": ("kyung", "gyeong"),
    "봉": ("bong",), "사": ("sa",), "부": ("boo", "bu"), "황보": ("hwangbo",), "남궁": ("namgung",),
    "제갈": ("jegal",), "선우": ("sunwoo", "seonu"), "독고": ("dokgo",),
}


def _hangul_syllable(ch: str) -> list[tuple[str, ...]]:
    code = ord(ch) - 0xAC00
    if not 0 <= code < 11172:
        return []
    ini, med, fin = code // 588, (code % 588) // 28, code % 28
    slots = [_INITIALS[ini], _MEDIALS[med]]
    if fin:
        slots.append(_FINALS[fin])
    return slots


def hangul(word: str) -> list[Lattice]:
    syl = [c for c in word if 0xAC00 <= ord(c) <= 0xD7A3]
    if not syl:
        return []
    text = "".join(syl)
    # Korean personal names are written solid: surname (1-2 syllables) + given name.
    if 2 <= len(text) <= 4:
        for sl in (2, 1):
            sur = text[:sl]
            if sur in SURNAMES and len(text) - sl >= 1:
                given: list[tuple[str, ...]] = []
                for c in text[sl:]:
                    given += _hangul_syllable(c)
                return [Lattice([SURNAMES[sur]], source=sur, script="Hangul"),
                        Lattice(given, source=text[sl:], script="Hangul")]
    slots: list[tuple[str, ...]] = []
    for c in text:
        slots += _hangul_syllable(c)
    return [Lattice(slots, source=word, script="Hangul")]


# ------------------------------------------------------------------- Kana
_KANA_BASE = {
    "ア": ("a",), "イ": ("i",), "ウ": ("u", ""), "エ": ("e",), "オ": ("o",),
    "カ": ("ka", "ca"), "キ": ("ki",), "ク": ("ku", "k", "c"), "ケ": ("ke",), "コ": ("ko", "co"),
    "ガ": ("ga",), "ギ": ("gi",), "グ": ("gu", "g"), "ゲ": ("ge",), "ゴ": ("go",),
    "サ": ("sa",), "シ": ("shi", "si", "sh"), "ス": ("su", "s"), "セ": ("se",), "ソ": ("so",),
    "ザ": ("za",), "ジ": ("ji", "zi", "j"), "ズ": ("zu", "z"), "ゼ": ("ze",), "ゾ": ("zo",),
    "タ": ("ta",), "チ": ("chi", "ti", "ch"), "ツ": ("tsu", "tu", "ts"), "テ": ("te",), "ト": ("to", "t"),
    "ダ": ("da",), "ヂ": ("ji", "di"), "ヅ": ("zu", "du"), "デ": ("de",), "ド": ("do", "d"),
    "ナ": ("na",), "ニ": ("ni",), "ヌ": ("nu", "n"), "ネ": ("ne",), "ノ": ("no",),
    "ハ": ("ha", "a"), "ヒ": ("hi",), "フ": ("fu", "hu", "f", "h"), "ヘ": ("he", "e"), "ホ": ("ho",),
    "バ": ("ba", "va"), "ビ": ("bi", "vi"), "ブ": ("bu", "b", "v"), "ベ": ("be", "ve"), "ボ": ("bo", "vo"),
    "パ": ("pa",), "ピ": ("pi",), "プ": ("pu", "p"), "ペ": ("pe",), "ポ": ("po",),
    "マ": ("ma",), "ミ": ("mi",), "ム": ("mu", "m"), "メ": ("me",), "モ": ("mo",),
    "ヤ": ("ya",), "ユ": ("yu",), "ヨ": ("yo",),
    "ラ": ("ra", "la"), "リ": ("ri", "li"), "ル": ("ru", "lu", "r", "l"), "レ": ("re", "le"), "ロ": ("ro", "lo"),
    "ワ": ("wa",), "ヰ": ("i",), "ヱ": ("e",), "ヲ": ("o", "wo"), "ン": ("n", "m"),
    "ヴ": ("vu", "v", "bu"), "ァ": ("a",), "ィ": ("i",), "ゥ": ("u",), "ェ": ("e",), "ォ": ("o",),
}
_KANA_DIGRAPHS = {
    "キャ": ("kya",), "キュ": ("kyu",), "キョ": ("kyo",), "シャ": ("sha", "sya"), "シュ": ("shu", "syu"),
    "ショ": ("sho", "syo"), "チャ": ("cha", "tya"), "チュ": ("chu",), "チョ": ("cho",), "ニャ": ("nya",),
    "ニュ": ("nyu",), "ニョ": ("nyo",), "ヒャ": ("hya",), "ヒュ": ("hyu",), "ヒョ": ("hyo",),
    "ミャ": ("mya",), "ミュ": ("myu",), "ミョ": ("myo",), "リャ": ("rya", "lya"), "リュ": ("ryu", "lyu"),
    "リョ": ("ryo", "lyo"), "ギャ": ("gya",), "ギュ": ("gyu",), "ギョ": ("gyo",), "ジャ": ("ja", "jya"),
    "ジュ": ("ju", "jyu"), "ジョ": ("jo", "jyo"), "ビャ": ("bya",), "ビュ": ("byu",), "ビョ": ("byo",),
    "ピャ": ("pya",), "ピュ": ("pyu",), "ピョ": ("pyo",), "ファ": ("fa", "ha"), "フィ": ("fi", "hi"),
    "フェ": ("fe", "he"), "フォ": ("fo", "ho"), "ティ": ("ti", "di"), "ディ": ("di", "dee"), "トゥ": ("tu", "t"),
    "ドゥ": ("du", "d"), "ウィ": ("wi", "ui"), "ウェ": ("we", "ue"), "ウォ": ("wo",), "ヴァ": ("va", "ba"),
    "ヴィ": ("vi", "bi"), "ヴェ": ("ve", "be"), "ヴォ": ("vo", "bo"), "シェ": ("she",), "ジェ": ("je",),
    "チェ": ("che",), "ツァ": ("tsa",), "イェ": ("ye",), "クァ": ("kwa", "qa"), "グァ": ("gwa",),
}
_VOWEL_OF = {"a": "a", "i": "i", "u": "u", "e": "e", "o": "o"}


def _to_katakana(s: str) -> str:
    return "".join(chr(ord(c) + 0x60) if 0x3041 <= ord(c) <= 0x3096 else c for c in s)


def kana(word: str) -> list[Lattice]:
    w = _to_katakana(word)
    slots: list[tuple[str, ...]] = []
    i = 0
    while i < len(w):
        two = w[i:i + 2]
        if two in _KANA_DIGRAPHS:
            slots.append(_KANA_DIGRAPHS[two])
            i += 2
            continue
        c = w[i]
        if c == "ー":  # long vowel: repeat previous vowel, or drop
            prev = slots[-1][0] if slots else ""
            v = prev[-1] if prev and prev[-1] in _VOWEL_OF else ""
            slots.append(("", v, "h") if v else ("",))
        elif c in "ッっ":  # geminate the next consonant
            nxt = _KANA_BASE.get(w[i + 1], ("",))[0] if i + 1 < len(w) else ""
            slots.append(("", nxt[:1]) if nxt and nxt[0] not in "aeiou" else ("",))
        elif c in _KANA_BASE:
            slots.append(_KANA_BASE[c])
        i += 1
    return [Lattice(slots, source=word, script="Kana")] if slots else []


# -------------------------------------------------------------------- Han
CANTONESE_SURNAMES = {
    "林": ("lam",), "陈": ("chan",), "陳": ("chan",), "黄": ("wong",), "黃": ("wong",), "李": ("lee", "li"),
    "张": ("cheung",), "張": ("cheung",), "梁": ("leung",), "刘": ("lau",), "劉": ("lau",), "何": ("ho",),
    "吴": ("ng",), "吳": ("ng",), "王": ("wong",), "周": ("chow", "chau"), "郑": ("cheng",), "鄭": ("cheng",),
    "谢": ("tse",), "謝": ("tse",), "郭": ("kwok",), "杨": ("yeung",), "楊": ("yeung",), "邓": ("tang",),
    "鄧": ("tang",), "许": ("hui",), "許": ("hui",), "曾": ("tsang",), "冯": ("fung",), "馮": ("fung",),
    "蔡": ("choi",), "胡": ("wu",), "梅": ("mui",), "叶": ("yip",), "葉": ("yip",), "罗": ("law",), "羅": ("law",),
}
# Korean readings of hanja common in names (used when the `hanja` package is absent)
HANJA_KOREAN = {
    "金": ("kim", "gim", "geum"), "李": ("lee", "yi", "i"), "朴": ("park", "pak"), "崔": ("choi",),
    "鄭": ("jung", "jeong", "chung"), "正": ("jeong", "jong", "chong"), "植": ("sik", "shik"),
    "日": ("il",), "成": ("seong", "sung", "song"), "恩": ("eun", "un"), "哲": ("cheol", "chol", "chul"),
    "永": ("yeong", "young", "yong"), "南": ("nam",), "姜": ("kang",), "趙": ("cho", "jo"),
    "尹": ("yoon", "yun"), "張": ("jang", "chang"), "林": ("lim", "im"), "韓": ("han",), "吳": ("oh",),
    "申": ("shin",), "權": ("kwon",), "黃": ("hwang",), "安": ("ahn",), "宋": ("song",), "洪": ("hong",),
    "玄": ("hyun",), "明": ("myung", "myeong"), "浩": ("ho",), "俊": ("jun", "joon"), "秀": ("soo", "su"),
    "英": ("young", "yeong"), "賢": ("hyun",), "敏": ("min",), "基": ("ki", "gi"), "東": ("dong",),
    "國": ("kook", "guk"), "光": ("kwang",), "炳": ("byung",), "勇": ("yong",), "龍": ("yong", "ryong"),
}
# syllables Chinese uses to transcribe a lone consonant in foreign names
_CONSONANT_SYLLABLES = {"bu", "de", "le", "er", "ke", "te", "si", "fu", "ge", "he", "mu", "pu",
                        "tu", "ku", "zi", "ci", "shi", "ri", "ji", "ye", "ne", "me", "se", "sha",
                        "bo", "lei", "luo", "mo", "fo", "po", "ka", "ta", "na", "la"}
_WADE = [("zh", ("zh", "ch", "j")), ("ch", ("ch",)), ("sh", ("sh",)), ("q", ("q", "ch")),
         ("x", ("x", "hs", "sh", "s")), ("z", ("z", "ts", "tz")), ("c", ("c", "ts")), ("r", ("r", "j"))]


def _pinyin_alts(py: str, transcription: bool = False) -> tuple[str, ...]:
    py = py.lower()
    alts = [py]
    if transcription:  # Chinese renderings of foreign names: l~r, ao~o, ou~u
        if py.startswith("l"):
            alts.append("r" + py[1:])
        if "ao" in py:
            alts.append(py.replace("ao", "o"))
        if "ou" in py:
            alts.append(py.replace("ou", "u"))
        if py.startswith("x"):
            alts.append("s" + py[1:])
    for ini, subs in _WADE:
        if py.startswith(ini):
            rest = py[len(ini):]
            alts += [s + rest for s in subs]
            break
    more = []
    for a in alts:
        if a.endswith("ong"):
            more.append(a[:-3] + "ung")
        if "ian" in a:
            more.append(a.replace("ian", "ien"))
        if a.endswith("ui"):
            more.append(a[:-2] + "uei")
        if a.startswith("yi"):
            more.append(a[1:])
        if a.startswith("wu"):
            more.append(a[1:])
        if a.endswith("e") and len(a) == 2:
            more.append(a[0] + "o")
    alts += more
    if py in _CONSONANT_SYLLABLES or (transcription and py[:1] not in "aeiouy"):
        cons = py.rstrip("aeiouy") or py
        alts.append(cons if py != "er" else "r")
        if py == "er":
            alts.append("ar")
    return tuple(dict.fromkeys(alts))


def _han_char(c: str, transcription: bool = False) -> tuple[str, ...]:
    alts: list[str] = []
    if _anyascii is not None:
        py = _anyascii(c).strip()
        if py and py.isascii() and py.isalpha():
            alts += _pinyin_alts(py, transcription)
    alts += CANTONESE_SURNAMES.get(c, ())
    if _hanja is not None:  # pragma: no cover - optional
        try:
            ko = _hanja.translate(c, "substitution")
            if ko and ko != c:
                for lat in hangul(ko):
                    alts += lat.spellings(6)
        except Exception:
            pass
    alts += HANJA_KOREAN.get(c, ())
    return tuple(dict.fromkeys(alts))


def is_han(c: str) -> bool:
    cp = ord(c)
    return 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x2FA1F


def han(word: str, personal_name: bool = True) -> list[Lattice]:
    chars = [c for c in word if is_han(c)]
    transcription = not (personal_name and 2 <= len(chars) <= 3)
    readings = [_han_char(c, transcription) for c in chars]
    if not chars or not any(readings):
        return []
    # 2-3 character personal names: surname + given name (each char its own part
    # so "Mei Lin" and "Meilin" both match via joined/apart).
    if personal_name and 2 <= len(chars) <= 3:
        return [Lattice([r], source=c, script="Han") for c, r in zip(chars, readings) if r]
    return [Lattice([r for r in readings if r], source=word, script="Han")]
