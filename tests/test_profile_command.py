import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

os.environ["MONGO_URI"] = ""

from cogs.engagement.commands import perfil_command as command
from cogs.engagement.cog import Engagement
from cogs.engagement import profile_renderer


class ProfileCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.user = MagicMock(spec=discord.Member)
        self.user.id, self.user.bot, self.user.name, self.user.display_name = 42, False, "pessoa", "Pessoa"
        self.user.roles = []
        self.user.joined_at = self.user.premium_since = self.user.primary_guild = None
        self.guild = SimpleNamespace(id=command.member_facts.__globals__["MAIN_GUILD_ID"], name="Animes Café")
        self.user.guild = self.guild
        asset = MagicMock()
        asset.read = AsyncMock(return_value=b"avatar")
        self.user.display_avatar.with_size.return_value.with_static_format.return_value = asset
        self.it = SimpleNamespace(user=self.user, guild=self.guild, guild_id=self.guild.id,
            response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock()),
            edit_original_response=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))
        self.profile = {"achievements": [], "data_available": True, "persistence_available": True}
        self.cog = SimpleNamespace(profile_render_slots=asyncio.Semaphore(2), profiles=SimpleNamespace(
            read_profile=MagicMock(return_value=self.profile.copy()), save_settings=MagicMock(return_value=True)))
        p = patch.object(profile_renderer, "render_profile", return_value=b"png")
        self.render = p.start()
        self.addCleanup(p.stop)

    async def test_private_default_and_explicit_public_opt_in(self):
        await command.execute(self.cog, self.it)
        self.it.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
        payload = self.it.edit_original_response.call_args.kwargs
        self.assertEqual(payload["attachments"][0].filename, "perfil-animes-cafe.png")
        self.assertFalse(payload["allowed_mentions"].everyone)
        self.assertEqual(self.cog.profiles.read_profile.call_args.args[0]["user_id"], "42")
        self.it.response.defer.reset_mock()
        await command.execute(self.cog, self.it, publico=True)
        self.it.response.defer.assert_awaited_once_with(ephemeral=False, thinking=True)

    async def test_dm_foreign_guild_and_bot_rejected_before_database(self):
        for guild, bot in ((None, False), (SimpleNamespace(id=1), False), (self.guild, True)):
            with self.subTest(guild=guild):
                self.it.guild, self.user.bot = guild, bot
                await command.execute(self.cog, self.it)
        self.cog.profiles.read_profile.assert_not_called()
        self.it.response.defer.assert_not_awaited()

    async def test_busy_renderer_and_invalid_settings_do_no_work(self):
        await command.execute(self.cog, self.it, sobre="x"*101)
        await command.execute(self.cog, self.it, tema="../../private")
        self.cog.profile_render_slots = asyncio.Semaphore(0)
        await command.execute(self.cog, self.it)
        self.cog.profiles.read_profile.assert_not_called()
        self.render.assert_not_called()

    async def test_settings_are_saved_for_author_and_normalized(self):
        await command.execute(self.cog, self.it, tema="sakura", sobre=" Olá\x00 ")
        self.cog.profiles.save_settings.assert_called_once_with(self.guild.id, 42, {"bio": "Olá", "theme": "sakura"})
        self.assertEqual(self.render.call_args.args[0]["theme"], "sakura")

    async def test_failed_settings_write_never_claims_success(self):
        self.cog.profiles.save_settings.return_value = False
        await command.execute(self.cog, self.it, tema="sakura")
        self.render.assert_not_called()
        self.assertIn("Não consegui salvar", self.it.edit_original_response.call_args.kwargs["content"])

    async def test_avatar_failure_uses_fallback_and_outage_is_visible(self):
        self.user.display_avatar.with_size.return_value.with_static_format.return_value.read.side_effect = asyncio.TimeoutError
        self.cog.profiles.read_profile.return_value["data_available"] = False
        await command.execute(self.cog, self.it)
        self.assertIsNone(self.render.call_args.args[1])
        self.assertIn("indisponíveis", self.it.edit_original_response.call_args.kwargs["content"])

    async def test_other_member_cannot_use_profile_buttons_or_select(self):
        self.it.user = SimpleNamespace(id=99)
        view = command.ProfileView(self.cog, 42, self.guild.id, self.profile)
        self.assertFalse(await view.interaction_check(self.it))
        selection = command.FeaturedSelect(self.cog, 42, self.guild.id,
                                          [{"id": "cafeinado", "name": "Cafeinado", "unlocked": True}])
        await selection.callback(self.it)
        self.cog.profiles.save_settings.assert_not_called()

    def test_registered_command_is_guild_only_and_has_cooldown(self):
        self.assertTrue(Engagement.perfil.guild_only)
        self.assertTrue(Engagement.perfil.checks)
        self.assertEqual([p.name for p in Engagement.perfil.parameters], ["tema", "sobre", "publico"])
