import unittest

from app.venue_matcher import deterministic_matches, narrow_venues


class VenueMatcherTest(unittest.TestCase):
    def test_narrow_venues_prefers_name_match(self):
        venues = [
            {"id": 1, "name": "OCBC Arena", "address": "Stadium Drive"},
            {"id": 2, "name": "Clementi Sports Hall", "address": "518 Clementi Avenue 3"},
        ]

        narrowed = narrow_venues("clementi hall", venues, limit=1)

        self.assertEqual(narrowed[0]["id"], 2)

    def test_deterministic_matches_returns_confirmation_ready_records(self):
        venues = [
            {"id": 2, "name": "Clementi Sports Hall", "address": "518 Clementi Avenue 3"},
        ]

        matches = deterministic_matches("clementi", venues)

        self.assertEqual(matches[0]["id"], 2)
        self.assertIn("confidence", matches[0])
        self.assertIn("reason", matches[0])


if __name__ == "__main__":
    unittest.main()
