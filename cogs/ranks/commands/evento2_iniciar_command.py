from __future__ import annotations
from ..cog import *


async def execute(self, it, canal: discord.TextChannel, duracao: str = None):
    if canal.id == CHAT_COUNT_CHANNEL_ID:
        return await it.response.send_message(
            "❌ O evento 2 precisa ficar em outro chat. Para o canal oficial, use `/evento_iniciar`.",
            ephemeral=True,
        )

    end = None
    if duracao:
        m = re.fullmatch(r"(\d+)([smhd])", duracao.strip().lower())
        if not m:
            return await it.response.send_message("Duração inválida. Use formatos como `10m`, `2h` ou `1d`.", ephemeral=True)
        amount = int(m.group(1))
        if amount <= 0:
            return await it.response.send_message("A duração precisa ser maior que zero.", ephemeral=True)
        end = time.time() + (amount * {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(m.group(2), 1))

    event_doc = {
        "active": True,
        "end_time": end,
        "channel_id": canal.id,
        "current_scores": {},
        "score_bonus_remainders": {},
    }

    await asyncio.to_thread(
        event_col.update_one,
        {"_id": "config2"},
        {"$set": event_doc},
        upsert=True,
    )
    cache = getattr(self.bot, "event_cache", None)
    if isinstance(cache, dict):
        cache[canal.id] = {"_id": "config2", **event_doc}

    msg = f"🎉 **Evento 2 Iniciado!**\nCanal: {canal.mention}\nRegras: Mínimo 6 caracteres e sem spam."
    if end:
        msg += f"\nEncerramento: <t:{int(end)}:R>"
    await it.response.send_message(msg)
