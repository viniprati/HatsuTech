import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

from scripts import audit_vip_message_history as audit


async def items(values, failure=None):
    for value in values:
        yield value
    if failure:
        raise failure


class MessageHistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.end = datetime.now(timezone.utc)
        self.start = self.end - timedelta(days=10)
        self.doc = {"_id": "1:2", "guild_id": "1", "user_id": "2", "role_id": "3"}
        self.roles = {"3": SimpleNamespace(id=3, name="VIP pessoal")}
        self.owners, _ = audit.select_owners([self.doc], 1, self.roles)

    def message(self, uid=2, age=1, mid=55):
        return SimpleNamespace(
            id=mid, author=SimpleNamespace(id=uid, bot=False),
            created_at=self.end - timedelta(days=age), channel=SimpleNamespace(id=9),
            jump_url=f"https://discord.com/channels/1/9/{mid}",
        )

    def channel(self, channel_id=9, messages=(), threads=()):
        channel = MagicMock(spec=discord.TextChannel)
        channel.id = channel_id
        channel.name = "canal"
        channel.permissions_for.return_value = SimpleNamespace(
            view_channel=True, read_message_history=True, manage_threads=True
        )
        channel.history.side_effect = lambda **_kwargs: items(messages)
        channel.archived_threads.side_effect = lambda **_kwargs: items(threads)
        return channel

    def guild(self, channels=(), active=()):
        return SimpleNamespace(
            id=1, name="Servidor", roles=list(self.roles.values()),
            fetch_channels=AsyncMock(return_value=list(channels)),
            active_threads=AsyncMock(return_value=list(active)),
        )

    async def test_reads_existing_messages_without_activity_timestamps(self):
        channel = self.channel(messages=[self.message()])
        with redirect_stdout(io.StringIO()):
            coverage = await audit.scan_guild(self.guild([channel]), object(), self.owners, self.start, self.end)
        rows = audit.finish_report(self.owners, coverage)
        self.assertEqual(rows[0]["resultado_atividade_geral"], "ATIVIDADE_CONFIRMADA")
        self.assertEqual(rows[0]["mensagens_encontradas"], 1)
        self.assertEqual(rows[0]["ultima_mensagem"]["mensagem_id"], "55")
        self.assertEqual(channel.history.call_args.kwargs["after"], self.start)
        self.assertIsNone(channel.history.call_args.kwargs["limit"])

    async def test_archive_and_active_threads_are_scanned_once(self):
        thread = self.channel(channel_id=10, messages=[self.message()])
        parent = self.channel(threads=[thread])
        with redirect_stdout(io.StringIO()):
            coverage = await audit.scan_guild(self.guild([parent], [thread]), object(), self.owners, self.start, self.end)
        self.assertEqual(len(coverage["canais"]), 2)
        thread.history.assert_called_once()
        self.assertEqual(self.owners[2]["mensagens_encontradas"], 1)

    async def test_hidden_channel_makes_negative_result_inconclusive(self):
        channel = self.channel()
        channel.permissions_for.return_value.view_channel = False
        coverage = await audit.scan_guild(self.guild([channel]), object(), self.owners, self.start, self.end)
        rows = audit.finish_report(self.owners, coverage)
        self.assertEqual(rows[0]["resultado_mensagens"], "INCONCLUSIVO_COBERTURA_PARCIAL")
        channel.history.assert_not_called()

    async def test_empty_history_does_not_claim_general_inactivity(self):
        with redirect_stdout(io.StringIO()):
            coverage = await audit.scan_guild(self.guild([self.channel()]), object(), self.owners, self.start, self.end)
        row = audit.finish_report(self.owners, coverage)[0]
        self.assertEqual(row["resultado_mensagens"], "SEM_MENSAGENS_ENCONTRADAS")
        self.assertIn("INCONCLUSIVO", row["resultado_atividade_geral"])

    async def test_partial_http_failure_preserves_messages_and_marks_coverage(self):
        channel = self.channel()
        response = SimpleNamespace(status=403, reason="Forbidden")
        channel.history.side_effect = lambda **_kwargs: items([self.message()], discord.Forbidden(response, "Forbidden"))
        with redirect_stdout(io.StringIO()):
            coverage = await audit.scan_guild(self.guild([channel]), object(), self.owners, self.start, self.end)
        self.assertFalse(coverage["canais"][0]["completo"])
        self.assertFalse(coverage["completa_nos_canais_enumerados"])
        self.assertEqual(audit.finish_report(self.owners, coverage)[0]["resultado_mensagens"], "COM_MENSAGENS_NO_PERIODO")

    async def test_unknown_private_threads_are_reported(self):
        channel = self.channel()
        channel.permissions_for.return_value.manage_threads = False
        with redirect_stdout(io.StringIO()):
            coverage = await audit.scan_guild(self.guild([channel]), object(), self.owners, self.start, self.end)
        self.assertTrue(coverage["falhas"])
        self.assertTrue(any(call.kwargs.get("joined") for call in channel.archived_threads.call_args_list))

    async def test_voice_channel_text_chat_is_scanned(self):
        channel = MagicMock(spec=discord.VoiceChannel)
        channel.id, channel.name = 12, "call"
        channel.permissions_for.return_value = SimpleNamespace(view_channel=True, read_message_history=True)
        channel.history.side_effect = lambda **_kwargs: items([self.message()])
        with redirect_stdout(io.StringIO()):
            coverage = await audit.scan_guild(self.guild([channel]), object(), self.owners, self.start, self.end)
        self.assertTrue(coverage["canais"][0]["completo"])
        self.assertEqual(self.owners[2]["mensagens_encontradas"], 1)

    async def test_failed_thread_discovery_is_not_treated_as_complete(self):
        guild = self.guild()
        response = SimpleNamespace(status=503, reason="Unavailable")
        guild.active_threads.side_effect = discord.HTTPException(response, "Unavailable")
        coverage = await audit.scan_guild(guild, object(), self.owners, self.start, self.end)
        self.assertFalse(coverage["completa_nos_canais_enumerados"])
        self.assertEqual(coverage["falhas"][0]["escopo"], "threads_ativas")

    async def test_http_login_only_never_starts_the_bot(self):
        channel = self.channel(messages=[self.message()])
        guild = self.guild([channel])
        guild.fetch_member = AsyncMock(return_value=SimpleNamespace(display_name="Dono"))
        client = MagicMock()
        client.__aenter__.return_value = client
        client.user = SimpleNamespace(id=999)
        client.login = AsyncMock()
        client.fetch_guild = AsyncMock(return_value=guild)
        with patch.object(audit.discord, "Client", return_value=client), redirect_stdout(io.StringIO()):
            payload = await audit.audit_history("not-a-real-token", [self.doc], 1, 10, channel_id=9)
        client.login.assert_awaited_once()
        client.start.assert_not_called()
        client.connect.assert_not_called()
        channel.send.assert_not_called()
        self.assertTrue(payload["read_only"])
        self.assertNotIn("not-a-real-token", json.dumps(payload))
        self.assertNotIn("content", payload["owners"][0]["ultima_mensagem"])

    async def test_lobby_only_does_not_read_other_channels_or_threads(self):
        lobby = self.channel(channel_id=9, messages=[self.message()])
        other = self.channel(channel_id=10)
        guild = self.guild([lobby, other])
        with redirect_stdout(io.StringIO()):
            coverage = await audit.scan_guild(guild, object(), self.owners, self.start, self.end,
                                              channel_id=9, include_threads=False)
        lobby.history.assert_called_once()
        other.history.assert_not_called()
        lobby.archived_threads.assert_not_called()
        other.archived_threads.assert_not_called()
        guild.active_threads.assert_not_awaited()
        self.assertEqual(coverage["canal_selecionado"], "9")
        self.assertEqual(len(coverage["canais"]), 1)

    async def test_optional_threads_are_limited_to_lobby(self):
        lobby = self.channel(channel_id=9)
        lobby_thread = self.channel(channel_id=11)
        lobby_thread.parent_id = 9
        other_thread = self.channel(channel_id=12)
        other_thread.parent_id = 10
        guild = self.guild([lobby], [lobby_thread, other_thread])
        with redirect_stdout(io.StringIO()):
            await audit.scan_guild(guild, object(), self.owners, self.start, self.end,
                                   channel_id=9, include_threads=True)
        lobby_thread.history.assert_called_once()
        other_thread.history.assert_not_called()

    async def test_wrong_lobby_id_does_not_fall_back_to_entire_server(self):
        other = self.channel(channel_id=10)
        with self.assertRaises(ValueError):
            await audit.scan_guild(self.guild([other]), object(), self.owners, self.start, self.end,
                                   channel_id=9, include_threads=False)
        other.history.assert_not_called()

    def test_filters_window_other_users_and_bots_and_keeps_latest_evidence(self):
        bot_message = self.message()
        bot_message.author.bot = True
        for message in [self.message(age=3, mid=1), self.message(age=1, mid=2), self.message(age=11),
                        self.message(age=-1), self.message(uid=999), bot_message]:
            audit.record_message(self.owners, message, self.start, self.end)
        self.assertEqual(self.owners[2]["mensagens_encontradas"], 2)
        self.assertEqual(self.owners[2]["ultima_mensagem"]["mensagem_id"], "2")

    def test_owner_sources_are_scoped_and_legacy_can_be_resolved_by_role(self):
        foreign = {**self.doc, "guild_id": "99", "user_id": "9"}
        legacy = {"_id": "4", "role_id": "3"}
        unknown = {"_id": "5", "role_id": "999"}
        owners, skipped = audit.select_owners([self.doc, self.doc, foreign, legacy, unknown], 1, self.roles)
        self.assertEqual(set(owners), {2, 4})
        self.assertEqual(len(owners[2]["cargos"]), 1)
        self.assertEqual(skipped["legados_sem_servidor_confirmado"], 1)

    def test_json_output_is_local_and_contains_no_message_content(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(audit, "REPORT_DIR", Path(directory)):
            audit.record_message(self.owners, self.message(), self.start, self.end)
            rows = audit.finish_report(self.owners, {"falhas": []})
            path = audit.save_report({"owners": rows, "read_only": True})
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["owners"][0]["mensagens_encontradas"], 1)
            self.assertNotIn("content", path.read_text(encoding="utf-8"))


class MessageHistoryCliTests(unittest.TestCase):
    def test_default_cli_selects_configured_lobby_without_threads(self):
        runner = AsyncMock(return_value={"summary": {}, "coverage": {"falhas": []}})
        with patch.dict(os.environ, {"DISCORD_TOKEN": "fake"}), patch.object(audit, "read_mongodb", return_value=[]):
            with patch.object(audit, "audit_history", runner), patch.object(audit, "save_report", return_value=Path("fake.json")):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(audit.main([]), 0)
        self.assertEqual(runner.call_args.kwargs["channel_id"], audit.CHAT_COUNT_CHANNEL_ID)
        self.assertFalse(runner.call_args.kwargs["include_threads"])

    def test_missing_token_never_contacts_services(self):
        with patch.dict(os.environ, {"DISCORD_TOKEN": ""}), patch.object(audit, "read_mongodb") as mongo:
            with redirect_stderr(io.StringIO()):
                self.assertEqual(audit.main([]), 1)
        mongo.assert_not_called()

    def test_bad_token_error_is_sanitized(self):
        with patch.dict(os.environ, {"DISCORD_TOKEN": "private-token"}):
            with patch.object(audit, "read_mongodb", return_value=[]):
                with patch.object(audit, "audit_history", AsyncMock(side_effect=discord.LoginFailure("private-token"))):
                    errors = io.StringIO()
                    with redirect_stderr(errors):
                        self.assertEqual(audit.main([]), 1)
        self.assertNotIn("private-token", errors.getvalue())
        self.assertIn("LoginFailure", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
