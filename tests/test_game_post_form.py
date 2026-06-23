import unittest

from app.game_post_form import (
    DEFAULT_SKILL_LEVELS,
    build_game_payload,
    parse_skill_range,
    record_answer,
    select_venue,
    set_venue_matches,
    start_game_post_session,
)


class GamePostFormTest(unittest.TestCase):
    def make_complete_session(self, pricing_answers):
        session = start_game_post_session("@organizer")
        set_venue_matches(
            session,
            "clementi",
            [{"id": 223, "name": "Clementi Sports Hall", "address": "518 Clementi Ave 3"}],
        )
        select_venue(session, "1")
        answers = [
            "25 Jun 2026",
            "7pm-9pm",
            "MB-HB",
            "6",
            "double",
            "public",
            *pricing_answers,
            "Bring shuttles",
        ]
        for answer in answers:
            record_answer(session, answer, list(DEFAULT_SKILL_LEVELS))
        return session

    def test_flat_pricing_payload_matches_create_game_contract(self):
        session = self.make_complete_session(["flat", "10"])

        payload = build_game_payload(session)

        self.assertEqual(payload["venueId"], 223)
        self.assertEqual(payload["skillLevelFromId"], 2)
        self.assertEqual(payload["skillLevelToId"], 3)
        self.assertEqual(payload["price"], 10.0)
        self.assertEqual(payload["pricing"], {
            "mode": "FLAT",
            "currency": "SGD",
            "flatPrice": 10.0,
        })
        self.assertEqual(payload["startTime"], "2026-06-25T11:00:00Z")
        self.assertEqual(payload["endTime"], "2026-06-25T13:00:00Z")

    def test_gendered_pricing_uses_lower_price_as_legacy_price(self):
        session = self.make_complete_session(["gendered", "15", "8"])

        payload = build_game_payload(session)

        self.assertEqual(payload["price"], 8.0)
        self.assertEqual(payload["pricing"]["malePrice"], 15.0)
        self.assertEqual(payload["pricing"]["femalePrice"], 8.0)

    def test_shuttlecock_pricing_uses_base_price_as_legacy_price(self):
        session = self.make_complete_session(["shuttlecock", "5", "3"])

        payload = build_game_payload(session)

        self.assertEqual(payload["price"], 5.0)
        self.assertEqual(payload["pricing"]["basePrice"], 5.0)
        self.assertEqual(payload["pricing"]["pricePerShuttle"], 3.0)

    def test_default_skill_aliases_work_with_full_api_names(self):
        api_levels = [
            {"id": 1, "name": "Beginner", "sortOrder": 1},
            {"id": 2, "name": "Mid Beginner", "sortOrder": 2},
            {"id": 3, "name": "High Beginner", "sortOrder": 3},
            {"id": 4, "name": "Low Intermediate", "sortOrder": 4},
        ]

        from_id, to_id, label = parse_skill_range("MB-HB", api_levels)

        self.assertEqual((from_id, to_id), (2, 3))
        self.assertEqual(label, "Mid Beginner-High Beginner")


if __name__ == "__main__":
    unittest.main()
