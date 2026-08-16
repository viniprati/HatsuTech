from __future__ import annotations
from ..cog import *


async def execute(self, it, duracao: str = None, canal: discord.TextChannel = None):
    end = None
    if duracao:
        m = re.fullmatch(r"(\d+)([smhd])", duracao.strip().lower())
        if not m:
            return await it.response.send_message("Duração inválida. Use formatos como `10m`, `2h` ou `1d`.", ephemeral=True)
        amount = int(m.group(1))
        if amount <= 0:
            return await it.response.send_message("A duração precisa ser maior que zero.", ephemeral=True)
        end = time.time() + (amount * {'s':1,'m':60,'h':3600,'d':86400}.get(m.group(2),1))

    event_doc = {
        "active": True,
        "end_time": end,
        "channel_id": CHAT_COUNT_CHANNEL_ID,
        "current_scores": {},
        "score_bonus_remainders": {},
    }


    await asyncio.to_thread(
        event_col.update_one,
        {"_id": "config"},
        {"$set": event_doc},
        upsert=True
    )
    cache = getattr(self.bot, "event_cache", None)
    if isinstance(cache, dict):
        cache[CHAT_COUNT_CHANNEL_ID] = {"_id": "config", **event_doc}

    msg = "🎉 **Evento Iniciado!**\nRegras: Mínimo 6 caracteres e sem spam."
    msg += f"\nCanal oficial: <#{CHAT_COUNT_CHANNEL_ID}>"
    if canal and canal.id != CHAT_COUNT_CHANNEL_ID:
        msg += "\nO canal escolhido foi ignorado porque a contagem está limitada ao canal oficial."
    await it.response.send_message(msg)
