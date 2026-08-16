from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, novo_nome: str):
    novo_nome = novo_nome.strip()
    guild_data = self.get_user_guild(it.user.id)
    if not guild_data or guild_data["leader_id"] != it.user.id:
        return await it.response.send_message("❌ Apenas o líder pode editar.", ephemeral=True)

    if not novo_nome or len(novo_nome) > 20:
        return await it.response.send_message("Nome muito longo.", ephemeral=True)
    existing = guilds_col.find_one({"name": novo_nome})
    if existing and existing["_id"] != guild_data["_id"]:
        return await it.response.send_message("❌ Já existe uma guilda com esse nome.", ephemeral=True)

    guilds_col.update_one({"_id": guild_data["_id"]}, {"$set": {"name": novo_nome}})
    await it.response.send_message(f"✅ Nome da guilda alterado para **{novo_nome}**!", ephemeral=True)
