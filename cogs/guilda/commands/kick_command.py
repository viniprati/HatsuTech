from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, membro: discord.Member):
    guild_data = self.get_user_guild(it.user.id)
    if not guild_data or guild_data["leader_id"] != it.user.id:
        return await it.response.send_message("❌ Apenas o líder pode kickar.", ephemeral=True)
    if membro.id == it.user.id:
        return await it.response.send_message("❌ Você não pode se kickar.", ephemeral=True)

    member_record = next((m for m in guild_data["members"] if m["user_id"] == membro.id), None)
    if not member_record:
        return await it.response.send_message("❌ Este usuário não está na sua guilda.", ephemeral=True)

    guilds_col.update_one(
        {"_id": guild_data["_id"]},
        {"$pull": {"members": {"user_id": membro.id}}}
    )
    await it.response.send_message(f"👢 **{membro.display_name}** foi removido da guilda.", ephemeral=True)
