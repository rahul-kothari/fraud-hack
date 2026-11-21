"""Policy examples as tests. Run: python -m unittest discover tests   (or pytest, if installed)."""
import unittest

from screening.dates import BirthSpec, PDate, dob_agrees, dob_contradicts, max_age_at
from screening.extract import _ages, _caps_name, search_query
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


if __name__ == "__main__":
    unittest.main()
