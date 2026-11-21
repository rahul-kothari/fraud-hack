"""Arabic script (Arabic, Persian, Urdu, Pashto) -> romanization lattice.

Arabic writes consonants and long vowels only. Between two letters we insert
an optional short-vowel slot; long-vowel letters (alif, waw, ya) carry their
own alternatives (waw/ya double as the consonants w/y). Harakat, when
present, replace the guessed vowel. The article al- is modelled with its
common spellings (al, el, ul, a, e, u or dropped) and sun-letter assimilation
(Abd-ur-Rahman, Abd-ul-Rahman, Abdel Rahman, Abdurrahman ...).
"""
from __future__ import annotations

from ..lattice import Lattice

V = ("", "a", "e", "i", "o", "u")  # optional short vowel

CONS: dict[str, tuple[str, ...]] = {
    "ب": ("b",), "ت": ("t",), "ث": ("th", "s", "t"), "ج": ("j", "g", "dj", "dzh", "zh"),
    "ح": ("h", ""), "خ": ("kh", "h", "x", "ch"), "د": ("d",), "ذ": ("dh", "z", "d", "th"),
    "ر": ("r",), "ز": ("z",), "س": ("s",), "ش": ("sh", "ch", "sch", "s"), "ص": ("s",),
    "ض": ("d", "dh", "z"), "ط": ("t",), "ظ": ("z", "dh", "th"), "ع": ("", "a", "e"),
    "غ": ("gh", "g", "r"), "ف": ("f", "ph"), "ق": ("q", "k", "g"), "ك": ("k", "c", "q"),
    "ل": ("l",), "م": ("m",), "ن": ("n",), "ه": ("h", ""), "ء": ("",),
    # Persian / Urdu / Pashto
    "پ": ("p",), "چ": ("ch", "c"), "ژ": ("zh", "j", "z"), "گ": ("g",), "ک": ("k", "c", "q"),
    "ٹ": ("t",), "ڈ": ("d",), "ڑ": ("r", "d"), "ں": ("n", ""), "ھ": ("h", ""), "ہ": ("h", ""),
    "ڤ": ("v",), "ڨ": ("g",), "ڭ": ("ng", "g"),
}
LONG: dict[str, tuple[str, ...]] = {
    "ا": ("a", "aa", "e", "o"),
    "آ": ("a", "aa"),
    "أ": ("a", "e", "o", "u", "i", ""),
    "إ": ("i", "e", "a"),
    "ٱ": ("a", "e", "u", ""),
    "و": ("w", "u", "o", "oo", "ou", "v", "aw", "ow", "au"),
    "ؤ": ("u", "o", "w", ""),
    "ي": ("y", "i", "ee", "e", "ie", "ei", "ai", "ay", "ey", "j"),
    "ی": ("y", "i", "ee", "e", "ie", "ei", "ai", "ay", "ey", "j"),
    "ى": ("a", "i", "y", "e"),
    "ئ": ("", "y", "i", "e", "a"),
    "ے": ("e", "ay", "ai", "y"),
    "ۓ": ("e", "ay", "ai"),
    "ة": ("a", "ah", "at", "e", "eh", "et"),
    "ۃ": ("a", "ah", "at"),
}
HARAKAT: dict[str, tuple[str, ...]] = {
    "َ": ("a", "e"),        # fatha
    "ِ": ("i", "e"),        # kasra
    "ُ": ("u", "o"),        # damma
    "ً": ("an", "a", ""),   # fathatan
    "ٍ": ("in", "i", ""),   # kasratan
    "ٌ": ("un", "u", ""),   # dammatan
    "ٰ": ("a", "aa"),       # superscript alef
    "ْ": ("",),             # sukun
}
SHADDA = "ّ"
IGNORE = set("ـٕٓٔ‌‍‎‏")  # tatweel, madda/hamza marks, ZWNJ...
SUN = set("تثدذرزسشصضطظلن")
ARTICLE = ("al", "el", "ul", "il", "a", "e", "u", "")
# first elements of compound names written solid with the article: Abd-al-X, Abu-l-X, Nur-ad-Din ...
COMPOUND_PREFIXES = {
    "عبد", "ابو", "بو", "سيف", "نور", "شمس", "عز", "نصر", "جمال", "صلاح", "سعد", "فضل", "زين",
    "ضياء", "شرف", "عماد", "بهاء", "علاء", "كمال", "نجم", "تاج", "ولي", "ذو", "بدر", "حسام", "فخر",
    "قمر", "محي", "معين", "شهاب", "ركن", "سراج", "عين",
}


def _double(alts: tuple[str, ...]) -> tuple[str, ...]:
    """A consonant may be written doubled in Latin (Hussein, Mohammed)."""
    out = list(alts)
    for a in alts:
        if len(a) == 1 and a.isalpha():
            out.append(a + a)
    return tuple(out)


def word_lattices(word: str) -> list[Lattice]:
    chars = [c for c in word if c not in IGNORE]
    if not chars:
        return []
    slots: list[tuple[str, ...]] = []
    i = 0
    # Definite article: initial ال (or after a prefix handled by caller)
    if len(chars) > 2 and chars[0] in "اٱ" and chars[1] == "ل":
        nxt = chars[2]
        if nxt == "ل" and len(chars) > 3:  # الله / اللہ
            slots += [("al", "el", "ul", "a", "u", "")]
            i = 2
        elif nxt in SUN:
            slots += [ARTICLE + ("ar", "ad", "as", "at", "an", "az", "ash", "ur", "ud", "us", "un", "uz")]
            i = 2
        else:
            slots += [ARTICLE]
            i = 2
    prev_was_letter = False
    last_cons_alts: tuple[str, ...] | None = None
    while i < len(chars):
        c = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        # mid-word article as in عبدالرحمن (abd + al + rahman), اسدالله (asad + ullah)
        if c in "اٱ" and nxt == "ل" and i > 0 and i + 2 < len(chars) and slots:
            prefix = "".join(chars[:i]).replace("أ", "ا").replace("إ", "ا")
            rest = "".join(chars[i:])
            if prefix in COMPOUND_PREFIXES or rest in ("الله", "اللہ", "اللة"):
                after = chars[i + 2]
                if after in SUN and after != "ل":
                    slots.append(ARTICLE + ("ur", "ar", "ud", "us", "un", "uz", "ush", "ul"))
                else:
                    slots.append(ARTICLE)
                i += 2
                prev_was_letter = True
                last_cons_alts = None
                continue
        if c in HARAKAT:
            if slots and slots[-1] == V:
                slots.pop()
            slots.append(HARAKAT[c])
            i += 1
            continue
        if c == SHADDA:
            if last_cons_alts:
                slots.append(tuple(a[-1:] for a in last_cons_alts) + ("",))
            i += 1
            continue
        if c in CONS or c in LONG:
            if prev_was_letter and not (slots and slots[-1] in HARAKAT.values()):
                slots.append(V)
            if c in CONS:
                alts = _double(CONS[c])
                last_cons_alts = CONS[c]
            else:
                alts = LONG[c]
                if c in "وي" + "ی":
                    alts = alts + ("ww",) if c == "و" else alts + ("yy", "iy")
                last_cons_alts = None
            if c == "ا" and i == 0:  # word-initial bare alif carries any vowel (Ibrahim, Usama)
                alts = ("a", "i", "e", "u", "o")
            # word-final ه after a vowel letter is usually 'ah' / 'a' / silent
            if c in "هہ" and i == len(chars) - 1:
                alts = ("h", "", "a", "ah", "e", "eh")
            slots.append(alts)
            prev_was_letter = True
            i += 1
            continue
        # anything else (digits, unknown letters) breaks nothing; skip
        i += 1
    if not slots:
        return []
    return [Lattice(slots, source=word, script="Arabic", display=DISPLAY.get(_lookup_key(word)))]


def _lookup_key(word: str) -> str:
    w = "".join(c for c in word if c not in IGNORE and c not in HARAKAT and c != SHADDA)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ٱ", "ا"), ("ى", "ي"), ("ی", "ي"), ("ک", "ك"),
                 ("ہ", "ه"), ("ۃ", "ة"), ("ے", "ي")):
        w = w.replace(a, b)
    return w


# Conventional spellings of common name words, used for display only (matching
# always uses the full lattice). Keys are normalised with _lookup_key.
DISPLAY = {_k: _v for _k, _v in []}
_PAIRS = """
محمد muhammad|احمد ahmad|محمود mahmoud|مصطفى mustafa|علي ali|عمر umar|عثمان usman|حسين hussein
حسن hassan|ابراهيم ibrahim|يوسف yusuf|يونس yunus|موسى musa|عيسى isa|يحيى yahya|زكريا zakariya
عبد abd|عبدالله abdullah|عبدالرحمن abdulrahman|عبدالرحمان abdulrahman|الرحمن rahman|رحمن rahman
عبدالعزيز abdulaziz|عبدالقادر abdulkadir|عبدالكريم abdulkarim|عبدالسلام abdulsalam|عبدالحميد abdulhamid
عبدالمجيد abdulmajid|عبدالناصر abdulnasser|عبدالباسط abdulbasit|عبدالواحد abdulwahid|عبداللطيف abdullatif
خالد khalid|سعد saad|سعيد said|سيد sayyid|ياسين yasin|ياسر yasir|سليمان sulaiman|سلمان salman|اسامة usama
حمزة hamza|طه taha|طارق tariq|فيصل faisal|فهد fahd|ناصر nasser|نصر nasr|منصور mansour|جمال jamal
كمال kamal|رشيد rashid|راشد rashid|حامد hamid|حميد hamid|مجيد majid|ماجد majid|سالم salim|سليم salim
صالح salih|فاطمة fatima|عائشة aisha|خديجة khadija|زينب zainab|مريم maryam|امينة amina|نور nur|نورا nora
بن bin|ابن ibn|بنت bint|ابو abu|ام umm|ال al|الله allah|الدين aldin|دين din|شيخ sheikh
ندیم nadeem|نديم nadeem|غني ghani|خان khan|اسد asad|اسدالله asadullah|شاه shah|حبيب habib|كسبة kasbah
غبرة ghabra|امين amin|انيس anis|رحماني rahmani|فريد farid|عزيز aziz|قادر qadir|كريم karim|رحيم rahim
شريف sharif|جعفر jafar|بكر bakr|ابوبكر abubakr|زبير zubair|بلال bilal|انور anwar|اكبر akbar|اصغر asghar
اقبال iqbal|ارشد arshad|اشرف ashraf|اعظم azam|افضل afzal|اسلم aslam|اكرم akram|اسماعيل ismail|اسحاق ishaq
ادريس idris|الياس ilyas|نوح nuh|هارون harun|داود dawud|سلطان sultan|ملك malik|قاسم qasim|هاشم hashim
مهدي mahdi|حيدر haidar|عباس abbas|جواد jawad|رضا reza|حسيني husseini|بادام badam|بهرام bahram
مفلح mufleh|الدلابيح aldalabih|رائد raed|الحجازي alhijazi|رشاد rashad|ياسين yasin|بوركليان beurklian
اني anni|انا anna|الحسن alhassan|عبدالعزيز abdulaziz|بلوش baluch|زماني zamani
"""
for _line in _PAIRS.strip().splitlines():
    for _pair in _line.split("|"):
        _ar, _lat = _pair.split()
        DISPLAY[_lookup_key(_ar)] = _lat
