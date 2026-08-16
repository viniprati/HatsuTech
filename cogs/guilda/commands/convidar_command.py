from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, usuario: discord.Member):
    guild_data = self.get_user_guild(it.user.id)

    if not guild_data:
        return await it.response.send_message("❌ Você não tem guilda.", ephemeral=True)

    if guild_data["leader_id"] != it.user.id:
        return await it.response.send_message("❌ Apenas o líder pode convidar.", ephemeral=True)

    active_members = await self.get_active_member_records(it.guild, guild_data)
    if len(active_members) >= 10:
        return await it.response.send_message("❌ Sua guilda já está cheia (Max 10).", ephemeral=True)

    if self.get_user_guild(usuario.id):
        return await it.response.send_message(f"❌ {usuario.display_name} já está em uma guilda.", ephemeral=True)

    if usuario.bot:
        return await it.response.send_message("🤖 Robôs não entram em guildas.", ephemeral=True)

    view = GuildInviteView(self, guild_data, usuario, it.user)
    await it.response.send_message(f"📨 Convite enviado para {usuario.mention}.", ephemeral=True)

    msg = await it.channel.send(
        content=f"{usuario.mention}, você foi convidado para entrar na guilda **{guild_data['name']}**!\nVocê tem 3 minutos para aceitar.",
        view=view
    )
    view.message = msg
