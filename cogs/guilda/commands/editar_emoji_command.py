from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction):
    guild_data = self.get_user_guild(it.user.id)

    if not guild_data:
        return await it.response.send_message("❌ Você não está em uma guilda.", ephemeral=True)

    if guild_data["leader_id"] != it.user.id:
        return await it.response.send_message("❌ Apenas o líder pode editar o ícone.", ephemeral=True)

    view = GuildIconView(guild_data["_id"])

    embed = discord.Embed(
        title="🎨 Editar Ícone da Guilda",
        description=f"O ícone atual é: {guild_data['emoji']}\n\nEscolha um novo ícone na lista abaixo ou clique em **Personalizado**.",
        color=discord.Color.blue()
    )
    await it.response.send_message(embed=embed, view=view, ephemeral=True)
