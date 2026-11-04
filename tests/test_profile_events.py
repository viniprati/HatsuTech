import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["MONGO_URI"] = ""

from cogs.ranks.commands import evento_encerrar_command as first
from cogs.ranks.commands import evento2_encerrar_command as second
from cogs.engagement import profile_service
from main import SecurityBot


class EventArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_close_uses_atomic_persisted_scores_and_preserves_winners(self):
        guild = SimpleNamespace(id=profile_service.MAIN_GUILD_ID)
        for module, config in ((first, "config"), (second, "config2")):
            with self.subTest(config=config):
                collection = MagicMock()
                closed = {"_id": config, "channel_id": 55, "last_event_scores": {"42": 100}}
                collection.find_one_and_update.return_value = closed
                it = SimpleNamespace(guild=guild, response=SimpleNamespace(defer=AsyncMock()), edit_original_response=AsyncMock())
                cog = SimpleNamespace(bot=SimpleNamespace(event_cache={55: {}}))
                with patch.object(module, "event_col", collection), patch.object(module, "ensure_db_online", AsyncMock(return_value=True)), patch.object(profile_service, "record_event_achievements", AsyncMock()) as award:
                    await module.execute(cog, it)
                query, pipeline = collection.find_one_and_update.call_args.args
                self.assertEqual(query, {"_id": config, "active": True})
                self.assertEqual(pipeline[0]["$set"]["last_event_scores"], {"$ifNull": ["$current_scores", {}]})
                award.assert_awaited_once_with(guild, {"42": 100}, source="evento_encerrar" if module is first else "evento2_encerrar")
                self.assertIn("Evento", it.edit_original_response.call_args.kwargs["content"])

    async def test_expiry_does_not_award_stale_routing_cache_winners(self):
        guild = SimpleNamespace(id=profile_service.MAIN_GUILD_ID)
        message = SimpleNamespace(content="uma mensagem válida", channel=SimpleNamespace(id=55), author=SimpleNamespace(id=42), guild=guild)
        bot = SimpleNamespace(event_cooldown={}, last_event_check=100,
            event_cache={55: {"_id": "config", "active": True, "end_time": 99, "current_scores": {"old": 100}}}, spam_system=None)
        collection = MagicMock()
        collection.find_one_and_update.return_value = {"last_event_scores": {"new": 200}}
        with patch("main.time.time", return_value=100), patch("main.event_col", collection), patch.object(profile_service, "record_event_achievements", AsyncMock()) as award:
            await SecurityBot.process_event_message(bot, message)
        award.assert_awaited_once_with(guild, {"new": 200}, source="event_expiry")
        query = collection.find_one_and_update.call_args.args[0]
        self.assertEqual(query["end_time"], {"$gt": 0, "$lte": 100})
        self.assertNotIn(55, bot.event_cache)

    async def test_failed_close_never_awards(self):
        it = SimpleNamespace(guild=None, response=SimpleNamespace(defer=AsyncMock()), edit_original_response=AsyncMock())
        collection = MagicMock()
        collection.find_one_and_update.return_value = None
        with patch.object(first, "event_col", collection), patch.object(first, "ensure_db_online", AsyncMock(return_value=True)), patch.object(profile_service, "record_event_achievements", AsyncMock()) as award:
            await first.execute(SimpleNamespace(), it)
        award.assert_not_awaited()
        self.assertIn("Não foi possível", it.edit_original_response.call_args.kwargs["content"])
