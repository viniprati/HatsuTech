import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

os.environ["MONGO_URI"] = ""

import admin_audit


class AdminAuditDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.recipients = {
            uid: SimpleNamespace(id=uid, send=AsyncMock())
            for uid in (983870132063453235, 459064218088374293)
        }
        self.collection = SimpleNamespace(
            insert_one=MagicMock(return_value=SimpleNamespace(acknowledged=True)),
            update_one=MagicMock(return_value=SimpleNamespace(acknowledged=True)),
        )
        self.bot = SimpleNamespace(get_user=self.recipients.get, fetch_user=AsyncMock())

    async def send(self):
        with patch.object(admin_audit, "ADMIN_AUDIT_DM_USER_IDS", tuple(self.recipients)), \
             patch.object(admin_audit, "admin_audit_logs_col", self.collection):
            return await admin_audit.send_admin_audit_dm(
                self.bot, category="vip", action="Cargo VIP excluído",
                guild=SimpleNamespace(id=1, name="Servidor"), actor=None, target_id=42,
                reason="Dono ausente", details={"Cargo": "VIP pessoal (3)"}, source="test:deletion",
            )

    async def test_reports_reach_both_configured_users_without_mentions(self):
        result = await self.send()
        self.assertEqual(result["sent"], 2)
        self.assertEqual(result["failed"], 0)
        for user in self.recipients.values():
            user.send.assert_awaited_once()
            payload = user.send.call_args.kwargs
            self.assertFalse(payload["allowed_mentions"].everyone)
            self.assertFalse(payload["allowed_mentions"].users)
        doc = self.collection.insert_one.call_args.args[0]
        self.assertEqual(set(doc["recipient_ids"]), {str(uid) for uid in self.recipients})
        self.assertEqual(doc["target_id"], "42")

    async def test_one_closed_dm_does_not_prevent_other_delivery(self):
        response = SimpleNamespace(status=403, reason="Forbidden")
        self.recipients[983870132063453235].send.side_effect = discord.Forbidden(response, "DM fechada")
        result = await self.send()
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(result["sent"], 1)
        self.recipients[983870132063453235].send.assert_awaited_once()
        self.recipients[459064218088374293].send.assert_awaited_once()
        recorded = [call.args[1]["$set"] for call in self.collection.update_one.call_args_list]
        self.assertTrue(any(value.get("deliveries.983870132063453235", {}).get("status") == "blocked" for value in recorded))


if __name__ == "__main__":
    unittest.main()
