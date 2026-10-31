from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4

import discord

from config import MAIN_GUILD_ID
from database import is_db_online, welcome_dm_logs_col
from utils import ensure_db_online, ensure_guild_interaction, has_full_access
from ..cog import APOIADOR_BENEFITS, APOIADOR_CHANNEL_ID, APOIADOR_ROLE_ID, member_has_server_tag


log = logging.getLogger(__name__)
DM_DELAY_SECONDS = 1.25
PROGRESS_INTERVAL_SECONDS = 30
MAX_CONSECUTIVE_FAILURES = 5


def _reserve_reminder(record_id: str, guild_id: int, user_id: int, run_id: str) -> bool | None:
    """Reserve once before sending; only definite failed deliveries can be retried."""
    document = {
        "type": "tag_supporter_reminder", "guild_id": str(guild_id),
        "user_id": str(user_id), "status": "pending", "run_id": run_id,
        "created_at": datetime.now(timezone.utc),
    }
    result = welcome_dm_logs_col.update_one(
        {"_id": record_id}, {"$setOnInsert": document}, upsert=True,
    )
    if not getattr(result, "acknowledged", False):
        return None
    if result.upserted_id is not None:
        return True
    # Matching by status ensures only one concurrent run can claim a retry.
    result = welcome_dm_logs_col.update_one(
        {"_id": record_id, "status": "failed"}, {"$set": document},
    )
    if not getattr(result, "acknowledged", False):
        return None
    return result.matched_count == 1


def needs_supporter_reminder(member: discord.Member) -> bool:
    return (
        not member.bot
        and member_has_server_tag(member)
        and getattr(member.primary_guild, "identity_enabled", False) is True
        and not any(role.id == APOIADOR_ROLE_ID for role in member.roles)
    )


def build_tag_reminder(guild: discord.Guild, channel: discord.TextChannel):
    url = f"https://discord.com/channels/{guild.id}/{channel.id}"
    embed = discord.Embed(
        title="☕ Sua tag já pode render benefícios!",
        description=(
            f"Oi! Eu sou a **HatsuTech**, o bot oficial do **{discord.utils.escape_markdown(guild.name)}**. ☕\n\n"
            "Identifiquei que você usa a **tag do nosso servidor** no perfil, mas ainda não resgatou "
            "o cargo **Apoiador**.\n\n"
            "Obrigado por levar o Café com você! Como agradecimento, você pode resgatar o cargo "
            "gratuitamente e liberar estes benefícios no servidor:"
        ),
        color=0xFFD34D,
    )
    embed.add_field(
        name="✨ Benefícios de Apoiador",
        value="\n".join(f"• {benefit}" for benefit in APOIADOR_BENEFITS),
        inline=False,
    )
    embed.add_field(
        name="🎁 Como resgatar",
        value=(
            f"[Acesse o painel de Apoiador]({url}) e clique em **Resgatar Apoiador**.\n\n"
            "Mantenha a tag do servidor no perfil para continuar com o cargo."
        ),
        inline=False,
    )
    embed.set_footer(text="HatsuTech • Animes Café • Lembrete único de resgate")
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Resgatar Apoiador", style=discord.ButtonStyle.link, url=url))
    return embed, view


async def _report(it: discord.Interaction, content: str, run_id: str):
    try:
        await it.edit_original_response(content=content)
    except discord.HTTPException as exc:
        log.warning("tag_report_failed run_id=%s status=%s code=%s", run_id, exc.status, exc.code)


async def execute(self, it: discord.Interaction):
    await it.response.defer(ephemeral=True)
    if not await ensure_guild_interaction(it, "o comando /tag"):
        return
    # Keep the runtime check even when execute is called outside the slash command.
    if not has_full_access(it.user) and not it.permissions.administrator:
        return await it.followup.send(
            "Somente administradores, o dono do bot ou membros com acesso total podem usar /tag.",
            ephemeral=True,
        )
    if it.guild.id != MAIN_GUILD_ID:
        return await it.followup.send("Use /tag no servidor principal do Animes Café.", ephemeral=True)
    if not await ensure_db_online(it, "o comando /tag"):
        return
    if it.guild.get_role(APOIADOR_ROLE_ID) is None:
        return await it.followup.send("Cargo Apoiador não encontrado.", ephemeral=True)

    lock = self.tag_reminder_locks.setdefault(it.guild.id, asyncio.Lock())
    if lock.locked():
        return await it.followup.send("Uma análise /tag já está em andamento neste servidor.", ephemeral=True)

    async with lock:
        run_id = str(uuid4())
        started = time.monotonic()
        counts = {"analisados": 0, "elegiveis": 0, "enviados": 0, "bloqueados": 0, "pendentes": 0,
                  "ja_avisados": 0, "ignorados": 0, "falhas": 0}
        reason = None
        log.info("tag_reminders_started run_id=%s guild_id=%s actor_id=%s", run_id, it.guild.id, it.user.id)
        try:
            channel = it.guild.get_channel(APOIADOR_CHANNEL_ID)
            if channel is None:
                channel = await it.guild.fetch_channel(APOIADOR_CHANNEL_ID)
            if not isinstance(channel, discord.TextChannel):
                reason = "Canal de resgate de Apoiador inválido."
                return
            await _report(it, "Analisando todos os membros do servidor…", run_id)
            candidates = []
            last_progress = time.monotonic()
            async for member in it.guild.fetch_members(limit=None):
                counts["analisados"] += 1
                if needs_supporter_reminder(member):
                    candidates.append(member.id)
                if time.monotonic() - last_progress >= PROGRESS_INTERVAL_SECONDS:
                    await _report(it, f"Analisando membros: {counts['analisados']} verificados…", run_id)
                    last_progress = time.monotonic()
            counts["elegiveis"] = len(candidates)
            embed, view = build_tag_reminder(it.guild, channel)
            failures = 0
            await _report(it, f"Análise concluída: {len(candidates)} membros elegíveis. Enviando lembretes…", run_id)
            for user_id in candidates:
                record_id = f"tag_supporter_reminder:{it.guild.id}:{user_id}"
                previous = await asyncio.to_thread(welcome_dm_logs_col.find_one, {"_id": record_id})
                if not is_db_online():
                    reason = "Banco indisponível; envio interrompido para preservar o histórico."
                    break
                if previous and previous.get("status") in {"sent", "dm_closed"}:
                    counts["ja_avisados"] += 1
                    continue
                if previous and previous.get("status") == "pending":
                    counts["pendentes"] += 1
                    continue

                # A failure to fetch a member is not evidence their DMs are closed.
                try:
                    member = await it.guild.fetch_member(user_id)
                except discord.NotFound:
                    counts["ignorados"] += 1
                    continue
                if not needs_supporter_reminder(member):
                    counts["ignorados"] += 1
                    continue
                reserved = await asyncio.to_thread(
                    _reserve_reminder, record_id, it.guild.id, user_id, run_id,
                )
                if reserved is None:
                    reason = "Não foi possível registrar a reserva da DM; nenhum novo envio será feito."
                    break
                if not reserved:
                    counts["ignorados"] += 1
                    continue
                counts["pendentes"] += 1
                status = None
                try:
                    await member.send(embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
                    status = "sent"
                    counts["enviados"] += 1
                    failures = 0
                except discord.Forbidden:
                    status = "dm_closed"
                    counts["bloqueados"] += 1
                    failures = 0
                except discord.NotFound:
                    counts["ignorados"] += 1
                    status = "failed"
                except discord.HTTPException as exc:
                    counts["falhas"] += 1
                    failures += 1
                    log.warning("tag_dm_failed run_id=%s user_id=%s status=%s code=%s", run_id, user_id, exc.status, exc.code)
                    if 400 <= exc.status < 500:
                        status = "failed"
                    # A server error may follow delivery; its reservation stays pending.
                    if exc.status == 429 or failures >= MAX_CONSECUTIVE_FAILURES:
                        reason = "Envio interrompido por limite do Discord ou falhas consecutivas."

                if status:
                    result = await asyncio.to_thread(
                        welcome_dm_logs_col.update_one,
                        {"_id": record_id, "status": "pending", "run_id": run_id},
                        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}},
                    )
                    if not getattr(result, "acknowledged", False) or result.matched_count != 1:
                        reason = "Não foi possível registrar o resultado da DM; envio interrompido."
                        break
                    counts["pendentes"] -= 1
                if reason:
                    break
                if time.monotonic() - last_progress >= PROGRESS_INTERVAL_SECONDS:
                    await _report(it, f"Envio em andamento: {counts['enviados']} enviados, {counts['bloqueados']} bloqueados.", run_id)
                    last_progress = time.monotonic()
                await asyncio.sleep(DM_DELAY_SECONDS)
        except asyncio.CancelledError:
            reason = "Execução cancelada; reservas pendentes foram preservadas para revisão."
            raise
        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
            reason = "Não consegui consultar os membros ou o canal de resgate. Confira as permissões do bot."
            log.warning("tag_scan_failed run_id=%s status=%s code=%s", run_id, exc.status, exc.code)
        except Exception:
            reason = "Ocorreu uma falha interna. Consulte os logs desta execução."
            log.exception("tag_reminders_failed run_id=%s", run_id)
        finally:
            log.info("tag_reminders_finished run_id=%s guild_id=%s counts=%s interrupted=%s reason=%s duration_seconds=%.3f",
                     run_id, it.guild.id, counts, bool(reason), reason or "completed", time.monotonic() - started)
            report = "☕ Relatório /tag\n" + "\n".join(f"{key.replace('_', ' ').capitalize()}: **{value}**" for key, value in counts.items())
            if reason:
                report += f"\n\n{reason}"
            report += f"\n\nExecução: `{run_id}`"
            await _report(it, report, run_id)
