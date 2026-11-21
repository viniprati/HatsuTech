import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["MONGO_URI"] = ""

import discord
from cogs.guilda import membership
from cogs.guilda.cog import GuildSystem


class DepartureTests(unittest.TestCase):
    def setUp(self):
        self.document = {"_id": "team", "leader_id": 1, "members": [
            {"user_id": "1"}, {"user_id": 2, "joined_at": datetime(2025, 1, 1, tzinfo=timezone.utc)},
            {"user_id": 3, "joined_at": datetime(2025, 2, 1, tzinfo=timezone.utc)},
        ]}
        self.collection = MagicMock()
        self.collection.find_one.return_value = self.document
        for name, value in (("guilds_col", self.collection), ("run_transaction", lambda work: work("session"))):
            patcher = patch.object(membership, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_leader_transfers_to_oldest_confirmed_member_and_keeps_collective_data(self):
        self.assertEqual(membership.remove_departed(self.document, {1}, {2, 3}), 1)
        query, update = self.collection.update_one.call_args.args
        self.assertIn("$or", query)
        self.assertEqual(update, {"$set": {"leader_id": 2}, "$pull": {"members": {"user_id": {"$in": ["1"]}}}})

    def test_waits_when_no_successor_is_confirmed(self):
        self.assertEqual(membership.remove_departed(self.document, {1}, set()), 0)
        self.collection.update_one.assert_not_called()

    def test_empty_guild_is_preserved_without_a_leader(self):
        self.assertEqual(membership.remove_departed(self.document, {1, 2, 3}, set()), 3)
        self.assertIsNone(self.collection.update_one.call_args.args[1]["$set"]["leader_id"])
        self.collection.delete_one.assert_not_called()

    def test_old_check_does_not_remove_a_member_with_a_new_registration(self):
        self.collection.find_one.return_value = {**self.document, "members": [
            {"user_id": "1", "joined_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}, *self.document["members"][1:],
        ]}
        self.assertEqual(membership.remove_departed(self.document, {1}, {2, 3}), 0)
        self.collection.update_one.assert_not_called()


class DiscordDepartureTests(unittest.IsolatedAsyncioTestCase):
    async def reconcile(self, error):
        cog = GuildSystem.__new__(GuildSystem)
        guild = SimpleNamespace(get_member=lambda uid: None, fetch_member=AsyncMock(side_effect=error))
        document = {"_id": "team", "leader_id": 2, "members": [{"user_id": 1}, {"user_id": 2}]}
        with patch.object(membership, "read_memberships", return_value=[document]), \
             patch.object(membership, "remove_departed", return_value=1) as remove:
            await cog._reconcile_memberships(guild, 1)
        return remove, document

    async def test_only_unknown_member_response_confirms_departure(self):
        response = SimpleNamespace(status=404, reason="Not Found")
        remove, document = await self.reconcile(discord.NotFound(response, {"code": 10007, "message": "Unknown Member"}))
        remove.assert_called_once_with(document, {1}, set())
        remove, _ = await self.reconcile(discord.NotFound(response, {"code": 10004, "message": "Unknown Guild"}))
        remove.assert_not_called()

    async def test_forbidden_does_not_remove_members(self):
        remove, _ = await self.reconcile(discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Forbidden"))
        remove.assert_not_called()
