from __future__ import annotations
from ..cog import *

DM_BROADCAST_DELAY_SECONDS = 1.25
MAX_ANNOUNCE_TITLE_LENGTH = DISCORD_EMBED_TITLE_LIMIT - 3
MAX_ANNOUNCE_MESSAGE_LENGTH = DISCORD_EMBED_DESCRIPTION_LIMIT - 3


async def execute(self, interaction: discord.Interaction, titulo: str, mensagem: str, imagem: discord.Attachment = None):

    await interaction.response.defer(ephemeral=True)

    if not await ensure_db_online(interaction, "o comando /anunciar"):
        return

    title = truncate_discord_text(titulo.strip(), MAX_ANNOUNCE_TITLE_LENGTH)
    description = truncate_discord_text(mensagem.strip(), MAX_ANNOUNCE_MESSAGE_LENGTH)
    if not title:
        return await interaction.followup.send("Informe um título para o anúncio.", ephemeral=True)
    if not description:
        return await interaction.followup.send("Informe uma mensagem para o anúncio.", ephemeral=True)
    if imagem and imagem.content_type and not imagem.content_type.startswith("image/"):
        return await interaction.followup.send("O anexo do anúncio precisa ser uma imagem.", ephemeral=True)

    total_users = await asyncio.to_thread(updates_col.count_documents, {})

    if total_users == 0:
        return await interaction.followup.send("⚠️ Ninguém ativou as notificações ainda.", ephemeral=True)


    embed = discord.Embed(
        title=f"📢 {title}",
        description=description,
        color=discord.Color.blue(),
        timestamp=datetime.datetime.now(datetime.timezone.utc)
    )
    if imagem:
        embed.set_image(url=imagem.url)

    embed.set_footer(text=f"Enviado por {interaction.user.name} • Use /notificacao para cancelar")


    sucessos = 0
    falhas = 0
    bloqueados = 0

    log.info(
        "dm_broadcast_started guild_id=%s channel_id=%s actor_id=%s recipients=%s",
        getattr(interaction.guild, "id", None),
        getattr(interaction.channel, "id", None),
        interaction.user.id,
        total_users,
    )
    await interaction.followup.send(f"🚀 Iniciando envio para **{total_users}** usuários...", ephemeral=True)

    subscribers = await asyncio.to_thread(lambda: list(updates_col.find({})))
    for data in subscribers:
        user_id = data["user_id"]
        try:

            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)

            if user:
                await user.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
                sucessos += 1
            else:
                falhas += 1

        except discord.Forbidden:

            bloqueados += 1

            await asyncio.to_thread(updates_col.delete_one, {"user_id": user_id})
            log.info("dm_broadcast_blocked user_id=%s", user_id)

        except discord.HTTPException as e:
            falhas += 1
            err_text = str(e)
            if e.status == 429 and "1015" in err_text:
                log.error("dm_broadcast_stopped_cloudflare_1015 actor_id=%s", interaction.user.id)
                falhas += max(0, total_users - (sucessos + bloqueados + falhas))
                break
            retry_after = float(getattr(e, "retry_after", 0) or 0)
            if retry_after > 0:
                log.warning("dm_broadcast_rate_limited user_id=%s retry_after=%s", user_id, retry_after)
                await asyncio.sleep(min(retry_after + 1, 60))

        except Exception as e:
            log.warning("dm_broadcast_user_failed user_id=%s error=%s", user_id, e)
            falhas += 1


        await asyncio.sleep(DM_BROADCAST_DELAY_SECONDS)


    embed_report = discord.Embed(title="📊 Relatório de Envio", color=discord.Color.green())
    embed_report.add_field(name="✅ Enviados", value=str(sucessos), inline=True)
    embed_report.add_field(name="🔒 DM Fechada/Bloqueado", value=str(bloqueados), inline=True)
    embed_report.add_field(name="⚠️ Falhas Gerais", value=str(falhas), inline=True)
    embed_report.add_field(name="👥 Total Tentado", value=str(total_users), inline=True)
    log.info(
        "dm_broadcast_finished actor_id=%s recipients=%s sent=%s blocked=%s failed=%s",
        interaction.user.id,
        total_users,
        sucessos,
        bloqueados,
        falhas,
    )

    try:
        await interaction.followup.send(embed=embed_report, ephemeral=True)
    except discord.HTTPException as e:
        log.warning("dm_broadcast_report_failed actor_id=%s status=%s", interaction.user.id, e.status)
