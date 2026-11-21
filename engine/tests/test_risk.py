"""Risk score behaviour on real dev-set cases. Run: python -m unittest discover tests"""
import unittest

from screening.dates import PDate
from screening.decide import hit_facts
from screening.resolve import Resolver
from screening.risk import WEIGHTS, assess, combine
from screening.store import Store


class Risk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.s = Store()
        cls.r = Resolver(cls.s, None)
        cls.alerts = {a["alert_id"]: a for a in cls.s.alerts}

    def risk(self, hid):
        h = self.s.hits[hid]
        a = self.alerts[h["alert_id"]]
        res = self.r.resolve(a)
        hf = hit_facts(h, self.s, None)
        return combine([assess(p, h, hf, PDate.from_iso(a["screened_at"])) for p in res.people])

    def test_confirmed_match_is_high(self):
        # H-0181BD: name, DOB and Brazil agree (practice label SAME_ENTITY). Its DOB comes from a web
        # search result, which is weighted down, so p_same is high but below 0.9.
        r = self.risk("H-0181BD")
        self.assertGreater(r.p_same, 0.8)
        self.assertEqual(r.band, "high")

    def test_impossible_match_is_low(self):
        # H-13E1CF: customer born 2007, hit reported on in 2020 (practice label TEMPORAL_IMPOSSIBILITY)
        self.assertEqual(self.risk("H-13E1CF").band, "low")

    def test_dob_contradiction_is_low(self):
        # H-4AA437: verified DOB 1995 vs hit born 1986/1987 (practice label DOB_MISMATCH)
        self.assertLess(self.risk("H-4AA437").p_same, 0.25)

    def test_identity_inconsistency_is_flagged(self):
        # H-866A26: record 'Tyler Harris' matches the hit; the KYC document says 'Amanda Harris'
        r = self.risk("H-866A26")
        self.assertIn("identity_inconsistency", r.flags)
        self.assertGreater(r.p_same, 0.5)

    def test_near_identical_dates(self):
        from screening.dates import BirthSpec
        from screening.risk import _near_identical
        hit = lambda s: BirthSpec.exact(PDate.from_iso(s), "dobs")
        kind = lambda c, h: (_near_identical(PDate.from_iso(c), hit(h)) or (None,))[0]
        self.assertEqual(kind("1988-05-15", "1988-05-17"), "dob_day_close")          # H-68C820
        self.assertEqual(kind("1988-05-15", "1988-05-51".replace("51", "15")), None)  # identical: not a near miss
        self.assertEqual(kind("1988-05-12", "1988-05-21"), "dob_day_close")          # day digits swapped
        self.assertEqual(kind("1976-01-08", "1976-01-28"), "dob_only_day")
        self.assertEqual(kind("1962-06-10", "1962-10-06"), "dob_day_month_swapped")  # dd/mm vs mm/dd
        self.assertEqual(kind("1962-06-10", "1962-09-10"), "dob_only_month")         # H-4A2E8B
        self.assertEqual(kind("1985-03-04", "1958-03-04"), "dob_year_close")         # year digits swapped
        self.assertEqual(kind("1985-03-04", "1986-03-04"), "dob_year_close")
        self.assertEqual(kind("1965-03-04", "1990-03-04"), "dob_only_year")
        self.assertIsNone(kind("1965-03-28", "1962-09-10"))                          # several parts differ

    def test_near_identical_dob_raises_risk(self):
        # H-68C820: 1988-05-15 vs 1988-05-17. The SOP clears it (DOB_MISMATCH); the risk score does not.
        r = self.risk("H-68C820")
        self.assertIn("dob_near_identical", r.flags)
        self.assertEqual(r.band, "high")

    def test_location_is_a_weak_signal(self):
        # strong name + DOB agreement outweighs a country difference, by construction
        self.assertGreater(WEIGHTS["name_agrees"] + WEIGHTS["dob_agrees"] + WEIGHTS["country_differs"] + WEIGHTS["prior"], 0.5)


if __name__ == "__main__":
    unittest.main()
