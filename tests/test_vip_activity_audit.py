import csv
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from pymongo.errors import ServerSelectionTimeoutError

from scripts import audit_vip_activity as audit


class VipActivityAuditTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.report_dir = Path(directory.name) / "reports"
        output_patch = patch.object(audit, "REPORT_DIR", self.report_dir)
        output_patch.start()
        self.addCleanup(output_patch.stop)
        self.now = datetime.now(timezone.utc)
        self.doc = {
            "_id": "1:2", "guild_id": "1", "user_id": "2", "role_id": "3",
            "last_activity_at": self.now - timedelta(days=11),
            "inactivity_observed_at": self.now,
            "inactivity_policy": audit.ACTIVITY_POLICY,
        }

    def report(self, **options):
        return audit.build_report([self.doc], "1", 10, self.now, **options)

    def test_current_history_and_old_activity_are_reported(self):
        rows, skipped = self.report()
        self.assertEqual(rows[0]["situacao"], "SEM_ATIVIDADE_REGISTRADA")
        self.assertEqual(rows[0]["dias_sem_registro"], "11.00")
        self.assertEqual(rows[0]["usuario_id"], "2")
        self.assertEqual(skipped, 0)

    def test_old_policy_does_not_prove_inactivity(self):
        self.doc.pop("inactivity_policy")
        rows, _ = self.report()
        self.assertEqual(rows[0]["situacao"], "POSSIVEL_INATIVO")
        self.assertEqual(rows[0]["historico"], "regra_antiga_ou_desconhecida")

    def test_recent_activity_is_evidence_even_with_old_policy(self):
        self.doc.pop("inactivity_policy")
        self.doc["last_activity_at"] = self.now - timedelta(days=2)
        rows, _ = self.report()
        self.assertEqual(rows[0]["situacao"], "ATIVIDADE_RECENTE")

    def test_monitoring_gap_does_not_prove_inactivity(self):
        self.doc["inactivity_observed_at"] = self.now - timedelta(hours=1)
        rows, _ = self.report()
        self.assertEqual(rows[0]["situacao"], "POSSIVEL_INATIVO")
        self.assertEqual(rows[0]["historico"], "monitoramento_interrompido")

    def test_missing_malformed_and_future_activity_are_unknown(self):
        for value in (None, "data inválida", self.now + timedelta(hours=1)):
            with self.subTest(value=value):
                self.doc["last_activity_at"] = value
                rows, _ = self.report()
                self.assertEqual(rows[0]["situacao"], "HISTORICO_INSUFICIENTE")

    def test_two_roles_have_separate_activity_dates(self):
        self.doc.update(highlight_id="4", highlight_last_activity_at=self.now - timedelta(days=1))
        rows, _ = self.report()
        by_kind = {row["tipo"]: row for row in rows}
        self.assertEqual(by_kind["personalizado"]["situacao"], "SEM_ATIVIDADE_REGISTRADA")
        self.assertEqual(by_kind["destaque"]["situacao"], "ATIVIDADE_RECENTE")

    def test_other_servers_and_unscoped_legacy_are_not_assumed_to_match(self):
        self.doc["guild_id"] = "99"
        self.assertEqual(self.report()[0], [])
        self.doc.pop("guild_id")
        self.assertEqual(len(self.report()[0]), 1)
        self.doc["_id"] = "2"
        rows, skipped = self.report()
        self.assertEqual(rows, [])
        self.assertEqual(skipped, 1)
        rows, _ = self.report(include_legacy=True)
        self.assertEqual(rows[0]["situacao"], "HISTORICO_INSUFICIENTE")
        self.assertEqual(rows[0]["historico"], "servidor_nao_confirmado")

    def test_naive_mongo_datetimes_and_backup_iso_are_supported(self):
        expected = self.now.replace(tzinfo=None)
        self.assertEqual(audit.parse_datetime(expected), self.now)
        self.assertEqual(audit.parse_datetime(self.now.isoformat()), self.now)
        self.assertEqual(audit.parse_datetime({"$date": self.now.isoformat()}), self.now)

    def test_offline_backup_and_csv_work_without_mongodb(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "backup.json"
            output = Path(directory) / "report.csv"
            content = json.dumps({"documents": [self.doc]}, default=lambda date: date.isoformat())
            source.write_text(content, encoding="utf-8")
            console = io.StringIO()
            with patch.object(audit, "MongoClient") as mongo, redirect_stdout(console):
                result = audit.main(["--input", str(source), "--guild-id", "1", "--csv", str(output)])
            self.assertEqual(result, 0)
            mongo.assert_not_called()
            self.assertEqual(source.read_text(encoding="utf-8"), content)
            with output.open(encoding="utf-8-sig", newline="") as report:
                rows = list(csv.DictReader(report))
            self.assertEqual(rows[0]["usuario_id"], "2")
            self.assertIn("Somente leitura", console.getvalue())

    def test_running_without_export_flags_generates_reusable_json(self):
        self.doc["unrelated_private_field"] = "must not be exported"
        other_server = {**self.doc, "_id": "99:9", "guild_id": "99", "user_id": "9"}
        with patch.object(audit, "read_mongodb", return_value=[self.doc, other_server]):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(audit.main(["--guild-id", "1"]), 0)
        files = list(self.report_dir.glob("*.json"))
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["threshold_days"], 10)
        self.assertEqual(payload["summary"]["owners"], 1)
        self.assertEqual(payload["rows"][0]["usuario_id"], "2")
        self.assertEqual(len(payload["documents"]), 1)
        self.assertNotIn("unrelated_private_field", payload["documents"][0])
        replay, _ = audit.build_report(audit.read_backup(files[0]), "1", 10, self.now)
        self.assertEqual(replay[0]["situacao"], "SEM_ATIVIDADE_REGISTRADA")

    def test_each_execution_keeps_a_separate_json_snapshot(self):
        with patch.object(audit, "read_mongodb", return_value=[self.doc]), redirect_stdout(io.StringIO()):
            self.assertEqual(audit.main(["--guild-id", "1"]), 0)
            self.assertEqual(audit.main(["--guild-id", "1"]), 0)
        self.assertEqual(len(list(self.report_dir.glob("*.json"))), 2)

    def test_mongo_reader_uses_only_ping_and_find(self):
        cursor = MagicMock()
        cursor.max_time_ms.return_value = [self.doc]
        collection = SimpleNamespace(find=MagicMock(return_value=cursor))
        client = MagicMock()
        client.__enter__.return_value = client
        client.__getitem__.return_value = {"vip_roles": collection}
        with patch.dict(os.environ, {"MONGO_URI": "configured"}), patch.object(audit, "MongoClient", return_value=client):
            self.assertEqual(audit.read_mongodb(), [self.doc])
        client.admin.command.assert_called_once_with("ping")
        collection.find.assert_called_once()

    def test_database_failure_is_not_reported_as_empty_or_leaked(self):
        console, errors = io.StringIO(), io.StringIO()
        with patch.object(audit, "read_mongodb", side_effect=ServerSelectionTimeoutError("secret connection details")):
            with redirect_stdout(console), redirect_stderr(errors):
                result = audit.main(["--guild-id", "1"])
        self.assertEqual(result, 1)
        self.assertNotIn("secret connection details", errors.getvalue())
        self.assertNotIn("Nenhum vínculo", console.getvalue())
        self.assertFalse(self.report_dir.exists())

    def test_nonpositive_days_are_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            audit.main(["--days", "0"])

    def test_csv_cannot_overwrite_input_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "backup.json"
            source.write_text("[]", encoding="utf-8")
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                audit.main(["--input", str(source), "--csv", str(source)])
            self.assertEqual(source.read_text(encoding="utf-8"), "[]")

    def test_missing_credentials_do_not_attempt_a_connection(self):
        errors = io.StringIO()
        with patch.dict(os.environ, {"MONGO_URI": ""}), patch.object(audit, "MongoClient") as mongo:
            with redirect_stderr(errors):
                self.assertEqual(audit.main(["--guild-id", "1"]), 1)
        mongo.assert_not_called()
        self.assertIn("Configure MONGO_URI", errors.getvalue())

    def test_exact_ten_day_boundary_and_custom_threshold(self):
        self.doc["last_activity_at"] = self.now - timedelta(days=10)
        self.assertEqual(self.report()[0][0]["situacao"], "SEM_ATIVIDADE_REGISTRADA")
        rows, _ = audit.build_report([self.doc], "1", 15, self.now)
        self.assertEqual(rows[0]["situacao"], "ATIVIDADE_RECENTE")


if __name__ == "__main__":
    unittest.main()
