import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

os.environ["MONGO_URI"] = ""

from cogs.vip import capacity_alerts


class VipCapacityAlertTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.owner = SimpleNamespace(id=42, bot=False, send=AsyncMock())
        self.role = SimpleNamespace(id=21, name="VIP pessoal", members=list(range(23)), is_default=lambda: False)
        self.guild = SimpleNamespace(id=11, chunked=True, get_role=lambda _: self.role,
                                     get_member=lambda _: self.owner)
        self.cog = SimpleNamespace(bot=object(), get_vip_limit=lambda _: 20,
                                   _is_personal_vip_role=lambda role: role is not None)
        self.document = {"_id": "11:42", "user_id": "42", "role_id": "21",
                         "member_slot_upgrade": {"role_id": "21", "count": 2}}
        self.monitor = capacity_alerts.VipCapacityAlerts(self.cog, lambda doc: doc["user_id"])
        self.collection = MagicMock()
        self.collection.find.return_value = [self.document]
        self.alert = AsyncMock()
        for name, value in (("vip_col", self.collection), ("send_admin_audit_dm", self.alert),
                            ("is_db_online", lambda: True)):
            patcher = patch.object(capacity_alerts, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_extra_slots_count_and_new_alert_requires_resolution(self):
        await self.monitor.check(self.guild, {21})
        await self.monitor.check(self.guild)
        self.alert.assert_awaited_once()
        alert = self.alert.call_args.kwargs
        self.assertIs(alert["target"], self.owner)
        self.assertIsNone(alert["actor"])
        self.assertEqual(alert["details"]["Limite"], "22 (20 do VIP + 2 vagas extras)")
        self.assertEqual(alert["details"]["Excedente"], "1")

        self.role.members.pop()
        await self.monitor.check(self.guild, {21})
        self.role.members.append(99)
        await self.monitor.check(self.guild, {21})
        self.assertEqual(self.alert.await_count, 2)

    async def test_owner_receives_one_dm_every_minute_during_excess(self):
        with patch.object(capacity_alerts, "monotonic", side_effect=[100, 159, 160, 161]):
            await self.monitor.check(self.guild)
            await self.monitor.check(self.guild, {21})
            self.owner.send.assert_awaited_once()
            await self.monitor.check(self.guild)
            await self.monitor.check(self.guild, {21})
        self.assertEqual(self.owner.send.await_count, 2)
        self.alert.assert_awaited_once()
        payload = self.owner.send.call_args
        self.assertIn("/vip_vagas", payload.args[0])
        self.assertFalse(payload.kwargs["allowed_mentions"].users)
        self.role.members.pop()
        await self.monitor.check(self.guild)
        self.assertFalse(self.monitor.owner_reminders)
        self.assertEqual(self.owner.send.await_count, 2)

    async def test_closed_dm_suppresses_repeated_attempts_for_same_excess(self):
        self.owner.send.side_effect = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "DM fechada")
        with patch.object(capacity_alerts, "monotonic", side_effect=[100, 160]):
            await self.monitor.check(self.guild)
            await self.monitor.check(self.guild)
        self.owner.send.assert_awaited_once()
        self.alert.assert_awaited_once()

    async def test_partial_member_cache_never_resets_existing_alert(self):
        self.guild.chunked = False
        await self.monitor.check(self.guild)
        self.assertEqual(self.alert.call_args.kwargs["details"]["Membros no cargo"], "Pelo menos 23")
        self.role.members.pop()
        await self.monitor.check(self.guild)
        self.role.members.append(99)
        await self.monitor.check(self.guild)
        self.alert.assert_awaited_once()

    async def test_ignores_highlight_and_role_with_ambiguous_owners(self):
        self.collection.find.return_value = [{**self.document, "highlight_id": "21"}]
        await self.monitor.check(self.guild)
        self.collection.find.return_value = [self.document, {**self.document, "_id": "11:43", "user_id": "43"}]
        await self.monitor.check(self.guild)
        self.alert.assert_not_awaited()

    async def test_database_read_failure_does_not_report_or_consume_alert(self):
        with patch.object(capacity_alerts, "get_db_failure_generation", side_effect=[4, 5]):
            await self.monitor.check(self.guild)
        self.assertFalse(self.monitor.reported)
        self.alert.assert_not_awaited()
