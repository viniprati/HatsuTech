from __future__ import annotations
from ..cog import *


async def execute(self, it):
    await it.channel.set_permissions(it.guild.default_role, send_messages=None)
    await it.response.send_message("🔓 **Canal destrancado com sucesso.**", ephemeral=True)
