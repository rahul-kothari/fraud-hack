"""How the transliteration model (screening/translit) feeds the decision. Run: python -m pytest tests"""
import unittest

from screening.dates import PDate
from screening.decide import decide_one, hit_facts, native_alias_agreement
from screening.names import names_agree
from screening.resolve import Fact, Person
from screening.risk import assess
from screening.store import Store


class Names(unittest.TestCase):
    def test_equal_length_either_side_covered(self):
        # neither name is shorter, so either side fully covered counts ("Abdul Salam" is all covered)
        self.assertTrue(names_agree("Abdulsalam Bello", "Abdul Salam").agrees)

    def test_company_and_person_names_never_agree(self):
        # H-5EEC5A: Stadtwerke München GmbH (company) vs Mun Chen (person)
        s = Store()
        hf = hit_facts(s.hits["H-5EEC5A"], s, None)
        co = Person(record_ids=["CUS-T"], entity_type="Company", record_names=[Fact("Stadtwerke München GmbH", "CUS-T")],
                    verified_name=Fact("Stadtwerke München GmbH", "KYC-T"))
        v = decide_one(co, hf, PDate(2026, 11, 1))
        self.assertEqual(v.reason, "ENTITY_TYPE_MISMATCH")
        self.assertIn("NAME_MISMATCH_VERIFIED", v.also)

    def test_short_part_not_swallowed_by_a_join(self):
        # "st"+"logistics" is 2 edits from "logistics", but "st" (under 4 letters) must match exactly
        self.assertFalse(names_agree("Starling Logistics Ltd", "ST Logistics (UK) Ltd.", company=True).agrees)
        self.assertTrue(names_agree("Abdulsalam Bello", "Abdul Salam Bello").agrees)


class NativeAlias(unittest.TestCase):
    """'Mokaddem, Mohamed' (H-2F0E93) has the Arabic alias أنيس رحماني (Anis Rahmani), a different name
    with no Latin counterpart on the profile."""

    @classmethod
    def setUpClass(cls):
        cls.s = Store()
        cls.hit = cls.s.hits["H-2F0E93"]
        cls.hf = hit_facts(cls.hit, cls.s, None)

    def person(self, verified):
        return Person(record_ids=["CUS-TEST"], entity_type="Individual",
                      record_names=[Fact(verified, "CUS-TEST")], verified_name=Fact(verified, "KYC-TEST"))

    def test_native_alias_blocks_name_clearance(self):
        v = decide_one(self.person("Anis Rahmani"), self.hf, PDate(2026, 11, 1))
        self.assertNotIn("NAME_MISMATCH_VERIFIED", [v.reason] + v.also)
        self.assertEqual(v.decision, "REVIEW")
        self.assertIn("cannot clear the hit", v.explanation)

    def test_unrelated_name_still_cleared(self):
        v = decide_one(self.person("Jonathan Whitfield"), self.hf, PDate(2026, 11, 1))
        self.assertEqual(v.decision, "DIFFERENT_ENTITY")
        self.assertIn("NAME_MISMATCH_VERIFIED", [v.reason] + v.also)

    def test_native_alias_never_confirms_and_raises_risk(self):
        self.assertIsNotNone(native_alias_agreement(self.person("Anis Rahmani"), self.hf))
        r = assess(self.person("Anis Rahmani"), self.hit, self.hf, PDate(2026, 11, 1))
        self.assertIn("native_alias_match", r.flags)


if __name__ == "__main__":
    unittest.main()
