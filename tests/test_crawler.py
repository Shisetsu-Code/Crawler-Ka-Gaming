from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

from crawl_ka_gaming import (
    _demo_user_id,
    build_targets,
    validate_targets,
)


class KaGamingCrawlerTests(unittest.TestCase):
    def payload(self):
        return {
            "status": "ok",
            "statusCode": 0,
            "numGames": 2,
            "gameLaunchURL": "https://gamesdemo.kaga88.com",
            "games": [
                {"gameId": "Zulu", "gameName": "Zulu"},
                {"gameId": "Alpha", "gameName": "Alpha"},
            ],
        }

    def test_build_targets_is_sorted_and_complete(self):
        targets = build_targets(self.payload(), language="es")
        self.assertEqual(len(targets), 2)
        self.assertIn("g=Alpha", targets[0])
        self.assertIn("g=Zulu", targets[1])

        query = parse_qs(urlsplit(targets[0]).query)
        self.assertEqual(query["loc"], ["es"])
        self.assertEqual(query["p"], ["demo"])
        self.assertEqual(query["cr"], ["USD"])

    def test_demo_user_id_is_deterministic(self):
        self.assertEqual(_demo_user_id("Alpha"), _demo_user_id("Alpha"))
        self.assertNotEqual(_demo_user_id("Alpha"), _demo_user_id("Beta"))

    def test_duplicate_game_id_fails(self):
        payload = self.payload()
        payload["games"][1]["gameId"] = "Zulu"
        with self.assertRaisesRegex(RuntimeError, "duplicado"):
            build_targets(payload, language="es")

    def test_catalog_count_mismatch_fails(self):
        payload = self.payload()
        payload["numGames"] = 3
        with self.assertRaisesRegex(RuntimeError, "incompleto"):
            build_targets(payload, language="es")

    def test_target_validation_rejects_duplicates(self):
        targets = build_targets(self.payload(), language="es")
        with self.assertRaisesRegex(RuntimeError, "duplicados"):
            validate_targets([targets[0], targets[0]])


if __name__ == "__main__":
    unittest.main()
