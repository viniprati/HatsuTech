"""Read Discord message history for VIP owners over the last N days.

Uses REST reads through a bare discord.Client: no gateway connection, bot cogs,
scheduled tasks, messages, role changes or database writes are started.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import discord
from dotenv import load_dotenv
from pymongo.errors import PyMongoError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_vip_activity import BRT, document_scope, positive_int, read_backup, read_mongodb
from config import CHAT_COUNT_CHANNEL_ID


REPORT_DIR = PROJECT_ROOT / "scripts" / "output" / "vip_message_history"


def select_owners(documents, guild_id, roles):
    owners = {}
    skipped = Counter()
    for doc in documents:
        scope = document_scope(doc, str(guild_id))
        if scope == "outro_servidor":
            continue
        linked = [(key, doc.get(key)) for key in ("role_id", "highlight_id") if doc.get(key) not in (None, "")]
        if not linked:
            continue
        if scope == "legado_sem_servidor" and not any(str(role_id) in roles for _, role_id in linked):
            skipped["legados_sem_servidor_confirmado"] += 1
            continue
        raw_uid = str(doc.get("user_id") or str(doc.get("_id", "")).rsplit(":", 1)[-1])
        if not raw_uid.isdigit() or int(raw_uid) <= 0:
            skipped["usuario_id_invalido"] += 1
            continue
        owner = owners.setdefault(int(raw_uid), {
            "usuario_id": raw_uid, "nome": None, "membro": "nao_confirmado", "cargos": [],
            "mensagens_encontradas": 0, "ultima_mensagem": None,
        })
        for field, raw_role_id in linked:
            role = roles.get(str(raw_role_id))
            item = {
                "cargo_id": str(raw_role_id), "nome": role.name if role else None,
                "tipo": "personalizado" if field == "role_id" else "destaque",
                "existe_no_servidor": role is not None,
            }
            if item not in owner["cargos"]:
                owner["cargos"].append(item)
    return owners, dict(skipped)


def record_message(owners, message, start, end):
    owner = owners.get(message.author.id)
    if owner is None or message.author.bot or not start <= message.created_at <= end:
        return
    owner["mensagens_encontradas"] += 1
    previous = owner["ultima_mensagem"]
    if previous is None or message.created_at > datetime.fromisoformat(previous["data_utc"]):
        owner["ultima_mensagem"] = {
            "data_utc": message.created_at.isoformat(),
            "data_brt": message.created_at.astimezone(BRT).isoformat(),
            "canal_id": str(message.channel.id), "mensagem_id": str(message.id), "url": message.jump_url,
        }


def issue(coverage, scope, target_id, reason):
    coverage["falhas"].append({"escopo": scope, "id": str(target_id), "motivo": reason})


async def scan_channel(channel, owners, start, end, coverage):
    scanned = {"canal_id": str(channel.id), "nome": channel.name, "mensagens_lidas": 0, "completo": False}
    coverage["canais"].append(scanned)
    print(f"Lendo histórico: {channel.name} ({channel.id})", flush=True)
    try:
        # No per-channel cap: read the entire requested interval, newest first.
        async for message in channel.history(limit=None, after=start, before=end + timedelta(milliseconds=1), oldest_first=False):
            scanned["mensagens_lidas"] += 1
            record_message(owners, message, start, end)
        scanned["completo"] = True
    except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError) as exc:
        issue(coverage, "historico", channel.id, type(exc).__name__)


async def scan_guild(guild, me, owners, start, end, channel_id=None, include_threads=True):
    coverage = {
        "canais": [], "falhas": [], "escopo": "servidor" if channel_id is None else "canal",
        "canal_selecionado": str(channel_id) if channel_id is not None else None,
        "inclui_threads": include_threads,
    }
    channels = await guild.fetch_channels()
    if channel_id is not None:
        channels = [channel for channel in channels if channel.id == channel_id]
        if not channels or not isinstance(channels[0], discord.abc.Messageable):
            raise ValueError("O canal selecionado não foi encontrado como canal de mensagens neste servidor.")
    visited = set()

    async def visit(channel):
        if channel.id not in visited:
            visited.add(channel.id)
            await scan_channel(channel, owners, start, end, coverage)

    # Read ordinary channels and text chat in voice/stage channels as well.
    for channel in channels:
        if not isinstance(channel, discord.abc.Messageable) and not hasattr(channel, "archived_threads"):
            continue
        permissions = channel.permissions_for(me)
        if not permissions.view_channel or not permissions.read_message_history:
            issue(coverage, "permissoes_canal", channel.id, "sem_ver_canal_ou_ler_historico")
            continue
        if isinstance(channel, discord.abc.Messageable):
            await visit(channel)
        if include_threads and hasattr(channel, "archived_threads"):
            variants = [{}]
            if isinstance(channel, discord.TextChannel):
                variants.append({"private": True, "joined": not permissions.manage_threads})
                if not permissions.manage_threads:
                    issue(coverage, "threads_privadas", channel.id, "threads_privadas_nao_associadas_podem_estar_ausentes")
            for options in variants:
                try:
                    # Enumerate all archives; creation dates do not bound recent activity.
                    async for thread in channel.archived_threads(limit=None, **options):
                        await visit(thread)
                except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    issue(coverage, "enumeracao_threads", channel.id, type(exc).__name__)
    if include_threads:
        try:
            for thread in await guild.active_threads():
                if channel_id is None or thread.parent_id == channel_id:
                    await visit(thread)
        except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError) as exc:
            issue(coverage, "threads_ativas", guild.id, type(exc).__name__)
    coverage["completa_nos_canais_enumerados"] = not coverage["falhas"]
    return coverage


def finish_report(owners, coverage):
    for owner in owners.values():
        if owner["mensagens_encontradas"]:
            owner["resultado_mensagens"] = "COM_MENSAGENS_NO_PERIODO"
            owner["resultado_atividade_geral"] = "ATIVIDADE_CONFIRMADA"
        else:
            owner["resultado_mensagens"] = (
                "INCONCLUSIVO_COBERTURA_PARCIAL" if coverage["falhas"] else "SEM_MENSAGENS_ENCONTRADAS"
            )
            owner["resultado_atividade_geral"] = "INCONCLUSIVO_SEM_HISTORICO_DE_CALL_E_OUTRAS_ATIVIDADES"
    return sorted(owners.values(), key=lambda owner: (owner["resultado_mensagens"], owner["usuario_id"]))


async def audit_history(token, documents, guild_id, days, channel_id=CHAT_COUNT_CHANNEL_ID, include_threads=False):
    async with discord.Client(intents=discord.Intents.none()) as client:
        # login() authenticates HTTP only; start()/connect() are intentionally unused.
        await client.login(token)
        guild = await client.fetch_guild(guild_id)
        me = await guild.fetch_member(client.user.id)
        roles = {str(role.id): role for role in guild.roles}
        owners, skipped = select_owners(documents, guild_id, roles)
        if not owners:
            raise ValueError("Nenhum dono de cargo VIP vinculado foi encontrado para este servidor.")
        for uid, owner in owners.items():
            try:
                member = await guild.fetch_member(uid)
                owner["nome"] = member.display_name
                owner["membro"] = "presente"
            except discord.NotFound:
                owner["membro"] = "ausente"
            except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError):
                pass
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days)
        print(f"Analisando mensagens de {len(owners)} dono(s) desde {start.astimezone(BRT).isoformat()}.", flush=True)
        print(f"Escopo: {'servidor inteiro' if channel_id is None else f'canal {channel_id}'}; threads: {include_threads}.", flush=True)
        coverage = await scan_guild(guild, me, owners, start, end, channel_id, include_threads)
        rows = finish_report(owners, coverage)
        return {
            "schema_version": 1, "exported_at": datetime.now(timezone.utc).isoformat(),
            "guild_id": str(guild.id), "guild_name": guild.name, "threshold_days": days,
            "period_start_utc": start.isoformat(), "period_end_utc": end.isoformat(),
            "source": "discord_message_history", "read_only": True,
            "summary": dict(Counter(row["resultado_mensagens"] for row in rows)),
            "skipped_records": skipped, "coverage": coverage, "owners": rows,
            "limitations": [
                "Resultados se limitam aos canais e threads indicados na cobertura deste relatório.",
                "Mensagens apagadas, canais apagados e canais inacessíveis não podem ser analisados.",
                "O histórico desta consulta não reconstrói participação passada em calls, reações ou interações.",
                "Sem mensagens encontradas não significa inatividade geral; não use este relatório para exclusão automática.",
                "Nenhum conteúdo de mensagem é armazenado, apenas contagens, IDs, datas e link da última mensagem.",
            ],
        }


def save_report(payload):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"vip_message_history_{datetime.now(timezone.utc):%Y%m%d_%H%M%S_%f}_UTC.json"
    with path.open("x", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)
        output.write("\n")
    return path


def main(argv=None):
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(Path.home() / ".env", override=False)
    parser = argparse.ArgumentParser(description="Consulta mensagens antigas dos donos de cargos VIP, sem alterar cargos ou dados.")
    parser.add_argument("--days", type=positive_int, default=10, help="Últimos N dias (padrão: 10).")
    parser.add_argument("--guild-id", type=positive_int, default=os.getenv("MAIN_GUILD_ID", "609159041499004982"))
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--channel-id", type=positive_int, default=CHAT_COUNT_CHANNEL_ID,
                       help=f"Canal a consultar (padrão: lobby {CHAT_COUNT_CHANNEL_ID}).")
    scope.add_argument("--all-channels", action="store_true", help="Consultar o servidor inteiro, incluindo threads.")
    parser.add_argument("--include-threads", action="store_true", help="Incluir threads do canal selecionado.")
    parser.add_argument("--input", type=Path, help="Backup JSON dos vínculos VIP; a consulta ao Discord continua necessária.")
    args = parser.parse_args(argv)
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        print("ERRO: configure DISCORD_TOKEN no .env para consultar o histórico do Discord.", file=sys.stderr)
        return 1
    try:
        documents = read_backup(args.input) if args.input else read_mongodb()
        payload = asyncio.run(audit_history(
            token, documents, args.guild_id, args.days,
            channel_id=None if args.all_channels else args.channel_id,
            include_threads=args.include_threads or args.all_channels,
        ))
        path = save_report(payload)
        print(f"\nJSON local salvo em: {path}")
        for status, count in payload["summary"].items():
            print(f"{status}: {count}")
        print(f"Falhas ou restrições de cobertura: {len(payload['coverage']['falhas'])}")
        print("A ausência de mensagens não comprova ausência de calls ou de outras atividades.")
        return 0
    except (discord.DiscordException, aiohttp.ClientError, asyncio.TimeoutError, PyMongoError, OSError) as exc:
        print(f"ERRO: não foi possível concluir a consulta ({type(exc).__name__}). Confira conexão e permissões.", file=sys.stderr)
        return 1
    except ValueError:
        print("ERRO: confira a configuração, o canal/servidor selecionado, o JSON de entrada e os vínculos VIP.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nConsulta interrompida; nenhum resultado completo foi gerado.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
