from __future__ import annotations
from ..cog import *


async def execute(self, it: discord.Interaction, nome: str, emoji: str):
    nome = nome.strip()
    emoji = emoji.strip()
    if not nome or len(nome) > 20:
        return await it.response.send_message("❌ Nome muito longo (máx 20 chars).", ephemeral=True)
    if len(emoji) > 50:
        return await it.response.send_message("❌ Emoji inválido ou muito longo.", ephemeral=True)

    if self.get_user_guild(it.user.id):
        return await it.response.send_message("❌ Você já está em uma guilda! Saia primeiro.", ephemeral=True)

    if guilds_col.find_one({"name": nome}):
        return await it.response.send_message("❌ Já existe uma guilda com esse nome.", ephemeral=True)

    guild_doc = {
        "name": nome,
        "emoji": emoji,
        "leader_id": it.user.id,
        "created_at": datetime.datetime.now(),
        "total_xp": 0,
        "members": [
            {
                "user_id": it.user.id,
                "joined_at": datetime.datetime.now(),
                "xp": 0,
                "msg_count": 0,
                "voice_minutes": 0,
                "voice_seconds": 0,
                "message_xp": 0,
                "voice_xp": 0
            }
        ]
    }

    guilds_col.insert_one(guild_doc)
    await it.response.send_message(f"✅ Guilda **{emoji} {nome}** criada com sucesso!", ephemeral=True)
