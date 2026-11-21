"""Opt-in financial tests against a disposable LOCAL MongoDB replica set.

HATSUTECH_TEST_MONGO_URI must point to loopback. A random test database is
created and dropped; the configured bot database and credentials are not used.
"""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import uuid4
from unittest.mock import patch

os.environ["MONGO_URI"] = ""

from bson import ObjectId
from pymongo import MongoClient
from pymongo.errors import OperationFailure

import database
from cogs.guilda import finance, membership
from cogs.guilda.cog import GuildSystem
from utils import get_brt_keys

TEST_URI = os.getenv("HATSUTECH_TEST_MONGO_URI", "")
if not TEST_URI and os.getenv("HATSUTECH_TEST_MONGO_PORT"):
    port = int(os.environ["HATSUTECH_TEST_MONGO_PORT"])
    if not 1 <= port <= 65535:
        raise ValueError("Invalid local MongoDB test port")
    TEST_URI = f"mongodb://127.0.0.1:{port}/?replicaSet=hatsutech-test"


@unittest.skipUnless(TEST_URI, "Requires an explicit local MongoDB replica set")
class GuildFinanceIntegrationTests(unittest.TestCase):
    def test_departure_transfers_leadership_and_preserves_xp_and_treasury(self):
        doc = self.team([{"user_id": "1"}, {"user_id": 2, "joined_at": self.now}], balance=123)
        snapshots = membership.read_memberships(1)
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(membership.remove_departed(snapshots[0], {1}, {2}), 1)
        updated = self.db.guilds.find_one({"_id": doc["_id"]})
        self.assertEqual(updated["leader_id"], 2)
        self.assertEqual([record["user_id"] for record in updated["members"]], [2])
        self.assertEqual(updated["total_xp"], doc["total_xp"])
        self.assertEqual(updated["treasury_eter"], 123)
        self.assertEqual(membership.remove_departed(snapshots[0], {1}, {2}), 0)

    @classmethod
    def setUpClass(cls):
        if urlparse(TEST_URI).hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError("Financial integration tests only accept loopback MongoDB")
        cls.client = MongoClient(TEST_URI, serverSelectionTimeoutMS=3000)
        cls.client.admin.command("ping")
        cls.name = "hatsutech_guild_tests_" + uuid4().hex

    @classmethod
    def tearDownClass(cls):
        cls.client.drop_database(cls.name)
        cls.client.close()

    def setUp(self):
        self.client.drop_database(self.name)
        self.db = self.client[self.name]
        self.patches = [patch.object(database, "MONGO_DB_NAME", self.name),
                        patch.object(database, "client", self.client), patch.object(database, "db", self.db),
                        patch.object(database, "_db_online", True)]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.server = finance.MAIN_GUILD_ID
        self.cog = GuildSystem.__new__(GuildSystem)
        self.now = datetime.now(timezone.utc)

    def user(self, uid=1, **balances):
        self.db.eco_users.insert_one({"_id": finance.economy_id(self.server, uid), **balances})

    def team(self, members=None, balance=0, monthly_xp=100_000):
        members = members or [{"user_id": 1, "joined_at": self.now - timedelta(days=8)}]
        doc = {"_id": ObjectId(), "name": "Equipe", "emoji": "🛡️", "leader_id": 1,
               "members": members, "total_xp": monthly_xp, "treasury_eter": balance,
               "stats_monthly": {"key": get_brt_keys()["month"], "message_xp": monthly_xp, "voice_xp": 0}}
        self.db.guilds.insert_one(doc)
        return doc

    def distribute(self, doc, operation_id="distribute:1", actor=1, present=None):
        return finance.distribute(self.server, doc["_id"], actor, doc["members"],
                                  set(finance.member_ids(doc)) if present is None else present,
                                  operation_id, now=self.now)

    def test_creation_charges_exact_fee_once_and_preserves_existing_balance(self):
        self.user(essencia=5000, eter=20)
        gid = finance.create_guild(self.server, 1, "Nova", "🛡️", "create:1")
        self.assertEqual(finance.create_guild(self.server, 1, "Nova", "🛡️", "create:1"), gid)
        self.assertEqual(self.db.eco_users.find_one()["essencia"], 1000)
        self.assertEqual(self.db.eco_users.find_one()["eter"], 20)
        self.assertEqual(self.db.guilds.count_documents({}), 1)

    def test_insufficient_funds_create_nothing(self):
        self.user(essencia=3999)
        with self.assertRaises(finance.GuildFinanceError):
            finance.create_guild(self.server, 1, "Nova", "🛡️", "create:1")
        self.assertEqual(self.db.eco_users.find_one()["essencia"], 3999)
        self.assertEqual(self.db.guilds.count_documents({}), 0)

    def test_failed_creation_rolls_back_charge(self):
        self.user(essencia=5000)
        with patch.object(finance.guilds_col, "insert_one", side_effect=OperationFailure("injected failure")):
            with self.assertRaises(database.TransactionUnavailable):
                finance.create_guild(self.server, 1, "Nova", "🛡️", "create:1")
        self.assertEqual(self.db.eco_users.find_one()["essencia"], 5000)
        self.assertEqual(self.db.guilds.count_documents({}), 0)

    def test_same_member_cannot_create_two_guilds_concurrently(self):
        self.user(essencia=10000)
        def attempt(n):
            try:
                return finance.create_guild(self.server, 1, f"Nova{n}", "🛡️", f"create:{n}")
            except (finance.GuildFinanceError, database.TransactionUnavailable):
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, (1, 2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.db.eco_users.find_one()["essencia"], 6000)
        self.assertEqual(self.db.guilds.count_documents({}), 1)

    def test_bonus_goes_only_to_treasury_while_base_and_vip_remain_personal(self):
        doc = self.team()
        for n in range(20):
            finance.credit_activity(self.cog, self.server, 1, "message", 1, 15, f"message:{n}")
        user, team = self.db.eco_users.find_one(), self.db.guilds.find_one()
        self.assertEqual(user["eter"], 23)
        self.assertEqual(team["treasury_eter"], 5)
        self.assertEqual(team["members"][0]["xp"], 20)
        self.assertEqual(team["members"][0]["treasury_contributed"], 5)
        entries = finance.read_history(self.server, 1, doc["_id"])[1]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["amount"], 5)

    def test_concurrent_chat_and_voice_preserve_fractional_bonus_and_money(self):
        self.team()
        def reward(n):
            source = "voice" if n % 2 else "message"
            finance.credit_activity(self.cog, self.server, 1, source, 1, 15, f"{source}:{n}")
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(reward, range(40)))
        self.assertEqual(self.db.eco_users.find_one()["eter"], 46)
        doc = self.db.guilds.find_one()
        self.assertEqual(doc["treasury_eter"], 10)
        self.assertEqual(doc["members"][0]["xp"], 40)

    def test_duplicate_activity_receipt_cannot_repeat_credit(self):
        self.team()
        self.assertTrue(finance.credit_activity(self.cog, self.server, 1, "voice", 4, 0, "voice:1"))
        self.assertFalse(finance.credit_activity(self.cog, self.server, 1, "voice", 4, 0, "voice:1"))
        self.assertEqual(self.db.eco_users.find_one()["eter"], 4)
        self.assertEqual(self.db.guilds.find_one()["treasury_eter"], 1)

    def test_delayed_activity_replay_after_other_rewards_is_ignored(self):
        self.team()
        finance.credit_activity(self.cog, self.server, 1, "message", 4, 0, "message:1")
        finance.credit_activity(self.cog, self.server, 1, "message", 4, 0, "message:2")
        self.assertFalse(finance.credit_activity(self.cog, self.server, 1, "message", 4, 0, "message:1"))
        self.assertEqual(self.db.eco_users.find_one()["eter"], 8)
        self.assertEqual(self.db.guilds.find_one()["treasury_eter"], 2)

    def test_failed_deposit_rolls_back_personal_credit_and_xp(self):
        self.team()
        with patch.object(finance.guild_history_col, "update_one", side_effect=OperationFailure("injected failure")):
            with self.assertRaises(database.TransactionUnavailable):
                finance.credit_activity(self.cog, self.server, 1, "message", 4, 0, "message:1")
        self.assertEqual(self.db.eco_users.count_documents({}), 0)
        doc = self.db.guilds.find_one()
        self.assertEqual(doc["treasury_eter"], 0)
        self.assertEqual(doc["total_xp"], 100000)

    def test_distribution_is_equal_includes_leader_and_keeps_remainder(self):
        doc = self.team([{"user_id": uid, "joined_at": self.now - timedelta(days=8)} for uid in range(1, 11)], balance=10003)
        result = self.distribute(doc)
        self.assertEqual((result["share"], result["remainder"]), (1000, 3))
        self.assertIn("1", result["recipients"])
        self.assertEqual(sum(user["eter"] for user in self.db.eco_users.find()), 10000)
        self.assertEqual(self.db.guilds.find_one()["treasury_eter"], 3)

    def test_seven_day_boundary_unknown_dates_and_absent_members(self):
        doc = self.team([
            {"user_id": 1, "joined_at": self.now - timedelta(days=7)},
            {"user_id": 2, "joined_at": self.now - timedelta(days=7) + timedelta(seconds=1)},
            {"user_id": 3}, {"user_id": 4, "joined_at": self.now - timedelta(days=10)},
        ], balance=10)
        result = self.distribute(doc, present={1, 2, 3})
        self.assertEqual(result["recipients"], ["1"])
        self.assertEqual(self.db.eco_users.find_one()["eter"], 10)

    def test_non_leader_cannot_distribute(self):
        doc = self.team(balance=100)
        with self.assertRaises(finance.GuildFinanceError):
            self.distribute(doc, actor=2)
        self.assertEqual(self.db.guilds.find_one()["treasury_eter"], 100)
        self.assertEqual(self.db.eco_users.count_documents({}), 0)

    def test_simultaneous_retries_distribute_once(self):
        doc = self.team(balance=100)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.distribute(doc), (1, 2)))
        self.assertEqual(results[0]["amount"], results[1]["amount"])
        self.assertEqual(self.db.eco_users.find_one()["eter"], 100)
        self.assertEqual(self.db.guilds.find_one()["treasury_eter"], 0)

    def test_distinct_simultaneous_commands_cannot_spend_same_treasury(self):
        doc = self.team(balance=100)
        def attempt(n):
            try:
                return self.distribute(doc, operation_id=f"distribute:{n}")
            except finance.GuildFinanceError:
                return None
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(attempt, (1, 2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(self.db.eco_users.find_one()["eter"], 100)
        self.assertEqual(self.db.guilds.find_one()["treasury_eter"], 0)

    def test_no_eligible_members_preserves_treasury(self):
        doc = self.team([{"user_id": 1, "joined_at": self.now - timedelta(days=6)}], balance=100)
        with self.assertRaises(finance.GuildFinanceError):
            self.distribute(doc)
        self.assertEqual(self.db.guilds.find_one()["treasury_eter"], 100)
        self.assertEqual(self.db.eco_users.count_documents({}), 0)

    def test_leader_must_also_complete_waiting_period_to_receive(self):
        doc = self.team([{"user_id": 1, "joined_at": self.now - timedelta(days=6)},
                         {"user_id": 2, "joined_at": self.now - timedelta(days=8)}], balance=100)
        self.assertEqual(self.distribute(doc)["recipients"], ["2"])
        self.assertIsNone(self.db.eco_users.find_one({"_id": finance.economy_id(self.server, 1)}))

    def test_join_records_new_waiting_period_and_prevents_second_membership(self):
        doc = self.team()
        finance.join_guild(self.server, doc["_id"], 2, doc["members"], {1})
        updated = self.db.guilds.find_one()
        joined = next(r for r in updated["members"] if r["user_id"] == 2)
        self.assertGreaterEqual(finance.utc_date(joined["joined_at"]), self.now - timedelta(seconds=1))
        with self.assertRaises(finance.GuildFinanceError):
            finance.create_guild(self.server, 2, "Outra", "🛡️", "create:2")
        self.db.guilds.update_one({"_id": doc["_id"]}, {"$set": {"treasury_eter": 10}})
        updated["treasury_eter"] = 10
        self.assertEqual(self.distribute(updated)["recipients"], ["1"])

    def test_history_is_bounded_and_scoped_to_guild(self):
        doc = self.team()
        self.db.guild_history.insert_many([
            {"_id": f"distribution:{n:03d}", "guild_id": doc["_id"], "type": "distribution", "updated_at": self.now}
            for n in range(105)
        ] + [{"_id": "other", "guild_id": ObjectId(), "updated_at": self.now}])
        entries = finance.read_history(self.server, 1, doc["_id"])[1]
        self.assertEqual(len(entries), 100)
        self.assertTrue(all(entry["guild_id"] == doc["_id"] for entry in entries))

    def test_failure_mid_distribution_leaves_all_balances_unchanged(self):
        doc = self.team([{"user_id": uid, "joined_at": self.now - timedelta(days=8)} for uid in (1, 2)], balance=100)
        original = finance.eco_users_col.update_one
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OperationFailure("injected failure")
            return original(*args, **kwargs)
        with patch.object(finance.eco_users_col, "update_one", side_effect=fail_second):
            with self.assertRaises(database.TransactionUnavailable):
                self.distribute(doc)
        self.assertEqual(self.db.eco_users.count_documents({}), 0)
        self.assertEqual(self.db.guilds.find_one()["treasury_eter"], 100)
        self.assertEqual(self.db.guild_history.count_documents({"type": "distribution"}), 0)

    def test_month_rollover_resets_boost_but_preserves_treasury(self):
        doc = self.team(balance=42)
        self.db.guilds.update_one({"_id": doc["_id"]}, {"$set": {"stats_monthly.key": "old-month"}})
        finance.credit_activity(self.cog, self.server, 1, "message", 100, 0, "message:1")
        doc = self.db.guilds.find_one()
        self.assertEqual(doc["treasury_eter"], 42)
        self.assertEqual(self.cog.monthly_xp(doc), 1)
        self.assertEqual(self.db.eco_users.find_one()["eter"], 100)

    def test_changed_membership_cancels_distribution(self):
        doc = self.team(balance=100)
        self.db.guilds.update_one({"_id": doc["_id"]}, {"$push": {"members": {"user_id": 2, "joined_at": self.now}}})
        with self.assertRaises(finance.GuildFinanceError):
            self.distribute(doc)
        self.assertEqual(self.db.guilds.find_one()["treasury_eter"], 100)

    def test_history_is_unavailable_to_non_member_and_former_member(self):
        doc = self.team()
        with self.assertRaises(finance.GuildFinanceError):
            finance.read_history(self.server, 2, doc["_id"])
        self.db.guilds.update_one({"_id": doc["_id"]}, {"$pull": {"members": {"user_id": 1}}})
        with self.assertRaises(finance.GuildFinanceError):
            finance.read_history(self.server, 1, doc["_id"])

    def test_deletion_with_any_balance_is_blocked_even_for_admin(self):
        doc = self.team(balance=1)
        with self.assertRaises(finance.GuildFinanceError):
            finance.delete_guild(self.server, doc["_id"], 1, "delete:1", admin=True)
        self.assertEqual(self.db.guilds.count_documents({}), 1)

    def test_test_server_uses_canonical_wallet_and_existing_guild_is_not_charged(self):
        from config import TEST_GUILD_ID
        self.team(balance=5)
        finance.credit_activity(self.cog, TEST_GUILD_ID, 1, "message", 4, 0, "message:1")
        self.assertEqual(self.db.eco_users.find_one()["_id"], finance.economy_id(self.server, 1))
        self.assertEqual(self.db.guilds.find_one()["treasury_eter"], 6)
