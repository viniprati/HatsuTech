from __future__ import annotations
from ..cog import *


async def execute(self, it, cargo: discord.Role):
    try:
        str_id = str(cargo.id)
        if str_id in self.badges_cache:
            result = await asyncio.to_thread(
                event_col.update_one,
                {"_id": "badges_config"},
                {"$unset": {f"roles.{str_id}": ""}}
            )
            if not getattr(result, "acknowledged", False) or not result.matched_count:
                return await it.response.send_message("Não consegui remover a badge do banco. Tente novamente.", ephemeral=True)
            del self.badges_cache[str_id]
            await it.response.send_message(f"🗑️ Badge removida do cargo {cargo.mention}.", ephemeral=True)
        else:
            await it.response.send_message("❌ Cargo não possui dados registrados.", ephemeral=True)
    except Exception as e:
        log.error(f"Erro em remover_badge: {e}")
        await it.response.send_message("❌ Erro ao deletar registro.", ephemeral=True)
