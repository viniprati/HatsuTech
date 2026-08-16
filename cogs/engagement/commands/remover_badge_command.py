from __future__ import annotations
from ..cog import *


async def execute(self, it, cargo: discord.Role):
    try:
        str_id = str(cargo.id)
        if str_id in self.badges_cache:
            del self.badges_cache[str_id]
            await asyncio.to_thread(
                event_col.update_one,
                {"_id": "badges_config"},
                {"$unset": {f"roles.{str_id}": ""}}
            )
            await it.response.send_message(f"🗑️ Remoção efetuada do cargo {cargo.mention}.", ephemeral=True)
        else:
            await it.response.send_message("❌ Cargo não possui dados registrados.", ephemeral=True)
    except Exception as e:
        log.error(f"Erro em remover_badge: {e}")
        await it.response.send_message("❌ Erro ao deletar registro.", ephemeral=True)
