from __future__ import annotations
from ..cog import *


async def execute(self, it):
    data = await asyncio.to_thread(event_col.find_one, {"_id": "config2"})
    if not data or not data.get("active"):
        return await it.response.send_message("❌ Nenhum evento 2 ativo no momento.")

    await asyncio.to_thread(
        event_col.update_one,
        {"_id": "config2"},
        {"$set": {"active": False, "last_event_scores": data.get("current_scores", {})}},
    )
    cache = getattr(self.bot, "event_cache", None)
    if isinstance(cache, dict) and data.get("channel_id"):
        cache.pop(int(data["channel_id"]), None)

    await it.response.send_message("🏁 **Evento 2 Encerrado!** Use `/topevento2` para ver os vencedores finais.")
