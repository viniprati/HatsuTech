from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction):
    guild_data = self.get_user_guild(it.user.id)
    if not guild_data:
        return await it.response.send_message("❌ Você não está em uma guilda.", ephemeral=True)

    if guild_data["leader_id"] == it.user.id:
        return await it.response.send_message("❌ O líder não pode sair. Use `/guilda deletar` ou passe a liderança.", ephemeral=True)

    guilds_col.update_one(
        {"_id": guild_data["_id"]},
        {"$pull": {"members": {"user_id": it.user.id}}}
    )

    await it.response.send_message(f"👋 Você saiu da guilda **{guild_data['name']}**.", ephemeral=True)
