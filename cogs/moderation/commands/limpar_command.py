from __future__ import annotations
from ..cog import *


async def execute(self, it, quantidade: int):
    await it.response.defer(ephemeral=True)
    if not await ensure_guild_interaction(it, "o comando /limpar"):
        return
    if not hasattr(it.channel, "purge"):
        return await it.followup.send("Use este comando em um canal de texto do servidor.", ephemeral=True)
    if quantidade < 1 or quantidade > 100:
        return await it.followup.send("Informe uma quantidade entre 1 e 100 mensagens.", ephemeral=True)
    try:
        deleted = await it.channel.purge(limit=quantidade)
        await it.followup.send(f"🧹 **Limpeza concluída!** {len(deleted)} mensagens removidas.", ephemeral=True)
    except discord.Forbidden:
        await it.followup.send("❌ Não tenho permissão para apagar mensagens neste canal.", ephemeral=True)
    except discord.HTTPException:
        await it.followup.send("❌ Não foi possível apagar as mensagens agora.", ephemeral=True)
