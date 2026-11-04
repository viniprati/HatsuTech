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
        {"_id": "config", "active": True},
        [{"$set": {"active": False, "last_event_scores": {"$ifNull": ["$current_scores", {}]}}}],
        return_document=ReturnDocument.AFTER,
    )
    if not closed:
        return await it.edit_original_response(content="Não foi possível encerrar o evento; confira se há um evento ativo e tente novamente.")
    from cogs.engagement.profile_service import record_event_achievements

    await record_event_achievements(it.guild, closed.get("last_event_scores", {}), source="evento_encerrar")
    cache = getattr(self.bot, "event_cache", None)
    if isinstance(cache, dict):
        cache.pop(CHAT_COUNT_CHANNEL_ID, None)

    await it.edit_original_response(content="🏁 **Evento Encerrado!** Use `/topevento` para ver os vencedores finais.")
