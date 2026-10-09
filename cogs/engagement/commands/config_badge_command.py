from __future__ import annotations
from ..cog import *


async def execute(self, it, cargo: discord.Role, emoji: str, nome_da_funcao: str):
    try:
        new_text = f"{emoji} **{nome_da_funcao}**"
        str_id = str(cargo.id)
        result = await asyncio.to_thread(
            event_col.update_one,
            {"_id": "badges_config"},
            {"$set": {f"roles.{str_id}": new_text}},
            upsert=True
        )
        if not getattr(result, "acknowledged", False):
            return await it.response.send_message("Não consegui salvar a badge. Tente novamente.", ephemeral=True)
        self.badges_cache[str_id] = new_text
        await it.response.send_message(f"✅ Badge salva para {cargo.mention}: {new_text}", ephemeral=True)
    except Exception as e:
        log.error(f"Erro em config_badge: {e}")
        await it.response.send_message("❌ Falha crítica ao persistir dados no banco.", ephemeral=True)
