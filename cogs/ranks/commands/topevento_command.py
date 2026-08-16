from __future__ import annotations
from ..cog import *


async def execute(self, it):
    data = await asyncio.to_thread(event_col.find_one, {"_id": "config"}) or {}
    active = data.get("active", False)
    raw_scores = data.get("current_scores" if active else "last_event_scores", {})
    sc = {user_id: int(float(score or 0)) for user_id, score in raw_scores.items()}

    if not sc:
        return await it.response.send_message("📭 Sem dados de evento registrados.")

    sorted_sc = sorted(sc.items(), key=lambda x:x[1], reverse=True)[:10]
    desc = "".join([f"**{i}.** <@{u}> — `{fmt_rank_score(q)} pts`\n" for i,(u,q) in enumerate(sorted_sc,1)])

    status = "🟢 (Em Andamento)" if active else "🔴 (Encerrado)"
    await it.response.send_message(embed=discord.Embed(title=f"Rank Evento {status}", description=desc, color=discord.Color.gold()))
