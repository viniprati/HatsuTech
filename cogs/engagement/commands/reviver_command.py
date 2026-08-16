from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, imagem: discord.Attachment = None):
    if REVIVER_ROLE_ID == 0:
        return await it.response.send_message("❌ **Atenção Administrador:** A constante `REVIVER_ROLE_ID` precisa ser configurada.", ephemeral=True)

    try:
        history = await self.get_reviver_history()
        cor_painel = discord.Color.from_rgb(43, 228, 172)

        embed = discord.Embed(
            title="✨ Central de Engajamento",
            description="Use este painel para enviar uma chamada no chat. Defina a mensagem antes de enviar.",
            color=cor_painel
        )

        icon_url = it.guild.icon.url if it.guild.icon else self.bot.user.display_avatar.url
        embed.set_thumbnail(url=icon_url)

        if imagem:
            if not imagem.content_type or not imagem.content_type.startswith('image/'):
                return await it.response.send_message("❌ O arquivo selecionado não parece ser uma imagem válida.", ephemeral=True)
            embed.set_image(url=imagem.url)

        status_emoji = "🟢"
        status_texto = "**Pronto para uso.** Aguardando mensagem."

        if history:
            last_entry = history[0]
            dt_utc = last_entry['timestamp']
            if dt_utc.tzinfo is None: dt_utc = dt_utc.replace(tzinfo=timezone.utc)

            diff = datetime.now(timezone.utc) - dt_utc
            if diff.total_seconds() < (REVIVER_COOLDOWN_MINUTES * 60):
                remaining = int(dt_utc.timestamp() + (REVIVER_COOLDOWN_MINUTES * 60))
                status_emoji = "🔴"
                status_texto = f"**Cooldown ativo.** Disponível <t:{remaining}:R>."

            dt_brt = dt_utc.astimezone(FUSO_BRT)
            data_escrita = dt_brt.strftime("%d/%m/%Y às %H:%M")
            timestamp_unix = int(dt_utc.timestamp())
            last_user = f"<@{last_entry['user_id']}>"

            embed.add_field(
                name="🕒 Último envio",
                value=f"> Responsável: {last_user}\n> Horário: **<t:{timestamp_unix}:R>** (`{data_escrita}`)",
                inline=False
            )
        else:
            embed.add_field(name="🕒 Último envio", value="> *Nenhum envio registrado ainda.*", inline=False)

        embed.add_field(
            name="📝 Pré-visualização da mensagem",
            value="> ⚠️ *Mensagem ainda não definida.\n> Use **'✏️ Editar Mensagem'** antes de enviar.*",
            inline=False
        )

        embed.add_field(name=f"{status_emoji} Status", value=status_texto, inline=False)
        embed.set_footer(text=f"Solicitado por {it.user.display_name}", icon_url=it.user.display_avatar.url)

        view = ReviverView(self, REVIVER_ROLE_ID, imagem)
        await it.response.send_message(embed=embed, view=view, ephemeral=True)

    except discord.errors.DiscordServerError:
        log.warning("Ocorreu uma lentidão nos servidores do Discord ao invocar o painel.")
        await it.response.send_message("❌ O Discord está instável no momento. Tente de novo em alguns segundos.", ephemeral=True)
    except Exception as e:
        log.error(f"Erro ao iniciar painel do reviver: {e}")
        if not it.response.is_done():
            await it.response.send_message("❌ Ocorreu um erro interno.", ephemeral=True)
