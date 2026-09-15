from __future__ import annotations
from ..cog import *


MAX_JOGO_LENGTH = 50
MAX_JOGAR_MESSAGE_LENGTH = 500


def _clean_field(value: str, max_length: int) -> str:
    cleaned = " ".join((value or "").strip().split())
    return cleaned[:max_length]


def _neutralize_mentions(value: str) -> str:
    return (
        value
        .replace("@everyone", "@\u200beveryone")
        .replace("@here", "@\u200bhere")
        .replace("<@&", "<@&\u200b")
        .replace("<@", "<@\u200b")
        .replace("<#", "<#\u200b")
    )


async def execute(self, it: discord.Interaction, jogo: str, mensagem: str):
    await it.response.defer(ephemeral=True)

    if not await ensure_guild_interaction(it, "o comando /jogar"):
        return

    if not await ensure_db_online(it, "o comando /jogar"):
        return

    role = it.guild.get_role(JOGAR_ROLE_ID) if it.guild else None
    if not role:
        return await it.followup.send("❌ Cargo de chamada para jogar não encontrado.", ephemeral=True)

    target_channel = it.guild.get_channel(JOGAR_CHANNEL_ID) if it.guild else None
    if target_channel is None:
        try:
            target_channel = await it.guild.fetch_channel(JOGAR_CHANNEL_ID)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            target_channel = None
    if target_channel is None or not hasattr(target_channel, "send"):
        return await it.followup.send("❌ Canal de chamadas para jogar não encontrado.", ephemeral=True)

    jogo = _clean_field(jogo, MAX_JOGO_LENGTH)
    mensagem = _clean_field(mensagem, MAX_JOGAR_MESSAGE_LENGTH)
    if not jogo:
        return await it.followup.send("❌ Informe o que você quer jogar.", ephemeral=True)
    if len(jogo) < 2:
        return await it.followup.send("❌ O nome do jogo precisa ter pelo menos 2 caracteres.", ephemeral=True)
    if not mensagem:
        return await it.followup.send("❌ Escreva uma mensagem para o chamado.", ephemeral=True)
    if len(mensagem) < 5:
        return await it.followup.send("❌ A mensagem precisa ter pelo menos 5 caracteres.", ephemeral=True)

    last_used = await self.get_jogar_last_used(it.user.id)
    if last_used:
        if last_used.tzinfo is None:
            last_used = last_used.replace(tzinfo=timezone.utc)
        available_at = int(last_used.timestamp() + JOGAR_COOLDOWN_SECONDS)
        if datetime.now(timezone.utc).timestamp() < available_at:
            return await it.followup.send(
                f"⏳ Você já chamou para jogar recentemente. Use novamente <t:{available_at}:R>.",
                ephemeral=True,
            )

    safe_jogo = _neutralize_mentions(jogo)
    safe_message = _neutralize_mentions(mensagem)
    embed = discord.Embed(
        title="<:controle:1512208193760268419> — Chamar para Jogar",
        description=(
            f"{it.user.mention} quer jogar **{safe_jogo}**.\n\n"
            f"> {safe_message}"
        ),
        color=discord.Color.from_rgb(255, 255, 255),
    )
    avatar_url = it.user.display_avatar.replace(size=128, format="png").url
    embed.set_author(name=f"{it.user.display_name} chamou para jogar", icon_url=avatar_url)
    embed.set_footer(text="Cooldown individual: 1 hora")

    try:
        await target_channel.send(
            content=role.mention,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=[role], users=False, everyone=False),
        )
    except discord.Forbidden:
        return await it.followup.send("❌ Não tenho permissão para enviar o chamado no canal de jogos.", ephemeral=True)
    except discord.HTTPException as e:
        log.error(f"Falha ao enviar chamado /jogar user_id={it.user.id}: {e}")
        return await it.followup.send("❌ Não consegui enviar o chamado agora. Tente novamente em instantes.", ephemeral=True)

    saved = await self.set_jogar_last_used(it.user.id)
    if not saved:
        log.warning("Chamado /jogar enviado sem persistir cooldown user_id=%s", it.user.id)

    await it.followup.send(f"✅ Chamado enviado em {target_channel.mention}.", ephemeral=True)
