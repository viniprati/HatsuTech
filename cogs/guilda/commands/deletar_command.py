from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction):
    guild_data = self.get_user_guild(it.user.id)

    if not guild_data:
        return await it.response.send_message("❌ Você não tem guilda para deletar.", ephemeral=True)

    if guild_data["leader_id"] != it.user.id:
        return await it.response.send_message("❌ Apenas o líder pode deletar a guilda.", ephemeral=True)

    embed = discord.Embed(
        title="⚠️ ATENÇÃO!",
        description=f"Tem certeza que deseja apagar a guilda **{guild_data['name']}**?\nIsso removerá todos os membros e o XP acumulado.",
        color=discord.Color.red()
    )
    await it.response.send_message(embed=embed, view=GuildConfirmDelete(guild_data["_id"], it.user.id), ephemeral=True)
