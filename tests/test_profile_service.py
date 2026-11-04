import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ["MONGO_URI"] = ""

from cogs.engagement import profile_service as service


class ProfileServiceTests(unittest.TestCase):
    def setUp(self):
        self.facts = {
            "user_id": "42", "guild_id": str(service.MAIN_GUILD_ID),
            "data_guild_id": str(service.MAIN_GUILD_ID), "main_guild_id": str(service.MAIN_GUILD_ID),
            "display_name": "Pessoa", "username": "pessoa", "server_name": "Animes Café",
            "role_ids": [], "server_tag": False,
        }
        self.cols = {}
        for name in ("profiles_col", "msg_col", "voice_col", "eco_users_col", "guilds_col", "event_col"):
            col = MagicMock()
            col.find_one.return_value = None
            col.update_one.return_value = SimpleNamespace(acknowledged=True)
            self.cols[name] = col
            p = patch.object(service, name, col)
            p.start()
            self.addCleanup(p.stop)

    def test_degraded_database_does_not_fabricate_balances_or_write_awards(self):
        with patch.object(service, "is_db_online", return_value=False):
            result = service.ProfileService.read_profile(self.facts, "request")
        self.assertFalse(result["data_available"])
        self.assertIsNone(result["eter"])
        self.assertIsNone(result["chat_points"])
        self.cols["msg_col"].find_one.assert_not_called()
        self.cols["profiles_col"].update_one.assert_not_called()

    def test_partial_read_failure_marks_all_database_data_unknown(self):
        self.cols["msg_col"].find_one.return_value = {"_id": "42", "count": 20000}
        with patch.object(service, "is_db_online", side_effect=[True, False]):
            result = service.ProfileService.read_profile(self.facts, "request")
        self.assertFalse(result["data_available"])
        self.assertIsNone(result["chat_points"])
        self.cols["profiles_col"].update_one.assert_not_called()

    def test_reconnection_does_not_erase_an_earlier_read_failure(self):
        self.cols["msg_col"].find_one.return_value = None  # Wrapper's failed-read fallback.
        self.cols["voice_col"].find_one.return_value = {"time": 1000 * 3600}
        # Global status has already recovered when checked, but its failure marker changed.
        with patch.object(service, "is_db_online", return_value=True), patch.object(service, "get_db_failure_generation", side_effect=[3, 3, 4]):
            result = service.ProfileService.read_profile(self.facts, "reconnected")
        self.assertFalse(result["data_available"])
        self.assertIsNone(result["chat_points"])
        self.assertIsNone(result["voice_seconds"])
        self.cols["profiles_col"].update_one.assert_not_called()

    def test_awards_use_atomic_earliest_time_and_separate_profile_scope(self):
        self.cols["msg_col"].find_one.return_value = {"_id": "42", "count": 10000}
        with patch.object(service, "is_db_online", return_value=True):
            result = service.ProfileService.read_profile(self.facts, "request")
        args = self.cols["profiles_col"].update_one.call_args
        self.assertEqual(args.args[0], {"_id": f"{service.MAIN_GUILD_ID}:42"})
        self.assertIn("earned.cafeinado", args.args[1]["$min"])
        self.assertNotIn("$set", args.args[1])
        self.assertTrue(result["persistence_available"])
        self.cols["eco_users_col"].update_one.assert_not_called()

    def test_failed_award_write_is_explicit(self):
        self.cols["msg_col"].find_one.return_value = {"count": 10000}
        self.cols["profiles_col"].update_one.return_value.acknowledged = False
        with patch.object(service, "is_db_online", return_value=True):
            result = service.ProfileService.read_profile(self.facts, "request")
        self.assertFalse(result["persistence_available"])

    def test_settings_cannot_modify_facts_or_earned_state(self):
        service.ProfileService.save_settings(1, 42, {"bio": "Oi", "eter": 900, "earned": {"cafeinado": True}})
        query, update = self.cols["profiles_col"].update_one.call_args.args
        self.assertEqual(query, {"_id": "1:42"})
        self.assertEqual(set(update["$set"]), {"bio", "updated_at"})

    def test_unrelated_guild_cannot_query_main_legacy_rank_or_team(self):
        facts = {**self.facts, "guild_id": "100", "data_guild_id": "100"}
        with patch.object(service, "is_db_online", return_value=True):
            service.ProfileService.read_profile(facts, "request")
        self.cols["msg_col"].find_one.assert_not_called()
        self.cols["guilds_col"].find_one.assert_not_called()
        self.cols["event_col"].find_one.assert_not_called()
        self.cols["eco_users_col"].find_one.assert_called_once_with({"_id": "100:42"})


class ActivityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.service = service.ProfileService()
        self.member = SimpleNamespace(id=42, guild=SimpleNamespace(id=1))

    async def test_one_successful_write_per_brt_day_and_retry_failure(self):
        collection = MagicMock()
        collection.update_one.side_effect = [SimpleNamespace(acknowledged=False), SimpleNamespace(acknowledged=True),
                                             SimpleNamespace(acknowledged=True)]
        now = datetime(2026, 11, 4, 2, 59, tzinfo=timezone.utc)
        with patch.object(service, "profiles_col", collection), patch.object(service, "is_db_online", return_value=True):
            await self.service.record_activity(self.member, now)
            await self.service.record_activity(self.member, now)
            await self.service.record_activity(self.member, now)
            self.assertEqual(collection.update_one.call_count, 2)
            pipeline = collection.update_one.call_args.args[1]
            days = pipeline[0]["$set"]["active_days"]["$slice"][0]["$setUnion"][1]
            self.assertEqual(days, ["2026-11-03"])
            await self.service.record_activity(self.member, now.replace(hour=3))
            self.assertEqual(collection.update_one.call_count, 3)

    async def test_activity_cache_is_bounded_and_offline_does_not_fill_cache(self):
        collection = MagicMock()
        collection.update_one.return_value = SimpleNamespace(acknowledged=True)
        with patch.object(service, "profiles_col", collection), patch.object(service, "is_db_online", return_value=False):
            await self.service.record_activity(self.member)
        collection.update_one.assert_not_called()
        self.assertFalse(self.service.activity_cache)
        with patch.object(service, "profiles_col", collection), patch.object(service, "is_db_online", return_value=True), patch.object(service, "MAX_ACTIVITY_CACHE", 2):
            for uid in range(4):
                await self.service.record_activity(SimpleNamespace(id=uid, guild=self.member.guild))
        self.assertEqual(len(self.service.activity_cache), 2)


class EventAchievementTests(unittest.IsolatedAsyncioTestCase):
    async def test_positive_ties_are_preserved_and_bots_skipped(self):
        guild = SimpleNamespace(id=service.MAIN_GUILD_ID,
                                get_member=lambda uid: SimpleNamespace(bot=uid == 3))
        collection = MagicMock()
        collection.update_one.return_value = SimpleNamespace(acknowledged=True)
        scores = {"1": 10, "2": 10, "3": 10, "4": 0, "5": -1, "6": "nan", "7": "inf", "bad": 100}
        with patch.object(service, "profiles_col", collection):
            await service.record_event_achievements(guild, scores, source="test")
        self.assertEqual(collection.update_one.call_count, 2)
        queries = [call.args[0]["_id"] for call in collection.update_one.call_args_list]
        self.assertEqual(queries, [f"{guild.id}:1", f"{guild.id}:2"])
        update = collection.update_one.call_args.args[1]
        self.assertIn("earned.campeao_de_eventos", update["$min"])

    async def test_foreign_guild_empty_event_and_failure_do_not_claim_success(self):
        guild = SimpleNamespace(id=1, get_member=lambda uid: None)
        collection = MagicMock()
        with patch.object(service, "profiles_col", collection):
            await service.record_event_achievements(guild, {"42": 1}, source="test")
            guild.id = service.MAIN_GUILD_ID
            await service.record_event_achievements(guild, {}, source="test")
        collection.update_one.assert_not_called()
        collection.update_one.return_value = SimpleNamespace(acknowledged=False)
        with patch.object(service, "profiles_col", collection), self.assertLogs(service.log, level="WARNING") as logs:
            await service.record_event_achievements(guild, {"42": 1, "43": 1}, source="test")
        self.assertEqual(collection.update_one.call_count, 1)
        self.assertIn("incomplete", logs.output[0])
