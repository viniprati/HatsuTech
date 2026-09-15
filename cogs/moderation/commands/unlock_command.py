from __future__ import annotations
from ..cog import *


async def execute(self, it):
    if not await ensure_guild_interaction(it, "o comando /unlock"):
        return
    if not isinstance(it.channel, discord.abc.GuildChannel):
        return await it.response.send_message("Use este comando em um canal do servidor.", ephemeral=True)
    await it.channel.set_permissions(it.guild.default_role, send_messages=None)
    await it.response.send_message("🔓 **Canal destrancado com sucesso.**", ephemeral=True)
