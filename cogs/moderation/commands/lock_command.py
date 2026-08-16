from __future__ import annotations
from ..cog import *


async def execute(self, it):
    await it.channel.set_permissions(it.guild.default_role, send_messages=False)
    await it.response.send_message("🔒 **Canal trancado com sucesso.**", ephemeral=True)
