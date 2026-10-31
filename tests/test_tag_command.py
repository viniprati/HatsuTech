import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

os.environ["MONGO_URI"] = ""

from cogs.engagement.commands import tag_command as tag
from cogs.engagement.cog import Engagement


class TagCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.member = SimpleNamespace(
            id=42, bot=False, guild=SimpleNamespace(id=tag.MAIN_GUILD_ID), roles=[],
            primary_guild=SimpleNamespace(id=tag.MAIN_GUILD_ID, identity_enabled=True),
            send=AsyncMock(),
        )
        self.members = [self.member]
        self.channel = MagicMock(spec=discord.TextChannel)
        self.channel.id = tag.APOIADOR_CHANNEL_ID

        async def fetch_members(**kwargs):
            self.assertIsNone(kwargs["limit"])
            for member in self.members:
                yield member

        self.guild = SimpleNamespace(
            id=tag.MAIN_GUILD_ID, name="Animes Café",
            get_role=lambda _id: object(), get_channel=lambda _id: self.channel,
            fetch_members=fetch_members, fetch_member=AsyncMock(return_value=self.member),
        )
        self.it = SimpleNamespace(
            guild=self.guild, user=SimpleNamespace(id=1), permissions=SimpleNamespace(administrator=True),
            response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()),
            edit_original_response=AsyncMock(),
        )
        self.cog = SimpleNamespace(tag_reminder_locks={})
        self.collection = SimpleNamespace(
            find_one=MagicMock(return_value=None),
            update_one=MagicMock(return_value=SimpleNamespace(acknowledged=True)),
        )
        self.patches = [
            patch.object(tag, "ensure_db_online", AsyncMock(return_value=True)),
            patch.object(tag, "is_db_online", return_value=True),
            patch.object(tag, "welcome_dm_logs_col", self.collection),
            patch.object(tag, "DM_DELAY_SECONDS", 0),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def test_sends_approved_message_and_persists_result(self):
        with self.assertLogs(tag.log, level="INFO") as logs:
            await tag.execute(self.cog, self.it)
        self.it.response.defer.assert_awaited_once_with(ephemeral=True)
        self.member.send.assert_awaited_once()
        payload = self.member.send.call_args.kwargs
        self.assertIn("**HatsuTech**, o bot oficial", payload["embed"].description)
        self.assertFalse(payload["allowed_mentions"].everyone)
        self.assertEqual(payload["view"].children[0].url,
                         f"https://discord.com/channels/{tag.MAIN_GUILD_ID}/{tag.APOIADOR_CHANNEL_ID}")
        self.assertEqual(self.collection.update_one.call_args.args[1]["$set"]["status"], "sent")
        self.assertIn("Enviados: **1**", self.it.edit_original_response.call_args.kwargs["content"])
        self.assertTrue(any("tag_reminders_started run_id=" in line for line in logs.output))
        self.assertTrue(any("tag_reminders_finished run_id=" in line for line in logs.output))

    def test_excludes_bots_hidden_tags_other_guilds_and_existing_supporters(self):
        self.assertTrue(tag.needs_supporter_reminder(self.member))
        changes = [
            {"bot": True}, {"primary_guild": None},
            {"primary_guild": SimpleNamespace(id=tag.MAIN_GUILD_ID, identity_enabled=False)},
            {"primary_guild": SimpleNamespace(id=tag.MAIN_GUILD_ID, identity_enabled=None)},
            {"primary_guild": SimpleNamespace(id=123, identity_enabled=True)},
            {"roles": [SimpleNamespace(id=tag.APOIADOR_ROLE_ID)]},
        ]
        for change in changes:
            with self.subTest(change=change):
                member = SimpleNamespace(**{**vars(self.member), **change})
                self.assertFalse(tag.needs_supporter_reminder(member))

    async def test_non_admin_is_denied_even_with_full_access(self):
        self.it.permissions.administrator = False
        await tag.execute(self.cog, self.it)
        self.member.send.assert_not_awaited()
        self.collection.find_one.assert_not_called()

    async def test_database_offline_at_start_prevents_scan(self):
        with patch.object(tag, "ensure_db_online", AsyncMock(return_value=False)):
            await tag.execute(self.cog, self.it)
        self.member.send.assert_not_awaited()
        self.it.edit_original_response.assert_not_awaited()

    async def test_test_server_cannot_send_main_server_reminders(self):
        self.guild.id = 123
        await tag.execute(self.cog, self.it)
        self.member.send.assert_not_awaited()
        self.assertIn("servidor principal", self.it.followup.send.call_args.args[0])

    async def test_registered_command_checks_administrator_at_runtime(self):
        self.it.permissions.administrator = False
        with self.assertRaises(discord.app_commands.MissingPermissions):
            await Engagement.tag.checks[0](self.it)

    async def test_does_not_repeat_successful_or_closed_dm(self):
        for status in ("sent", "dm_closed"):
            with self.subTest(status=status):
                self.collection.find_one.return_value = {"status": status}
                await tag.execute(self.cog, self.it)
                self.member.send.assert_not_awaited()
                self.collection.update_one.assert_not_called()

    async def test_claim_during_scan_prevents_dm(self):
        refreshed = SimpleNamespace(**{**vars(self.member), "roles": [SimpleNamespace(id=tag.APOIADOR_ROLE_ID)]})
        self.guild.fetch_member.return_value = refreshed
        await tag.execute(self.cog, self.it)
        self.member.send.assert_not_awaited()

    async def test_closed_dm_is_recorded_and_reported(self):
        self.member.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Closed")
        await tag.execute(self.cog, self.it)
        self.assertEqual(self.collection.update_one.call_args.args[1]["$set"]["status"], "dm_closed")
        self.assertIn("Bloqueados: **1**", self.it.edit_original_response.call_args.kwargs["content"])

    async def test_fetch_forbidden_does_not_mark_dms_closed(self):
        self.guild.fetch_member.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Denied")
        with self.assertLogs(tag.log, level="WARNING"):
            await tag.execute(self.cog, self.it)
        self.collection.update_one.assert_not_called()
        self.member.send.assert_not_awaited()

    async def test_database_failure_before_send_stops_delivery(self):
        with patch.object(tag, "is_db_online", return_value=False):
            await tag.execute(self.cog, self.it)
        self.member.send.assert_not_awaited()
        self.assertIn("Banco indisponível", self.it.edit_original_response.call_args.kwargs["content"])

    async def test_unacknowledged_history_stops_before_next_recipient(self):
        self.members.append(SimpleNamespace(**{**vars(self.member), "id": 43}))
        self.collection.update_one.return_value = SimpleNamespace(acknowledged=False)
        await tag.execute(self.cog, self.it)
        self.member.send.assert_awaited_once()
        self.assertIn("registrar o resultado", self.it.edit_original_response.call_args.kwargs["content"])

    async def test_rate_limit_stops_run_without_marking_delivery(self):
        self.members.append(SimpleNamespace(**{**vars(self.member), "id": 43}))
        self.member.send.side_effect = discord.HTTPException(SimpleNamespace(status=429, reason="Too Many Requests"), "Rate limited")
        with self.assertLogs(tag.log, level="WARNING"):
            await tag.execute(self.cog, self.it)
        self.member.send.assert_awaited_once()
        self.collection.update_one.assert_not_called()

    async def test_concurrent_run_is_rejected(self):
        lock = asyncio.Lock()
        await lock.acquire()
        self.cog.tag_reminder_locks[self.guild.id] = lock
        try:
            await tag.execute(self.cog, self.it)
        finally:
            lock.release()
        self.member.send.assert_not_awaited()
        self.assertIn("já está em andamento", self.it.followup.send.call_args.args[0])

    async def test_incomplete_member_scan_does_not_send_partial_campaign(self):
        async def broken_scan(**kwargs):
            yield self.member
            raise discord.HTTPException(SimpleNamespace(status=500, reason="Error"), "Unavailable")
        self.guild.fetch_members = broken_scan
        with self.assertLogs(tag.log, level="WARNING"):
            await tag.execute(self.cog, self.it)
        self.member.send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
