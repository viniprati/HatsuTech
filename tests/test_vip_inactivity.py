import os
import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

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
            "last_activity_at": self.now - timedelta(days=11),
            "inactivity_policy": vip_module.VIP_INACTIVITY_POLICY,
        }
        self.role = SimpleNamespace(id=3, name="VIP comum", mention="<@&3>", managed=False, delete=AsyncMock())
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
        self.system._monarch_highlight_owners = {}
        self.system._monarch_highlight_activity_written = {}
        self.system._common_vip_cache_loaded = True
        self.system._monarch_highlight_cache_loaded = True
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
            patch.object(vip_module, "send_admin_audit_dm", AsyncMock(return_value={"sent": 2})),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()

    async def test_deletes_only_expired_common_role_and_clears_link(self):
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.role.delete.assert_awaited_once()
        self.assertEqual(self.doc["status"], "inactive")
        self.assertNotIn("role_id", self.doc)
        self.assertEqual(self.doc["last_role_id"], "3")
        vip_module.send_admin_audit_dm.assert_awaited_once()

    async def test_recent_activity_prevents_deletion(self):
        self.doc["last_activity_at"] = self.now - timedelta(days=1)
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.role.delete.assert_not_awaited()
        self.assertEqual(self.doc["status"], "active")

    async def test_deletion_report_contains_owner_role_and_reason(self):
        await self.system._delete_vip_role_with_audit(self.guild, 2, self.role, "Inatividade por 10 dias", "test")
        payload = vip_module.send_admin_audit_dm.call_args.kwargs
        self.assertEqual(payload["target_id"], 2)
        self.assertEqual(payload["reason"], "Inatividade por 10 dias")
        self.assertIn("3", payload["details"]["Cargo excluído"])
        self.assertEqual(payload["source"], "vip_role_delete:test")

    async def test_dm_failure_does_not_prevent_database_cleanup(self):
        vip_module.send_admin_audit_dm.side_effect = RuntimeError("DM indisponível")
        with self.assertLogs(vip_module.log, level="ERROR"):
            await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.role.delete.assert_awaited_once()
        self.assertEqual(self.doc["status"], "inactive")
        self.assertNotIn("role_id", self.doc)

    async def test_already_missing_role_does_not_send_deletion_report(self):
        response = SimpleNamespace(status=404, reason="Not Found")
        self.role.delete.side_effect = discord.NotFound(response, "Not Found")
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        vip_module.send_admin_audit_dm.assert_not_awaited()

    async def test_audit_helper_rejects_base_roles(self):
        self.role.id = vip_module.MONARCH_VIP_ID
        with self.assertRaises(ValueError):
            await self.system._delete_vip_role_with_audit(self.guild, 2, self.role, "test", "test")
        self.role.delete.assert_not_awaited()
        vip_module.send_admin_audit_dm.assert_not_awaited()

    async def test_owner_panel_defers_before_deletion_and_sends_followup(self):
        view = vip_module.VipMainView.__new__(vip_module.VipMainView)
        view.cog, view.role = self.system, self.role
        view._ensure_owner_binding = AsyncMock(return_value=True)
        view.stop = MagicMock()
        it = SimpleNamespace(
            guild=self.guild, user=self.member,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        with patch.object(vip_module, "ensure_db_online", AsyncMock(return_value=True)):
            await vip_module.VipMainView.delete(view, it, None)
        it.response.defer.assert_awaited_once_with(ephemeral=True)
        it.response.send_message.assert_not_awaited()
        it.followup.send.assert_awaited_once()
        vip_module.send_admin_audit_dm.assert_awaited_once()

    async def test_highlight_panel_reports_deletion_with_owner_actor(self):
        self.configure_monarch_highlight()
        view = vip_module.VipHighlightView.__new__(vip_module.VipHighlightView)
        view.cog, view.role = self.system, self.highlight
        view._ensure_owner_binding = AsyncMock(return_value=True)
        view.stop = MagicMock()
        it = SimpleNamespace(
            guild=self.guild, user=self.member,
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        with patch.object(vip_module, "ensure_db_online", AsyncMock(return_value=True)):
            await vip_module.VipHighlightView.delete_highlight(view, it, None)
        it.response.defer.assert_awaited_once_with(ephemeral=True)
        self.highlight.delete.assert_awaited_once()
        self.assertEqual(vip_module.send_admin_audit_dm.call_args.kwargs["actor"], self.member)
        self.assertEqual(vip_module.send_admin_audit_dm.call_args.kwargs["details"]["Tipo"], "destaque")

    async def test_relink_starts_new_window_and_registers_owner_cache(self):
        from cogs.vip.commands import vincular_vip_command as command

        self.system._common_vip_owners.clear()
        self.system._position_common_vip_role = AsyncMock(return_value=True)
        it = SimpleNamespace(guild=self.guild, user=self.member, response=SimpleNamespace(send_message=AsyncMock()))
        with patch.object(command, "ensure_db_online", AsyncMock(return_value=True)), \
             patch.object(command, "vip_col", self.collection), \
             patch.object(command, "send_admin_audit_dm", AsyncMock()):
            await command.execute(self.system, it, self.member, self.role)
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)
        self.assertEqual(self.doc["inactivity_policy"], vip_module.VIP_INACTIVITY_POLICY)
        self.assertEqual(self.system._common_vip_owners[(1, 2)], self.doc["_id"])

    async def test_unrecognized_role_source_is_preserved(self):
        for source in ("unknown", "command:/vip:highlight"):
            with self.subTest(source=source):
                self.doc["role_source"] = source
                await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.role.delete.assert_not_awaited()

    async def test_voice_presence_prevents_deletion(self):
        self.member.voice = SimpleNamespace(channel=object())
        self.system._record_common_vip_voice_activity = AsyncMock(return_value=True)
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.role.delete.assert_not_awaited()
        self.system._record_common_vip_voice_activity.assert_awaited_once()

    async def test_discord_failure_keeps_role_link_for_retry(self):
        response = SimpleNamespace(status=403, reason="Forbidden", text="Forbidden")
        self.role.delete.side_effect = discord.Forbidden(response, "Forbidden")
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.assertEqual(self.doc["role_id"], "3")
        self.assertEqual(self.doc["status"], "needs_review")
        self.assertEqual(self.doc["cleanup_reason"], "inactivity_delete_failed")
        vip_module.send_admin_audit_dm.assert_not_awaited()

    async def test_missing_history_starts_new_10_day_window(self):
        self.doc["last_activity_at"] = self.now - timedelta(days=30)
        self.system._delete_inactive_common_vip = AsyncMock()
        await self.system._check_inactive_common_vips_once()
        self.system._delete_inactive_common_vip.assert_not_awaited()
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)

    async def test_legacy_record_gets_guild_scope_before_role_deletion(self):
        self.doc.pop("guild_id")
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
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

    async def test_nine_days_without_activity_preserves_personal_role(self):
        self.doc["last_activity_at"] = self.now - timedelta(days=9, hours=23)
        self.doc["inactivity_observed_at"] = self.now
        await self.system._check_inactive_common_vips_once()
        self.role.delete.assert_not_awaited()

    async def test_ten_days_without_activity_deletes_personal_role(self):
        self.doc["last_activity_at"] = self.now - timedelta(days=10, seconds=1)
        self.doc["inactivity_observed_at"] = self.now
        await self.system._check_inactive_common_vips_once()
        self.role.delete.assert_awaited_once()
        self.assertEqual(self.doc["disabled_reason"], "owner_inactive_10_days")

    async def test_manually_linked_personal_role_also_expires_after_ten_days(self):
        self.doc["role_source"] = "command:/vincular_vip"
        self.doc["last_activity_at"] = self.now - timedelta(days=10, seconds=1)
        self.doc["inactivity_observed_at"] = self.now
        await self.system._check_inactive_common_vips_once()
        self.role.delete.assert_awaited_once()

    async def test_manually_linked_owner_activity_warms_cache(self):
        self.doc["role_source"] = "command:/vincular_vip"
        self.system._common_vip_owners.clear()
        self.system._common_vip_cache_loaded = False
        await self.system.on_message(SimpleNamespace(guild=self.guild, author=self.member))
        self.assertEqual(self.system._common_vip_owners[(1, 2)], self.doc["_id"])
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)

    async def test_voice_exit_records_activity(self):
        await self.system.on_voice_state_update(
            self.member, SimpleNamespace(channel=object()), SimpleNamespace(channel=None)
        )
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)

    async def test_afk_channel_does_not_reset_activity(self):
        self.guild.afk_channel = object()
        previous_activity = self.doc["last_activity_at"]
        await self.system.on_voice_state_update(
            self.member, SimpleNamespace(channel=None), SimpleNamespace(channel=self.guild.afk_channel)
        )
        self.assertEqual(self.doc["last_activity_at"], previous_activity)

    async def test_commands_buttons_and_modal_submissions_reset_activity(self):
        for kind in (discord.InteractionType.application_command, discord.InteractionType.component,
                     discord.InteractionType.modal_submit):
            with self.subTest(kind=kind):
                self.system._common_vip_activity_written.clear()
                self.doc["last_activity_at"] = self.now - timedelta(days=9)
                await self.system.on_interaction(SimpleNamespace(type=kind, guild=self.guild, user=self.member))
                self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)

    async def test_autocomplete_does_not_count_as_activity(self):
        previous_activity = self.doc["last_activity_at"]
        await self.system.on_interaction(SimpleNamespace(
            type=discord.InteractionType.autocomplete, guild=self.guild, user=self.member
        ))
        self.assertEqual(self.doc["last_activity_at"], previous_activity)

    async def test_reaction_on_uncached_message_resets_activity(self):
        self.system.bot.get_guild = lambda _gid: self.guild
        await self.system.on_raw_reaction_add(SimpleNamespace(guild_id=1, member=self.member, user_id=2))
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)

    async def test_direct_messages_and_bots_do_not_reset_activity(self):
        previous_activity = self.doc["last_activity_at"]
        await self.system.on_message(SimpleNamespace(guild=None, author=self.member))
        self.member.bot = True
        await self.system.on_message(SimpleNamespace(guild=self.guild, author=self.member))
        self.assertEqual(self.doc["last_activity_at"], previous_activity)

    async def test_long_monitoring_gap_starts_new_window(self):
        self.doc["inactivity_observed_at"] = self.now - timedelta(hours=1)
        await self.system._check_inactive_common_vips_once()
        self.role.delete.assert_not_awaited()
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)

    async def test_old_activity_policy_starts_new_ten_day_window(self):
        self.doc.pop("inactivity_policy")
        self.doc["inactivity_observed_at"] = self.now
        await self.system._check_inactive_common_vips_once()
        self.role.delete.assert_not_awaited()
        self.assertEqual(self.doc["inactivity_policy"], vip_module.VIP_INACTIVITY_POLICY)
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)

    async def test_ongoing_call_prevents_inactivity_deletion(self):
        self.doc["inactivity_observed_at"] = self.now
        self.member.voice = SimpleNamespace(channel=object())
        await self.system._check_inactive_common_vips_once()
        self.role.delete.assert_not_awaited()
        self.assertLess((datetime.now(timezone.utc) - self.doc["last_activity_at"]).total_seconds(), 5)

    def configure_monarch_highlight(self):
        self.highlight = SimpleNamespace(id=4, name="Destaque Monarch", managed=False, delete=AsyncMock())
        self.doc["highlight_id"] = "4"
        self.doc["highlight_active"] = True
        self.doc["highlight_last_activity_at"] = self.now - timedelta(days=11)
        self.doc["highlight_inactivity_policy"] = vip_module.VIP_INACTIVITY_POLICY
        self.member.roles = [SimpleNamespace(id=vip_module.MONARCH_VIP_ID)]
        self.member.voice = None
        self.guild.get_role = lambda rid: self.highlight if rid == 4 else self.role if rid == 3 else None
        self.system._monarch_highlight_owners[(1, 2)] = self.doc["_id"]

    async def test_monarch_highlight_deleted_after_10_days_without_touching_base_role(self):
        self.configure_monarch_highlight()
        await self.system._delete_inactive_monarch_highlight(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.highlight.delete.assert_awaited_once()
        self.role.delete.assert_not_awaited()
        self.assertNotIn("highlight_id", self.doc)
        self.assertEqual(self.doc["highlight_disabled_reason"], "owner_inactive_10_days")
        vip_module.send_admin_audit_dm.assert_awaited_once()
        self.assertEqual(vip_module.send_admin_audit_dm.call_args.kwargs["details"]["Tipo"], "destaque")

    async def test_recent_monarch_activity_preserves_highlight(self):
        self.configure_monarch_highlight()
        self.doc["highlight_last_activity_at"] = self.now - timedelta(days=1)
        await self.system._delete_inactive_monarch_highlight(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.highlight.delete.assert_not_awaited()
        self.assertEqual(self.doc["highlight_id"], "4")

    async def test_ten_days_without_activity_deletes_monarch_highlight(self):
        self.configure_monarch_highlight()
        self.doc["highlight_last_activity_at"] = self.now - timedelta(days=10, seconds=1)
        self.doc["highlight_inactivity_observed_at"] = self.now
        await self.system._check_inactive_monarch_highlights_once()
        self.highlight.delete.assert_awaited_once()
        self.role.delete.assert_not_awaited()
        self.assertEqual(self.doc["highlight_disabled_reason"], "owner_inactive_10_days")

    async def test_reaction_updates_common_and_monarch_activity(self):
        self.configure_monarch_highlight()
        self.system.bot.get_guild = lambda _gid: self.guild
        await self.system.on_raw_reaction_add(SimpleNamespace(guild_id=1, member=self.member, user_id=2))
        for field in ("last_activity_at", "highlight_last_activity_at"):
            self.assertLess((datetime.now(timezone.utc) - self.doc[field]).total_seconds(), 5)

    async def test_old_highlight_policy_starts_new_ten_day_window(self):
        self.configure_monarch_highlight()
        self.doc.pop("highlight_inactivity_policy")
        self.doc["highlight_inactivity_observed_at"] = self.now
        await self.system._check_inactive_monarch_highlights_once()
        self.highlight.delete.assert_not_awaited()
        self.assertEqual(self.doc["highlight_inactivity_policy"], vip_module.VIP_INACTIVITY_POLICY)
        self.assertLess((datetime.now(timezone.utc) - self.doc["highlight_last_activity_at"]).total_seconds(), 5)

    async def test_highlight_delete_failure_preserves_link_for_retry(self):
        self.configure_monarch_highlight()
        response = SimpleNamespace(status=403, reason="Forbidden", text="Forbidden")
        self.highlight.delete.side_effect = discord.Forbidden(response, "Forbidden")
        await self.system._delete_inactive_monarch_highlight(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.assertEqual(self.doc["highlight_id"], "4")
        self.assertTrue(self.doc["highlight_review_required"])
        self.assertEqual(self.doc["highlight_cleanup_reason"], "highlight_delete_failed")

    async def test_entitlement_deactivation_failure_preserves_highlight_link(self):
        self.configure_monarch_highlight()
        response = SimpleNamespace(status=403, reason="Forbidden", text="Forbidden")
        self.highlight.delete.side_effect = discord.Forbidden(response, "Forbidden")
        await self.system._deactivate_monarch_highlight_role(self.member, self.highlight, "monarch_expired_or_missing", "test")
        self.assertEqual(self.doc["highlight_id"], "4")
        self.assertEqual(self.doc["highlight_delete_reason"], "monarch_expired_or_missing")

    async def test_existing_highlight_starts_new_10_day_window(self):
        self.configure_monarch_highlight()
        self.doc["highlight_last_activity_at"] = self.now - timedelta(days=40)
        self.system._delete_inactive_monarch_highlight = AsyncMock()
        await self.system._check_inactive_monarch_highlights_once()
        self.system._delete_inactive_monarch_highlight.assert_not_awaited()
        self.assertLess((datetime.now(timezone.utc) - self.doc["highlight_last_activity_at"]).total_seconds(), 5)

    async def test_highlight_only_owner_activity_is_recorded(self):
        self.configure_monarch_highlight()
        self.system._common_vip_owners.clear()
        await self.system.on_message(SimpleNamespace(guild=self.guild, author=self.member))
        self.assertLess((datetime.now(timezone.utc) - self.doc["highlight_last_activity_at"]).total_seconds(), 5)

    async def test_short_monarch_voice_session_is_recorded(self):
        self.configure_monarch_highlight()
        self.system._common_vip_owners.clear()
        await self.system.on_voice_state_update(
            self.member, SimpleNamespace(channel=None), SimpleNamespace(channel=object())
        )
        self.assertLess((datetime.now(timezone.utc) - self.doc["highlight_last_activity_at"]).total_seconds(), 5)

    async def test_highlight_failed_deletion_is_retried_after_backoff(self):
        self.configure_monarch_highlight()
        self.doc["highlight_inactivity_observed_at"] = self.now
        self.doc["highlight_cleanup_reason"] = "highlight_delete_failed"
        self.doc["highlight_retry_after"] = self.now - timedelta(minutes=1)
        self.system._delete_inactive_monarch_highlight = AsyncMock()
        await self.system._check_inactive_monarch_highlights_once()
        self.system._delete_inactive_monarch_highlight.assert_awaited_once()

    async def test_entitlement_deactivation_removes_highlight_after_success(self):
        self.configure_monarch_highlight()
        await self.system._deactivate_monarch_highlight_role(self.member, self.highlight, "monarch_expired_or_missing", "test")
        self.highlight.delete.assert_awaited_once()
        self.assertNotIn("highlight_id", self.doc)
        self.assertFalse(self.doc["highlight_active"])

    async def test_former_monarch_in_voice_still_enters_cleanup(self):
        self.configure_monarch_highlight()
        self.member.roles = []
        self.member.voice = SimpleNamespace(channel=object())
        self.doc["highlight_inactivity_observed_at"] = self.now
        self.system._delete_inactive_monarch_highlight = AsyncMock()
        await self.system._check_inactive_monarch_highlights_once()
        self.system._delete_inactive_monarch_highlight.assert_awaited_once()

    async def test_absent_common_owner_does_not_leave_role_behind(self):
        self.doc["status"] = "needs_review"
        self.doc["cleanup_reason"] = "member_not_found"
        self.guild.get_member = lambda _uid: None
        response = SimpleNamespace(status=404, reason="Not Found", text="Not Found")
        self.guild.fetch_member = AsyncMock(side_effect=discord.NotFound(response, "Not Found"))
        await self.system._delete_inactive_common_vip(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.role.delete.assert_awaited_once()
        self.assertNotIn("role_id", self.doc)

    async def test_absent_monarch_owner_does_not_leave_highlight_behind(self):
        self.configure_monarch_highlight()
        self.guild.get_member = lambda _uid: None
        response = SimpleNamespace(status=404, reason="Not Found", text="Not Found")
        self.guild.fetch_member = AsyncMock(side_effect=discord.NotFound(response, "Not Found"))
        await self.system._delete_inactive_monarch_highlight(self.guild, 2, self.doc["_id"], self.now - timedelta(days=10))
        self.highlight.delete.assert_awaited_once()
        self.assertNotIn("highlight_id", self.doc)

    async def test_startup_message_warms_highlight_cache(self):
        self.configure_monarch_highlight()
        self.system._monarch_highlight_owners.clear()
        self.system._monarch_highlight_cache_loaded = False
        await self.system.on_message(SimpleNamespace(guild=self.guild, author=self.member))
        self.assertEqual(self.system._monarch_highlight_owners[(1, 2)], self.doc["_id"])
        self.assertLess((datetime.now(timezone.utc) - self.doc["highlight_last_activity_at"]).total_seconds(), 5)

    def configure_departed_owner(self):
        self.guild.get_member = lambda _uid: None
        self.guild.members = []
        response = SimpleNamespace(status=404, reason="Not Found", text="Not Found")
        self.guild.fetch_member = AsyncMock(side_effect=discord.NotFound(response, "Not Found"))
        self.guild.fetch_roles = AsyncMock(return_value=[])
        self.system.bot.get_guild = lambda gid: self.guild if gid == 1 else None
        self.temp_collection = SimpleNamespace(delete_many=lambda *_args: None)
        temporary_roles = patch.object(vip_module, "temp_col", self.temp_collection)
        temporary_roles.start()
        self.addCleanup(temporary_roles.stop)

    async def test_departure_deletes_recent_common_role_immediately(self):
        self.configure_departed_owner()
        self.doc["last_activity_at"] = self.now
        with self.assertLogs(vip_module.log, level="INFO") as logs:
            await self.system.on_raw_member_remove(SimpleNamespace(guild_id=1, user=SimpleNamespace(id=2)))
        self.role.delete.assert_awaited_once()
        self.assertEqual(self.doc["status"], "inactive")
        self.assertFalse(self.doc["entitlement_active"])
        self.assertNotIn("role_id", self.doc)
        event = json.loads(logs.records[0].getMessage())
        self.assertEqual(event["event"], "vip_departure_role_deleted")
        self.assertEqual((event["guild_id"], event["user_id"]), (1, 2))
        self.assertTrue(event["cleanup_id"])

    async def test_departure_deletes_linked_role_and_monarch_highlight(self):
        self.configure_departed_owner()
        self.configure_monarch_highlight()
        self.doc["role_source"] = "command:/vincular_vip"
        await self.system._cleanup_absent_vip_owner(self.guild, 2, "test")
        self.role.delete.assert_awaited_once()
        self.highlight.delete.assert_awaited_once()
        self.assertNotIn("role_id", self.doc)
        self.assertNotIn("highlight_id", self.doc)
        self.assertFalse(self.doc["highlight_active"])
        self.assertEqual(self.doc["status"], "inactive")
        self.assertEqual(vip_module.send_admin_audit_dm.await_count, 2)

    async def test_departure_preserves_link_on_discord_failure_then_reconciles(self):
        self.configure_departed_owner()
        response = SimpleNamespace(status=403, reason="Forbidden", text="Forbidden")
        self.role.delete.side_effect = discord.Forbidden(response, "Forbidden")
        with self.assertLogs(vip_module.log, level="WARNING") as logs:
            result = await self.system._cleanup_absent_vip_owner(self.guild, 2, "test")
        self.assertFalse(result)
        self.assertEqual(self.doc["role_id"], "3")
        self.assertEqual(self.doc["status"], "needs_review")
        self.assertTrue(any("vip_departure_role_delete_failed" in line for line in logs.output))
        self.role.delete.side_effect = None
        self.doc["departure_retry_after"] = self.now - timedelta(seconds=1)
        with patch.object(vip_module, "RECONCILE_ABSENT_VIP_DELAY_SECONDS", 0):
            await self.system.reconcile_absent_vips.coro(self.system)
        self.assertEqual(self.role.delete.await_count, 2)
        self.assertNotIn("role_id", self.doc)
        self.assertEqual(self.doc["status"], "inactive")

    async def test_departure_reconciles_old_review_and_inactive_records(self):
        self.configure_departed_owner()
        for status in ("needs_review", "inactive"):
            with self.subTest(status=status):
                self.doc.update(status=status, role_id="3", review_required=True,
                                missing_member=True, cleanup_reason="member_not_found")
                self.role.delete.reset_mock()
                with patch.object(vip_module, "RECONCILE_ABSENT_VIP_DELAY_SECONDS", 0):
                    await self.system.reconcile_absent_vips.coro(self.system)
                self.role.delete.assert_awaited_once()
                self.assertNotIn("role_id", self.doc)

    async def test_departure_reconciler_waits_before_retrying_failure(self):
        self.configure_departed_owner()
        self.doc["departure_retry_after"] = self.now + timedelta(hours=1)
        await self.system.reconcile_absent_vips.coro(self.system)
        self.guild.fetch_member.assert_not_awaited()
        self.role.delete.assert_not_awaited()

    async def test_departure_preserves_general_managed_and_default_roles(self):
        self.configure_departed_owner()
        for role_id, managed in ((vip_module.MONARCH_VIP_ID, False), (3, True), (self.guild.id, False)):
            with self.subTest(role_id=role_id, managed=managed):
                self.role.id = role_id
                self.role.managed = managed
                self.doc["role_id"] = str(role_id)
                self.guild.get_role = lambda _rid: self.role
                self.assertFalse(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
                self.role.delete.assert_not_awaited()
                self.assertEqual(self.doc["role_id"], str(role_id))

    async def test_departure_preserves_roles_linked_to_another_owner(self):
        self.configure_departed_owner()
        original_find_one = self.collection.find_one

        def find_one(query):
            if isinstance(query.get("_id"), dict):
                return {"_id": "1:99", "role_id": "3"}
            return original_find_one(query)

        self.collection.find_one = find_one
        self.assertFalse(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
        self.role.delete.assert_not_awaited()
        self.assertEqual(self.doc["role_id"], "3")

    async def test_departure_skips_member_who_has_returned(self):
        self.configure_departed_owner()
        self.guild.fetch_member = AsyncMock(return_value=self.member)
        self.assertFalse(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
        self.role.delete.assert_not_awaited()

    async def test_departure_skips_when_absence_cannot_be_confirmed(self):
        self.configure_departed_owner()
        response = SimpleNamespace(status=403, reason="Forbidden", text="Forbidden")
        self.guild.fetch_member = AsyncMock(side_effect=discord.Forbidden(response, "Forbidden"))
        self.assertFalse(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
        self.role.delete.assert_not_awaited()

    async def test_departure_skips_offline_database(self):
        self.configure_departed_owner()
        with patch.object(vip_module, "is_db_online", return_value=False):
            self.assertFalse(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
        self.role.delete.assert_not_awaited()

    async def test_departure_fetches_role_missing_from_cache(self):
        self.configure_departed_owner()
        self.guild.get_role = lambda _rid: None
        self.guild.fetch_roles.return_value = [self.role]
        await self.system._cleanup_absent_vip_owner(self.guild, 2, "test")
        self.role.delete.assert_awaited_once()
        self.assertNotIn("role_id", self.doc)

    async def test_departure_keeps_link_when_role_lookup_fails(self):
        self.configure_departed_owner()
        self.guild.get_role = lambda _rid: None
        response = SimpleNamespace(status=503, reason="Unavailable", text="Unavailable")
        self.guild.fetch_roles.side_effect = discord.HTTPException(response, "Unavailable")
        self.assertFalse(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
        self.role.delete.assert_not_awaited()
        self.assertEqual(self.doc["role_id"], "3")

    async def test_departure_preserves_role_above_bot_hierarchy(self):
        self.configure_departed_owner()
        with patch.object(vip_module, "bot_can_manage_role", return_value=False):
            self.assertFalse(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
        self.role.delete.assert_not_awaited()

    async def test_departure_confirms_missing_role_before_clearing_link(self):
        self.configure_departed_owner()
        self.guild.get_role = lambda _rid: None
        self.assertTrue(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
        self.guild.fetch_roles.assert_awaited_once()
        self.assertNotIn("role_id", self.doc)

    async def test_departure_clears_link_when_role_already_deleted(self):
        self.configure_departed_owner()
        response = SimpleNamespace(status=404, reason="Not Found", text="Not Found")
        self.role.delete.side_effect = discord.NotFound(response, "Not Found")
        await self.system._cleanup_absent_vip_owner(self.guild, 2, "test")
        self.assertNotIn("role_id", self.doc)
        self.assertEqual(self.doc["status"], "inactive")

    async def test_departure_repeated_event_does_not_delete_role_twice(self):
        self.configure_departed_owner()
        payload = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=2))
        await self.system.on_raw_member_remove(payload)
        await self.system.on_raw_member_remove(payload)
        self.role.delete.assert_awaited_once()
        vip_module.send_admin_audit_dm.assert_awaited_once()

    async def test_departure_keeps_link_if_database_does_not_save_after_deletion(self):
        self.configure_departed_owner()
        self.system._update_vip_role_with_snapshot.side_effect = None
        with self.assertLogs(vip_module.log, level="ERROR"):
            self.assertFalse(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
        self.role.delete.assert_awaited_once()
        self.assertEqual(self.doc["role_id"], "3")

    async def test_departure_keeps_failed_highlight_for_next_attempt(self):
        self.configure_departed_owner()
        self.configure_monarch_highlight()
        response = SimpleNamespace(status=403, reason="Forbidden", text="Forbidden")
        self.highlight.delete.side_effect = discord.Forbidden(response, "Forbidden")
        self.assertFalse(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
        self.assertNotIn("role_id", self.doc)
        self.assertEqual(self.doc["highlight_id"], "4")
        self.assertEqual(self.doc["status"], "needs_review")
        self.highlight.delete.side_effect = None
        self.assertTrue(await self.system._cleanup_absent_vip_owner(self.guild, 2, "reconciler"))
        self.assertNotIn("highlight_id", self.doc)
        self.role.delete.assert_awaited_once()

    async def test_departure_preserves_record_from_another_server(self):
        self.configure_departed_owner()
        self.doc["guild_id"] = "99"
        self.assertFalse(await self.system._cleanup_absent_vip_owner(self.guild, 2, "test"))
        self.role.delete.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
