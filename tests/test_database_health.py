import os
import unittest
from unittest.mock import MagicMock, patch

from pymongo.errors import AutoReconnect

os.environ["MONGO_URI"] = ""
import database


class DatabaseHealthTests(unittest.TestCase):
    def test_failure_marker_survives_a_subsequent_success(self):
        underlying = MagicMock()
        underlying.find_one.side_effect = AutoReconnect("simulated connection loss")
        wrapper = database.ResilientCollection("health_test")
        before = database.get_db_failure_generation()
        with patch.object(wrapper, "_get_collection", return_value=underlying), patch.object(database, "_db_online", True):
            self.assertIsNone(wrapper.find_one({"_id": "42"}))
            after = database.get_db_failure_generation()
            underlying.find_one.side_effect = None
            underlying.find_one.return_value = {"_id": "42"}
            self.assertEqual(wrapper.find_one({"_id": "42"}), {"_id": "42"})
            self.assertTrue(database.is_db_online())
            self.assertGreater(after, before)
            self.assertEqual(database.get_db_failure_generation(), after)

    def test_degraded_default_also_marks_a_failed_operation(self):
        wrapper = database.ResilientCollection("health_test")
        before = database.get_db_failure_generation()
        with patch.object(wrapper, "_get_collection", return_value=None):
            self.assertIsNone(wrapper.find_one({"_id": "42"}))
        self.assertGreater(database.get_db_failure_generation(), before)
