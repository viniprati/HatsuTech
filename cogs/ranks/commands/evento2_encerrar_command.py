from __future__ import annotations
from ..cog import *
from pymongo import ReturnDocument
from utils import ensure_db_online


async def execute(self, it):
    if not await ensure_db_online(it):
        return
    await it.response.defer(ephemeral=True)
    closed = await asyncio.to_thread(
        event_col.find_one_and_update,
        {"_id": "config2", "active": True},
        [{"$set": {"active": False, "last_event_scores": {"$ifNull": ["$current_scores", {}]}}}],
        return_document=ReturnDocument.AFTER,
    )
    if not closed:
        return await it.edit_original_response(content="Não foi possível encerrar o evento 2; confira se há um evento ativo e tente novamente.")
    from cogs.engagement.profile_service import record_event_achievements

    await record_event_achievements(it.guild, closed.get("last_event_scores", {}), source="evento2_encerrar")
    cache = getattr(self.bot, "event_cache", None)
    if isinstance(cache, dict) and closed.get("channel_id"):
        cache.pop(int(closed["channel_id"]), None)

    await it.edit_original_response(content="🏁 **Evento 2 Encerrado!** Use `/topevento2` para ver os vencedores finais.")
