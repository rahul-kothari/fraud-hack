# Grok-Bot-hackathon: name matching and transliteration for sanctions screening

Fin-crime hackathon, *"Is my customer sanctioned?"*. For every screening hit we
must decide whether the listed profile is the customer. Names are the first
question: does the customer's (verified) name agree with any of the hit's names
or aliases? This repo holds the **name model**. It implements the SOP's
principle 8 exactly and adds a **transliteration model**, so the many aliases
written in Arabic, Cyrillic, Bengali, Chinese, Hebrew, Japanese, Armenian,
Devanagari, Telugu, Korean and other scripts can be compared with Latin
customer names.

## Why transliteration matters here

All customer-side names (system of record, KYC checks, notes, alerts) are in
Latin script. 125 of the 819 dev hits carry aliases in other scripts. Most are
renderings of the hit's Latin name, but some are **names that appear nowhere
in Latin**: `Mokaddem, Mohamed` has the alias `أنيس رحماني` (Anis Rahmani),
and `Islam, Md Saidul` has `সাইদ তামিম` (Said Tamim). A literal reading of the
SOP cannot see these. A customer called Anis Rahmani would be cleared with
`NAME_MISMATCH_VERIFIED`, which is the worst mistake the brief names.

## How it works

```
raw name ─► strip brackets, NFKC ─► tokens ─┬─ Latin ─► fold case/accents/punctuation ─► part
                                            └─ other script ─► romanization lattice ─► part
parts ─► drop placeholders (NA, TEST, XXX, digits…), initials, company legal forms, duplicates
customer parts × hit parts ─► edges (identical | name_variants | ≤1/2 edits | joined/apart | transliteration)
                         ─► best one-to-one assignment ─► agree if ≥2 parts match or the shorter name is covered
```

**Romanization lattice** (`screening/translit/lattice.py`). A native-script word
is not turned into one guessed spelling. It becomes a sequence of slots, each
a set of Latin alternatives:

* `ي` → y | i | ee | e | ai …
* Cyrillic `х` → kh | h | ch | x
* Bengali inherent vowel → o | a | (silent)
* the Arabic article → al | el | ul | ar- | ur- | … (sun-letter assimilation)
* optional short vowels between Arabic/Hebrew consonants, since those scripts don't write them

A Latin part is scored by the **exact edit distance to the closest spelling in
the lattice**, computed by approximate NFA matching without enumerating
spellings (verified against brute force in the tests). The SOP's own edit
budget is then applied, so a transliterated alias meets the same standard as
a Latin one.

Scripts (`screening/translit/scripts/`):

| script | approach |
|---|---|
| Arabic, Persian, Urdu | consonant/long-vowel table, optional short vowels, harakat, shadda, article + sun letters, ta marbuta, display dictionary of common names |
| Hebrew | abjad table with matres lectionis and geresh (`ע'` = gh) |
| Cyrillic (ru, uk, sr, bg, mk, kk) | BGN/PCGN, ISO 9, passport and German/French spellings, digraphs (кс = x) |
| Greek, Armenian, Georgian | national systems with alternatives, digraphs |
| Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil, Telugu, Kannada, Malayalam | one offset table (the Unicode blocks are parallel), inherent vowel + schwa deletion, matras, virama, nukta; `মো.` = Md |
| Hangul | algorithmic jamo decomposition, RR + McCune-Reischauer, conventional surnames (박 = Park) |
| Japanese kana | Hepburn/Kunrei, foreign-name syllables may drop their vowel (アブドゥル = Abdul), r/l |
| Han | Mandarin + Wade-Giles, Cantonese surnames, Korean hanja readings (金正植 = Kim Jong Sik), consonant syllables in transcriptions (阿卜杜勒 = Abdul) |
| anything else | `anyascii` fallback |

**Precision guards**, chosen from the evaluation's false positives:

* A short part (under 4 letters) must be an exact reading of similar length, so `le` does not match `اللہ`.
* Variant + edits do not stack.
* Weak transliterated evidence does not stack: at most 1 edit in total across a name's transliterated matches.
* Vowel quality is free only for members of a `name_variants.json` group (Telugu `మహమ్మద` = Mohammed).

### Two readings, used asymmetrically

`NameMatcher.assess(customer_names, hit_names)` returns both the **literal**
SOP reading (Latin letters only) and the **transliterated** reading. It also
separates native aliases into:

* **redundant**: a rendering of one of the hit's own Latin names. These defer
  to the Latin form, which is more precise (Arabic writes *Wyn* and *Wynn*
  alike).
* **independent**: no Latin counterpart on the profile. These are real extra
  evidence.

| `status` | `can_clear` | `supports_confirm` | meaning for the decision |
|---|---|---|---|
| `agree` | False | True | name agrees under the SOP |
| `agree_via_transliteration` | False | False* | only an independent native alias agrees → never clear on name; REVIEW unless something else contradicts |
| `disagree` | True | False | basis for `NAME_MISMATCH_VERIFIED` (use the customer's **verified** legal name) |
| `undecidable` | False | False | individual customer with < 2 real name parts: neither confirm nor clear on name |

\* `confirm_on_transliteration=True` lets it confirm too.

## Results on the dev set

`python scripts/eval_names.py --data-dir <dev data>`

**Parallel corpus.** These are hits with both Latin names and native aliases
(111 distinct alias/name sets). Recall asks whether an alias agrees with its
own hit. False agreement uses 3,148 negative pairs: aliases vs unrelated hits.

| system | recall | false agreement |
|---|---|---|
| **this model** | **91.0%** (101/111) | **0.00%** (0/3148) |
| anyascii + SOP matching | 36.9% (41/111) | 0.00% |
| literal SOP, no transliteration | 0% | 0% |

All 10 non-agreements are correct:

* 5 are *translations*, not transliterations (全球救济基金会 = "Global Relief Foundation").
* 4 are aliases naming a different person (Anis Rahmani, Said Tamim, Raed al-Hijazi, "al-Jihadi Supermarket").
* 1 is `মো. শাহেদ` (Md. Shahed) vs "Shaheed, Mohammad". The SOP does not list *Md* as a variant of *Muhammad*, in Latin or here.

That makes **every genuine transliteration agree (101/101)**.

Recall by script: Arabic 32/35, Cyrillic 23/24, Indic 19/21, Han 8/10, Kana
8/9, Hebrew 5/6, Armenian 4/4, Hangul 2/2. Every miss is one of the cases
above.

**Practice labels.** All 29 name verdicts implied by the 50 practice labels
come out the same: 7 `NAME_MISMATCH_VERIFIED`, 22 name agreements.

## Usage

```python
from screening.translit import NameMatcher, hit_names, romanize

m = NameMatcher()
a = m.assess(
    customer_names=["Anis Rahmani"],                       # verified legal name first
    hit_names_=[n.text for n in hit_names(hit_record)],    # name + aliases
    entity_type=hit_record["entity_type"],
)
a.status, a.can_clear, a.supports_confirm, a.explain()

m.compare("Abdulsalam Bello", "Abdul Salam Bello").agree    # one pair, SOP principle 8
romanize("Олексій Володимирович Григор'єв")                 # 'oleksiy volodimirovich grigoryev'
```

Command line:

```
python -m screening.translit compare "Anis Rahmani" "Mokaddem, Mohamed" "أنيس رحماني"
python -m screening.translit compare --type Company "Danske Bank A/S" "Danske Bank" "АО Данске банк"
python -m screening.translit romanize "হারুনুর রশিদ"
```

## Data

The data is not committed. `screening/data.py` reads the data room's `dev/`
JSON Lines files (the source of truth) or CSV exports of the browse workbook.
To export the workbook, run
`python scripts/fetch_workbook.py --sheet-id <ID> --out data/dev`. The sheet
ID is not stored in the repo. `screening/translit/data/name_variants.json` holds
the SOP's variant groups and legal forms. Set `NAME_VARIANTS_PATH` to use the
data room's copy instead.

## Layout

```
screening/translit/lattice.py      romanization lattice + exact edit distance to it
screening/translit/scripts/        per-script romanizers
screening/translit/normalize.py    tokens -> SOP name parts
screening/translit/matcher.py      principle-8 agreement, assess()
screening/translit/hitnames.py     name + aliases from a hit record
screening/data.py               JSONL / CSV loader
scripts/eval_names.py           evaluation above
tests/                          pytest suite (python -m pytest)
```

Python 3.10+, no required dependencies. `pip install anyascii` is
recommended: without it, Mandarin readings fall back to the Cantonese and
Korean tables, and scripts without a table are skipped.

## Integration notes (engine)

This package was brought into the engine as `screening/translit/`, from `engine/name_check/screening/names/`.
Only the package name changed. The engine uses it in `decide.native_alias_agreement()` as a one-way safety net on
`NAME_MISMATCH_VERIFIED`: an `agree_via_transliteration` status blocks a clearance on name. It never
confirms a hit. The risk score counts such a match as evidence for the same person.

Its principle-8 matcher was compared with the engine's `names.py` on all 881 customer-name checks the
engine makes on the dev set. They agree on 878. The 3 differences, all company names:

| Customer vs hit | `names.py` | this matcher | Resolution |
|---|---|---|---|
| Stadtwerke München GmbH (company) vs Mun Chen (person) | disagree | agree | These should never be compared: a company's name never agrees with a person's. The engine now treats names across entity types as not agreeing, in the decision, this safety net and the risk score. The case did expose one real gap: with equal part counts, `names.py` now accepts either side being fully covered ("Abdul Salam" is covered by "Abdulsalam Bello"). |
| Starling Logistics Ltd vs ST Logistics (UK) Ltd. | disagree | agree | `names.py` keeps disagree: "st"+"logistics" joined is 2 edits from "logistics", which would swallow "st", a part under 4 letters that must match exactly. Suggest this matcher apply the same rule to joined matches. |
| E-Ram Consulting LLC vs alias OOO Ram-E | agree | disagree | Reading differs: `names.py` drops "OOO" as a repeated-letter placeholder; this matcher keeps it. "OOO" is the Russian legal form (LLC), which the SOP's list omits. `names.py`'s reading cannot cause a clearance, so it is kept. |

None of the three changes a decision.
