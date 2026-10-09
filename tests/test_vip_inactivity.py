import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

os.environ["MONGO_URI"] = ""

from cogs.vip import cog as vip_module


class FakeVipCollection:
    def __init__(self, doc):
        self.doc = doc

    def find_one(self, query):
        if isinstance(query.get("_id"), dict):
            return None
        return self.doc if query.get("_id") == self.doc["_id"] else None

    def find(self, _query):
        return [self.doc]

    def update_one(self, _query, update):
        self.doc.update(update.get("$set", {}))
        return SimpleNamespace(matched_count=1)


class VipInactivityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.doc = {
            "_id": "1:2",
            "guild_id": "1",
            "user_id": "2",
            "role_id": "3",
            "role_source": "command:/vip:common",
            "status": "active",
            "last_activity_at": self.now - timedelta(days=22),
        }
        self.role = SimpleNamespace(id=3, name="VIP comum", managed=False, delete=AsyncMock())
        self.member = SimpleNamespace(id=2, bot=False, voice=None, mention="@Dono")
        self.guild = SimpleNamespace(
            id=1, afk_channel=None,
            get_member=lambda uid: self.member if uid == 2 else None,
            get_role=lambda rid: self.role if rid == 3 else None,
        )
        self.member.guild = self.guild
        self.system = vip_module.VipSystem.__new__(vip_module.VipSystem)
        self.system._vip_locks = {}
        self.system._common_vip_owners = {(1, 2): self.doc["_id"]}
        self.system._common_vip_activity_written = {}
        self.system.bot = SimpleNamespace(guilds=[self.guild])
        self.system._get_vip_doc = AsyncMock(return_value=self.doc)
        self.system.enviar_log = AsyncMock()

        async def save(_uid, update, _source, **_kwargs):
            self.doc.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                self.doc.pop(key, None)

        self.system._update_vip_role_with_snapshot = AsyncMock(side_effect=save)
        self.collection = FakeVipCollection(self.doc)
        self.patches = [
            patch.object(vip_module, "vip_col", self.collection),
            patch.object(vip_module, "is_db_online", return_value=True),
            patch.object(vip_module, "bot_can_manage_role", return_value=True),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    async def test_deletes_only_expired_common_role_and_clears_link(self):
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=21))
        self.role.delete.assert_awaited_once()
        self.assertEqual(self.doc["status"], "inactive")
        self.assertNotIn("role_id", self.doc)
        self.assertEqual(self.doc["last_role_id"], "3")

    async def test_recent_activity_prevents_deletion(self):
        self.doc["last_activity_at"] = self.now - timedelta(days=1)
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=21))
        self.role.delete.assert_not_awaited()
        self.assertEqual(self.doc["status"], "active")

    async def test_special_or_linked_role_is_preserved(self):
        for source in ("command:/vincular_vip", "command:/vip:highlight"):
            with self.subTest(source=source):
                self.doc["role_source"] = source
                await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=21))
        self.role.delete.assert_not_awaited()

    async def test_voice_presence_prevents_deletion(self):
        self.member.voice = SimpleNamespace(channel=object())
        self.system._record_common_vip_voice_activity = AsyncMock(return_value=True)
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=21))
        self.role.delete.assert_not_awaited()
        self.system._record_common_vip_voice_activity.assert_awaited_once()

    async def test_discord_failure_keeps_role_link_for_retry(self):
        response = SimpleNamespace(status=403, reason="Forbidden", text="Forbidden")
        self.role.delete.side_effect = discord.Forbidden(response, "Forbidden")
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=21))
        self.assertEqual(self.doc["role_id"], "3")
        self.assertEqual(self.doc["status"], "needs_review")
        self.assertEqual(self.doc["cleanup_reason"], "inactivity_delete_failed")

    async def test_missing_history_starts_new_21_day_window(self):
        self.doc["last_activity_at"] = self.now - timedelta(days=30)
        self.system._delete_inactive_common_vip = AsyncMock()
        await self.system._check_inactive_common_vips_once()
        self.system._delete_inactive_common_vip.assert_not_awaited()
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)

    async def test_legacy_record_gets_guild_scope_before_role_deletion(self):
        self.doc.pop("guild_id")
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=21))
        self.role.delete.assert_awaited_once()
        self.assertEqual(self.doc["guild_id"], "1")

    async def test_short_voice_session_is_recorded_on_join(self):
        after = SimpleNamespace(channel=object())
        await self.system.on_voice_state_update(self.member, SimpleNamespace(channel=None), after)
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)

    async def test_message_activity_is_recorded(self):
        message = SimpleNamespace(guild=self.guild, author=self.member)
        await self.system.on_message(message)
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)


if __name__ == "__main__":
    unittest.main()
