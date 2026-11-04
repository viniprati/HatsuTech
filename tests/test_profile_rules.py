import unittest
from datetime import datetime, timezone, timedelta

from cogs.engagement.profile_rules import ACHIEVEMENT_IDS, MAIN_GUILD_ID, build_profile


class ProfileRulesTests(unittest.TestCase):
    def facts(self, **changes):
        value = {
            "user_id": "42", "guild_id": MAIN_GUILD_ID, "data_guild_id": MAIN_GUILD_ID,
            "display_name": "Cafe\x00User", "username": "cafe", "server_name": "Animes Café",
            "joined_at": datetime.now(timezone.utc) - timedelta(days=365), "role_ids": [],
            "server_tag": False, "owner_id": 999,
        }
        value.update(changes)
        return value

    def test_all_ids_and_thresholds(self):
        result = build_profile(
            self.facts(), chat_doc={"count": 10_000}, voice_doc={"time": 1000 * 3600},
            profile_doc={"active_days": [f"2026-01-0{i}" for i in range(1, 8)]},
            guild_doc={"members": [{"user_id": 42, "xp": 1000}]},
            event_docs=[{"last_event_scores": {"42": 10, "7": 2}}],
        )
        self.assertEqual(tuple(a["id"] for a in result["achievements"]), ACHIEVEMENT_IDS)
        self.assertEqual(sum(a["unlocked"] for a in result["achievements"]), 8)
        self.assertEqual(result["chat_points"], 10000)
        self.assertEqual(result["voice_seconds"], 3600000)
        self.assertNotIn("\x00", result["display_name"])

    def test_missing_db_facts_are_unknown(self):
        result = build_profile(self.facts(), data_available=False)
        self.assertIsNone(result["chat_points"])
        self.assertFalse(any(a["unlocked"] for a in result["achievements"] if a["id"] not in {"lenda_do_cafe", "criador_da_hatsu"}))

    def test_foreign_guild_cannot_use_global_counters(self):
        result = build_profile(self.facts(guild_id="123", data_guild_id="123"), chat_doc={"count": 999999}, voice_doc={"time": 1e9})
        self.assertIsNone(result["chat_points"])
        self.assertIsNone(result["voice_seconds"])

    def test_earned_is_monotonic_but_supporter_is_live(self):
        result = build_profile(self.facts(), profile_doc={"earned": {"cafeinado": datetime.now(timezone.utc), "apoiador_do_cafe": datetime.now(timezone.utc)}})
        by_id = {a["id"]: a for a in result["achievements"]}
        self.assertTrue(by_id["cafeinado"]["unlocked"])
        self.assertFalse(by_id["apoiador_do_cafe"]["unlocked"])

    def test_event_tie_awards_both_winners(self):
        first = build_profile(self.facts(), event_docs=[{"last_event_scores": {"42": 5, "99": 5}}])
        self.assertTrue(next(a for a in first["achievements"] if a["id"] == "campeao_de_eventos")["unlocked"])

    def badges(self, result):
        return {a["id"]: a for a in result["achievements"]}

    def test_thresholds_just_below_and_exact(self):
        now = datetime(2026, 11, 4, tzinfo=timezone.utc)
        for points, voice, days, expected in ((9999, 359999, 364, False), (10000, 360000, 365, True)):
            with self.subTest(points=points):
                badges = self.badges(build_profile(self.facts(joined_at=now-timedelta(days=days)),
                                                   chat_doc={"count": points}, voice_doc={"time": voice}, now=now))
                for aid in ("cafeinado", "voz_do_cafe", "lenda_do_cafe"):
                    self.assertEqual(badges[aid]["unlocked"], expected)

    def test_saved_cosmetics_and_featured_order(self):
        stored = {"theme": "sakura", "bio": "Oi\x00 pessoal", "earned": {aid: datetime.now(timezone.utc) for aid in ACHIEVEMENT_IDS},
                  "featured": ["voz_do_cafe", "cafeinado", "voz_do_cafe", "maratonista", "invalid"]}
        result = build_profile(self.facts(), profile_doc=stored)
        self.assertEqual(result["theme"], "sakura")
        self.assertEqual(result["bio"], "Oi pessoal")
        self.assertEqual(result["featured"], ["voz_do_cafe", "cafeinado", "maratonista"])
        self.assertEqual(build_profile(self.facts(), profile_doc={**stored, "featured": []})["featured"], [])

    def test_locked_featured_badges_and_invalid_settings_are_removed(self):
        result = build_profile(self.facts(joined_at=None), profile_doc={"theme": "../../etc", "bio": "x"*200,
                              "featured": ["cafeinado", "invalid"]})
        self.assertEqual(result["theme"], "cafe")
        self.assertEqual(len(result["bio"]), 100)
        self.assertEqual(result["featured"], [])

    def test_highest_vip_and_personal_guild_xp(self):
        result = build_profile(self.facts(role_ids=[999723165225857074, 1351596017631494195]),
                               guild_doc={"name": "Café Squad", "members": [{"user_id": "42", "xp": 999}, {"user_id": 1, "xp": 99999}]})
        self.assertEqual(result["vip_label"], "VIP Monarch")
        self.assertEqual(result["guild_name"], "Café Squad")
        self.assertFalse(self.badges(result)["alma_da_guilda"]["unlocked"])

    def test_other_user_and_other_guild_records_are_not_used(self):
        result = build_profile(self.facts(), chat_doc={"_id": "123", "count": 99999},
                               voice_doc={"guild_id": "123", "time": 1e9},
                               economy_doc={"user_id": "123", "eter": 99999},
                               profile_doc={"guild_id": "123", "earned": {"cafeinado": datetime.now(timezone.utc)}})
        self.assertIsNone(result["chat_points"])
        self.assertIsNone(result["voice_seconds"])
        self.assertIsNone(result["eter"])
        self.assertFalse(self.badges(result)["cafeinado"]["unlocked"])

    def test_test_guild_reads_canonical_ranks_but_keeps_local_membership_age(self):
        result = build_profile(self.facts(guild_id="1442105700246491189", joined_at=None),
                               chat_doc={"count": 10000, "guild_id": int(MAIN_GUILD_ID)})
        self.assertEqual(result["chat_points"], 10000)
        self.assertTrue(self.badges(result)["cafeinado"]["unlocked"])
        self.assertFalse(self.badges(result)["lenda_do_cafe"]["unlocked"])

    def test_activity_ignores_duplicates_invalid_and_future_days(self):
        now = datetime(2026, 11, 4, tzinfo=timezone.utc)
        result = build_profile(self.facts(), profile_doc={"active_days": ["2026-11-01", "2026-11-01", "2026-99-99", "9999-01-01", "2026-11-02"]}, now=now)
        self.assertEqual(self.badges(result)["presenca_marcante"]["current"], 2)
        empty = self.badges(build_profile(self.facts()))["presenca_marcante"]
        self.assertTrue(empty["available"])
        self.assertEqual(empty["current"], 0)

    def test_cached_activity_cannot_award_during_outage_and_no_newly_unlocked(self):
        stored = {"active_days": [f"2026-01-0{i}" for i in range(1, 8)]}
        result = build_profile(self.facts(), profile_doc=stored, data_available=False)
        self.assertFalse(self.badges(result)["presenca_marcante"]["unlocked"])
        self.assertEqual(result["newly_unlocked"], [])

    def test_nonfinite_negative_and_boolean_counters_are_unknown(self):
        for value in (float("nan"), float("inf"), -1, True, "garbage", 10**1000):
            with self.subTest(value_type=type(value).__name__):
                result = build_profile(self.facts(), chat_doc={"count": value}, voice_doc={"time": value}, economy_doc={"eter": value})
                self.assertIsNone(result["chat_points"])
                self.assertIsNone(result["voice_seconds"])
                self.assertIsNone(result["eter"])

    def test_invalid_earned_values_do_not_unlock_achievements(self):
        result = build_profile(self.facts(), profile_doc={"earned": {"cafeinado": True, "maratonista": "old"}})
        self.assertFalse(self.badges(result)["cafeinado"]["unlocked"])
        self.assertFalse(self.badges(result)["maratonista"]["unlocked"])

    def test_event_active_edition_does_not_replace_previous_winner(self):
        events = [{"active": True, "current_scores": {"7": 999}, "last_event_scores": {"42": 2}},
                  {"guild_id": "other", "last_event_scores": {"7": 100}}]
        result = build_profile(self.facts(), event_docs=events)
        self.assertTrue(self.badges(result)["campeao_de_eventos"]["unlocked"])
        zeros = build_profile(self.facts(), event_docs=[{"last_event_scores": {"42": 0, "7": -10}}])
        self.assertFalse(self.badges(zeros)["campeao_de_eventos"]["unlocked"])

    def test_owner_and_supporter_require_current_verified_facts(self):
        creator = build_profile(self.facts(user_id="999", server_tag=True))
        self.assertTrue(self.badges(creator)["criador_da_hatsu"]["unlocked"])
        self.assertTrue(self.badges(creator)["apoiador_do_cafe"]["unlocked"])
        fake = build_profile(self.facts(premium_since="yes"))
        self.assertFalse(self.badges(fake)["apoiador_do_cafe"]["unlocked"])


if __name__ == "__main__":
    unittest.main()
