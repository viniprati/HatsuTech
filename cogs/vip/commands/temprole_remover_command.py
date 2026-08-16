from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, usuario: discord.Member, cargo: discord.Role):
    await it.response.defer(ephemeral=True)
    if not await ensure_db_online(it, "o comando /temprole_remover"):
        return
    query = {
        "user_id": str(usuario.id),
        "guild_id": str(it.guild.id),
        "role_id": str(cargo.id),
    }
    exists = await asyncio.to_thread(temp_col.find_one, query)
    if not exists:
        return await it.followup.send(
            "Nao existe temprole ativo para este usuario/cargo.",
            ephemeral=True
        )

    view = TempRoleAdjustView(it.user.id, usuario, cargo)
    embed = await view.build_embed()
    await it.followup.send(embed=embed, view=view, ephemeral=True)
