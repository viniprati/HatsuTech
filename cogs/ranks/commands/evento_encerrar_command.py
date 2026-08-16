from __future__ import annotations
from ..cog import *


async def execute(self, it):
    data = await asyncio.to_thread(event_col.find_one, {"_id": "config"})
    if not data or not data.get("active"):
        return await it.response.send_message("❌ Nenhum evento ativo no momento.")

    await asyncio.to_thread(
        event_col.update_one,
        {"_id": "config"},
        {"$set": {"active": False, "last_event_scores": data.get("current_scores", {})}}
    )
    cache = getattr(self.bot, "event_cache", None)
    if isinstance(cache, dict):
        cache.pop(CHAT_COUNT_CHANNEL_ID, None)

    await it.response.send_message("🏁 **Evento Encerrado!** Use `/topevento` para ver os vencedores finais.")
