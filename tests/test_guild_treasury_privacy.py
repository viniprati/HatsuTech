import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["MONGO_URI"] = ""

from database import TransactionUnavailable
from cogs.guilda import finance
from cogs.guilda.cog import GuildSystem
from cogs.guilda.commands import guilda_cofre_command as treasury
from cogs.guilda.commands import painel_command as panel


class TreasuryPrivacyTests(unittest.IsolatedAsyncioTestCase):
    def interaction(self):
        return SimpleNamespace(
            user=SimpleNamespace(id=42), guild=SimpleNamespace(id=finance.MAIN_GUILD_ID),
            response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=lambda: False),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    async def test_treasury_is_private_and_queries_only_requesting_members_guild(self):
        it = self.interaction()
        document = {"name": "Equipe", "treasury_eter": 12345,
                    "members": [{"user_id": 42, "treasury_contributed": 123},
                                {"user_id": 99, "treasury_contributed": 900}]}
        with patch.object(finance, "read_current_guild", return_value=document) as read:
            await treasury.execute(None, it)
        read.assert_called_once_with(it.guild.id, it.user.id)
        self.assertTrue(it.response.defer.call_args.kwargs["ephemeral"])
        payload = it.followup.send.call_args.kwargs
        self.assertTrue(payload["ephemeral"])
        self.assertIn("12.345", payload["embed"].description)
        self.assertEqual(payload["embed"].fields[0].value, "123 Éteres")
        self.assertFalse(payload["allowed_mentions"].everyone)
        self.assertFalse(payload["allowed_mentions"].users)

    async def test_non_member_receives_only_private_error(self):
        it = self.interaction()
        with patch.object(finance, "read_current_guild", side_effect=finance.GuildFinanceError("Você não está em uma guilda.")):
            await treasury.execute(None, it)
        payload = it.followup.send.call_args.kwargs
        self.assertTrue(payload["ephemeral"])
        self.assertNotIn("embed", payload)

    async def test_database_failure_does_not_fabricate_zero_balance(self):
        it = self.interaction()
        with patch.object(finance, "read_current_guild", side_effect=TransactionUnavailable("Banco indisponível.")):
            await treasury.execute(None, it)
        self.assertTrue(it.followup.send.call_args.kwargs["ephemeral"])
        self.assertNotIn("embed", it.followup.send.call_args.kwargs)

    async def test_dm_is_rejected_privately_without_reading_financial_data(self):
        it = self.interaction()
        it.guild = None
        with patch.object(finance, "read_current_guild") as read:
            await treasury.execute(None, it)
        read.assert_not_called()
        self.assertTrue(it.response.send_message.call_args.kwargs["ephemeral"])

    async def test_command_has_no_arbitrary_user_or_guild_selector(self):
        self.assertEqual(GuildSystem.guilda_cofre.name, "guilda_cofre")
        self.assertEqual(GuildSystem.guilda_cofre.parameters, [])
        self.assertTrue(GuildSystem.guilda_cofre.guild_only)

    async def test_public_panel_cannot_expose_treasury_or_financial_contributions(self):
        it = self.interaction()
        member = SimpleNamespace(id=42, mention="<@42>")
        record = {"user_id": 42, "xp": 111, "msg_count": 15, "treasury_contributed": 7654321}
        document = {"_id": "team", "name": "Equipe", "emoji": "🛡️", "leader_id": 42,
                    "treasury_eter": 9876543, "members": [record]}
        runtime = {**document, "_active_records": [(record, member)], "_active_member_count": 1,
                   "_leader_text": "<@42>"}
        system = GuildSystem.__new__(GuildSystem)
        system.get_user_guild = MagicMock(return_value=document)
        system.build_guild_runtime_view = AsyncMock(return_value=runtime)
        with patch.object(panel.guilds_col, "find", return_value=[document]):
            await panel.execute(system, it)
        embed = it.followup.send.call_args.kwargs["embed"]
        self.assertNotIn("Éteres", embed.description)
        self.assertNotIn("9876543", embed.description.replace(".", "").replace(",", ""))
        self.assertNotIn("7654321", embed.description.replace(".", "").replace(",", ""))
        self.assertIn("111 XP", embed.description)
        self.assertIn("/guilda_cofre", embed.footer.text)
