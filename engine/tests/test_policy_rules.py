"""Policy examples as tests. Run: python -m unittest discover tests   (or pytest, if installed)."""
import unittest

from screening.dates import BirthSpec, PDate, dob_agrees, dob_contradicts, max_age_at
from screening.extract import _age_at_date, _ages, _caps_name, profile_dob, search_query
from screening.names import names_agree, part_match, parts


class Names(unittest.TestCase):
    def test_normalisation(self):
        self.assertEqual(parts("Elvira Velazco Morillo (AKA)"), ("elvira", "velazco", "morillo"))
        self.assertEqual(parts("COSTA, MARCOS ROBERTO"), ("costa", "marcos", "roberto"))
        self.assertEqual(parts("John A. Smith"), ("john", "smith"))            # initials are not parts
        self.assertEqual(parts("TEST N/A Brooks"), ("brooks",))                # placeholders are not parts
        self.assertEqual(parts("Stadtwerke München GmbH", company=True), ("stadtwerke", "munchen"))

    def test_part_rules(self):
        self.assertTrue(part_match("mohammed", "muhammad"))                     # variant group
        self.assertTrue(part_match("velasco", "velazco"))                       # 7 letters: 1 edit fine
        self.assertTrue(part_match("omar", "omer"))                             # variants
        self.assertFalse(part_match("ali", "al"))                               # under 4 letters: identical only
        self.assertFalse(part_match("anna", "nana"))                            # swap = 2 edits, 4 letters allows 1
        self.assertTrue(part_match("setfanovic", "stefanovic"))                 # swap = 2 edits, 10 letters allows 2

    def test_joined_or_apart(self):
        self.assertTrue(names_agree("Abdulsalam Bello", "Abdul Salam Bello").agrees)

    def test_never_joined_on_both_sides(self):
        # H-B47A06: 'wyn' (3 letters) must equal 'wynn' exactly, so only 'gareth' matches.
        self.assertFalse(names_agree("Gareth Wyn Llewellyn", "Gareth Wynn").agrees)

    def test_agreement(self):
        self.assertTrue(names_agree("Elvira Velasco MORILLO", "Elvira Velasco Morillo").agrees)
        self.assertTrue(names_agree("Marcos Costa", "COSTA, MARCOS ROBERTO").agrees)       # 2 parts match
        self.assertFalse(names_agree("Marcos Silva", "COSTA, MARCOS ROBERTO").agrees)      # only 1 part
        self.assertTrue(names_agree("Tobi", "Oluwatobiloba Adeyemi").agrees)               # shorter name fully matched


class Dates(unittest.TestCase):
    def test_age_gives_two_years(self):
        h = BirthSpec.from_age(45, PDate(2019, 3), "x")
        self.assertEqual(h.years, {1973, 1974})

    def test_agree_and_contradict(self):
        hit = BirthSpec.exact(PDate(1968, 3, 5), "dobs")
        self.assertTrue(dob_agrees(PDate(1968), hit))                # a year alone can agree with a full date
        self.assertFalse(dob_contradicts(PDate(1969, 1, 1), hit))    # within 1 year: no contradiction
        self.assertTrue(dob_contradicts(PDate(1970), hit))           # more than 1 year out
        self.assertTrue(dob_contradicts(PDate(1968, 4, 5), hit))     # same year, month differs
        self.assertTrue(dob_contradicts(PDate(1968, 3, 6), hit))     # same year and month, day differs

    def test_age_at(self):
        self.assertEqual(max_age_at(PDate(2000, 6, 1), PDate(2016, 5, 31)), 15)
        self.assertEqual(max_age_at(PDate(2000), PDate(2016, 5, 31)), 16)  # unknown birthday: could be 16


class Extraction(unittest.TestCase):
    def test_caps_name_keeps_accents(self):
        self.assertEqual(_caps_name("identifying the holder as MILAN SETFANOVIĆ, born 09/02/1989."),
                         "MILAN SETFANOVIĆ")

    def test_ages(self):
        self.assertEqual(_ages("May 2019 news reports profiled 33 year old MARCOS"), [33])
        self.assertEqual(_ages("listed Aleksandar Raković, 29, a politically exposed person"), [29])

    def test_search_query(self):
        self.assertEqual(search_query("Jérôme Kerviel"), "jerome kerviel")
        self.assertEqual(search_query("Thomas P. Walsh"), "thomas walsh")      # initials dropped

    def test_age_at_end_of_sentence(self):
        # H-84E6E6
        self.assertEqual(_age_at_date("In June 2006, when questioning by investigators took place, "
                                      "Tomasz Drozd was 27."), (27, PDate(2006, 6)))

    def test_month_and_year_written_apart(self):
        # H-8CC0BB
        self.assertEqual(_age_at_date("A 1996 media profile from October described Oleksii Volodymyrovych "
                                      "Hryhoriev, 21, as a sanctioned individual in Russia."), (21, PDate(1996, 10)))


def _hit(first_paragraph):
    return {"profile_notes": first_paragraph + "\n\nCareer:\nSomething else."}


class ProfileDob(unittest.TestCase):
    def test_born_in_year(self):
        # H-D26A8B and nine others
        d = profile_dob(_hit("Yahaya Abubakar Abdullahi was born in 1952."), None)
        self.assertEqual((d.spec.years, d.spec.month), (frozenset({1952}), None))

    def test_born_on_date(self):
        d = profile_dob(_hit("Christian Zaum was born on 30 June 1969."), None)
        self.assertEqual((d.spec.years, d.spec.month, d.spec.day), (frozenset({1969}), 6, 30))

    def test_dob_field_read_only_when_unambiguous(self):
        # H-2C6B2E: 6/20/1955 can only be 20 June 1955
        d = profile_dob(_hit("Name: James, Richard / DIN: 08A4967 / Sex: M / DOB: 6/20/1955 / Height: 5' 10\""), None)
        self.assertEqual((d.spec.years, d.spec.month, d.spec.day), (frozenset({1955}), 6, 20))
        # 3/4/1960 could be 3 April or 4 March: not read (left to Grok)
        self.assertIsNone(profile_dob(_hit("Name: X / DOB: 3/4/1960 / Sex: M"), None))


if __name__ == "__main__":
    unittest.main()
