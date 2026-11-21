from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction):
    guild_data = self.get_user_guild(it.user.id)
    if not guild_data:
        return await it.response.send_message("❌ Você não está em uma guilda.", ephemeral=True)

    if guild_data["leader_id"] == it.user.id:
        return await it.response.send_message("❌ O líder não pode sair. Use `/guilda deletar` ou passe a liderança.", ephemeral=True)

    user_ids = [it.user.id, str(it.user.id)]
    result = await asyncio.to_thread(
        guilds_col.update_one,
        {"_id": guild_data["_id"], "leader_id": {"$nin": user_ids}, "members.user_id": {"$in": user_ids}},
        {"$pull": {"members": {"user_id": {"$in": user_ids}}}},
    )
    if not result.acknowledged or not result.modified_count:
        return await it.response.send_message("Não consegui confirmar sua saída. Confira a liderança e tente novamente.", ephemeral=True)

    await it.response.send_message(f"👋 Você saiu da guilda **{guild_data['name']}**.", ephemeral=True)
