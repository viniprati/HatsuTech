from __future__ import annotations

import time
from uuid import uuid4

from ..cog import *

DM_BROADCAST_DELAY_SECONDS = 1.25
MAX_ANNOUNCE_TITLE_LENGTH = DISCORD_EMBED_TITLE_LIMIT - 3
MAX_ANNOUNCE_MESSAGE_LENGTH = DISCORD_EMBED_DESCRIPTION_LIMIT - 3


async def broadcast_embed(
    self,
    interaction: discord.Interaction,
    embed: discord.Embed,
    *,
    broadcast_type: str,
    command_name: str = "/anunciar",
):
    if not await ensure_db_online(interaction, f"o comando {command_name}"):
        return

    total_users = await asyncio.to_thread(updates_col.count_documents, {})

    if total_users == 0:
        return await interaction.followup.send("⚠️ Ninguém ativou as notificações ainda.", ephemeral=True)

    broadcast_id = str(uuid4())
    started_at = time.monotonic()
    sucessos = 0
    falhas = 0
    bloqueados = 0

    log.info(
        "dm_broadcast_started broadcast_id=%s broadcast_type=%s guild_id=%s channel_id=%s actor_id=%s recipients=%s",
        broadcast_id,
        broadcast_type,
        getattr(interaction.guild, "id", None),
        getattr(interaction.channel, "id", None),
        interaction.user.id,
        total_users,
    )
    await interaction.followup.send(f"🚀 Iniciando envio para **{total_users}** usuários...", ephemeral=True)

    subscribers = await asyncio.to_thread(lambda: list(updates_col.find({})))
    for data in subscribers:
        raw_user_id = data.get("user_id")
        try:
            user_id = int(raw_user_id)

            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)

            if user:
                await user.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                sucessos += 1
            else:
                falhas += 1

        except discord.Forbidden:

            bloqueados += 1

            await asyncio.to_thread(updates_col.delete_one, {"user_id": raw_user_id})
            log.info("dm_broadcast_blocked broadcast_id=%s user_id=%s", broadcast_id, user_id)

        except (TypeError, ValueError):
            falhas += 1
            log.warning(
                "dm_broadcast_invalid_subscriber broadcast_id=%s document_id=%s",
                broadcast_id,
                data.get("_id"),
            )

        except discord.HTTPException as e:
            falhas += 1
            err_text = str(e)
            if e.status == 429 and "1015" in err_text:
                log.error(
                    "dm_broadcast_stopped_cloudflare_1015 broadcast_id=%s actor_id=%s",
                    broadcast_id,
                    interaction.user.id,
                )
                falhas += max(0, total_users - (sucessos + bloqueados + falhas))
                break
            retry_after = float(getattr(e, "retry_after", 0) or 0)
            if retry_after > 0:
                log.warning(
                    "dm_broadcast_rate_limited broadcast_id=%s user_id=%s retry_after=%s",
                    broadcast_id,
                    user_id,
                    retry_after,
                )
                await asyncio.sleep(min(retry_after + 1, 60))

        except Exception as e:
            log.warning(
                "dm_broadcast_user_failed broadcast_id=%s user_id=%s error=%s",
                broadcast_id,
                user_id,
                e,
            )
            falhas += 1


        await asyncio.sleep(DM_BROADCAST_DELAY_SECONDS)


    embed_report = discord.Embed(title="📊 Relatório de Envio", color=discord.Color.green())
    embed_report.add_field(name="✅ Enviados", value=str(sucessos), inline=True)
    embed_report.add_field(name="🔒 DM Fechada/Bloqueado", value=str(bloqueados), inline=True)
    embed_report.add_field(name="⚠️ Falhas Gerais", value=str(falhas), inline=True)
    embed_report.add_field(name="👥 Total Tentado", value=str(total_users), inline=True)
    log.info(
        "dm_broadcast_finished broadcast_id=%s broadcast_type=%s actor_id=%s "
        "recipients=%s sent=%s blocked=%s failed=%s duration_seconds=%.3f",
        broadcast_id,
        broadcast_type,
        interaction.user.id,
        total_users,
        sucessos,
        bloqueados,
        falhas,
        time.monotonic() - started_at,
    )

    try:
        await interaction.followup.send(embed=embed_report, ephemeral=True)
    except discord.HTTPException as e:
        log.warning(
            "dm_broadcast_report_failed broadcast_id=%s actor_id=%s status=%s",
            broadcast_id,
            interaction.user.id,
            e.status,
        )


async def execute(self, interaction: discord.Interaction, titulo: str, mensagem: str, imagem: discord.Attachment = None):
    await interaction.response.defer(ephemeral=True)

    title = truncate_discord_text(titulo.strip(), MAX_ANNOUNCE_TITLE_LENGTH)
    description = truncate_discord_text(mensagem.strip(), MAX_ANNOUNCE_MESSAGE_LENGTH)
    if not title:
        return await interaction.followup.send("Informe um título para o anúncio.", ephemeral=True)
    if not description:
        return await interaction.followup.send("Informe uma mensagem para o anúncio.", ephemeral=True)
    if imagem and imagem.content_type and not imagem.content_type.startswith("image/"):
        return await interaction.followup.send("O anexo do anúncio precisa ser uma imagem.", ephemeral=True)

    embed = discord.Embed(
        title=f"📢 {title}",
        description=description,
        color=discord.Color.blue(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if imagem:
        embed.set_image(url=imagem.url)

    embed.set_footer(text=f"Enviado por {interaction.user.name} • Use /notificacao para cancelar")
    await broadcast_embed(self, interaction, embed, broadcast_type="custom_announcement")
