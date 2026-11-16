import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["MONGO_URI"] = ""

import discord
from pymongo.errors import AutoReconnect

import database
from cogs.guilda import finance
from cogs.guilda.commands import historico_guilda_command as history
from cogs.guilda.commands.distribuir_command import resolve_present_ids


class TransactionTests(unittest.TestCase):
    def test_session_operations_propagate_failures_instead_of_returning_defaults(self):
        collection = MagicMock()
        collection.update_one.side_effect = AutoReconnect("simulated failure")
        session = SimpleNamespace(client={database.MONGO_DB_NAME: {"test": collection}})
        with self.assertRaises(AutoReconnect):
            database.ResilientCollection("test").update_one({}, {}, session=session)

    def test_session_cursor_errors_are_not_swallowed(self):
        collection = MagicMock()
        collection.find.return_value.__iter__.side_effect = AutoReconnect("lazy cursor failure")
        session = SimpleNamespace(client={database.MONGO_DB_NAME: {"test": collection}})
        cursor = database.ResilientCollection("test").find({}, session=session)
        with self.assertRaises(AutoReconnect):
            list(cursor)

    def test_offline_transaction_does_not_call_callback(self):
        callback = MagicMock()
        with patch.object(database, "_ensure_connection", return_value=False):
            with self.assertRaises(database.TransactionUnavailable):
                database.run_transaction(callback)
        callback.assert_not_called()

    def test_transaction_error_is_private_and_preserves_failure_marker(self):
        client = MagicMock()
        client.start_session.side_effect = AutoReconnect("private connection detail")
        before = database.get_db_failure_generation()
        with patch.object(database, "client", client), patch.object(database, "_ensure_connection", return_value=True):
            with self.assertRaises(database.TransactionUnavailable) as error:
                database.run_transaction(MagicMock())
        self.assertNotIn("private connection detail", str(error.exception))
        self.assertGreater(database.get_db_failure_generation(), before)

    def test_invalid_creation_input_cannot_start_a_charge(self):
        with patch.object(finance, "run_transaction") as transaction:
            with self.assertRaises(finance.GuildFinanceError):
                finance.create_guild(1, 2, " ", "🛡️", "create:1")
        transaction.assert_not_called()

    def test_membership_snapshot_ignores_concurrent_xp_but_detects_rejoining(self):
        now = datetime.now(timezone.utc)
        old = [{"user_id": 1, "joined_at": now, "xp": 1}]
        self.assertEqual(finance.membership_signature(old), finance.membership_signature([
            {"user_id": 1, "joined_at": now, "xp": 100},
        ]))
        self.assertNotEqual(finance.membership_signature(old), finance.membership_signature([
            {"user_id": 1, "joined_at": now + timedelta(days=1)},
        ]))


class GuildPrivacyTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self, uid=1, gid=2):
        return SimpleNamespace(
            user=SimpleNamespace(id=uid), guild_id=gid, guild=SimpleNamespace(id=gid),
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), is_done=lambda: True),
            followup=SimpleNamespace(send=AsyncMock()), edit_original_response=AsyncMock(),
        )

    async def test_other_member_cannot_use_history_view(self):
        view = history.GuildHistoryView(1, 2, "team")
        interaction = self.interaction(uid=3)
        self.assertFalse(await view.interaction_check(interaction))
        self.assertTrue(interaction.response.send_message.call_args.kwargs["ephemeral"])

    async def test_history_is_ephemeral_and_has_no_arbitrary_guild_argument(self):
        interaction = self.interaction()
        document = {"_id": "team", "name": "Equipe", "treasury_eter": 10}
        with patch.object(finance, "read_current_guild", return_value=document), \
             patch.object(finance, "read_history", return_value=(document, [])):
            await history.execute(None, interaction)
        self.assertTrue(interaction.response.defer.call_args.kwargs["ephemeral"])
        self.assertTrue(interaction.followup.send.call_args.kwargs["ephemeral"])
        self.assertFalse(interaction.followup.send.call_args.kwargs["allowed_mentions"].everyone)

    async def test_former_member_loses_navigation_access(self):
        view = history.GuildHistoryView(1, 2, "team")
        interaction = self.interaction()
        with patch.object(finance, "read_history", side_effect=finance.GuildFinanceError("Você saiu da guilda.")):
            await view.change_page(interaction, 1)
        payload = interaction.edit_original_response.call_args.kwargs
        self.assertIsNone(payload["view"])
        self.assertIsNone(payload["embed"])

    async def test_uncertain_discord_membership_stops_distribution(self):
        guild = SimpleNamespace(get_member=lambda uid: None, fetch_member=AsyncMock())
        guild.fetch_member.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "no access")
        with self.assertRaises(finance.GuildFinanceError):
            await resolve_present_ids(guild, [{"user_id": 1}])

    async def test_only_confirmed_departures_and_bots_are_excluded(self):
        guild = SimpleNamespace(get_member=lambda uid: SimpleNamespace(id=uid, bot=uid == 2) if uid != 3 else None,
                                fetch_member=AsyncMock())
        guild.fetch_member.side_effect = discord.NotFound(SimpleNamespace(status=404, reason="Not found"), "left")
        self.assertEqual(await resolve_present_ids(guild, [{"user_id": uid} for uid in (1, 2, 3)]), {1})

    async def test_history_paginates_and_bounds_fields(self):
        view = history.GuildHistoryView(1, 2, "team")
        entries = [{"type": "distribution", "actor_id": "1", "amount": 100,
                    "share": 10, "recipients": [str(uid) for uid in range(1, 11)]} for _ in range(15)]
        embed = view.render({"name": "Equipe"}, entries)
        self.assertEqual(len(embed.fields), 5)
        self.assertTrue(view.previous.disabled)
        self.assertFalse(view.next.disabled)
        self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))
