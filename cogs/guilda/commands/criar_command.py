from __future__ import annotations

import asyncio
import discord

from database import TransactionUnavailable
from utils import ensure_guild_interaction
from ..finance import create_guild, GuildFinanceError


async def execute(self, it: discord.Interaction, nome: str, emoji: str):
    if not await ensure_guild_interaction(it, "o comando /guilda criar"):
        return
    await it.response.defer(ephemeral=True)
    try:
        await asyncio.to_thread(create_guild, it.guild.id, it.user.id, nome, emoji, f"create:{it.id}")
    except (GuildFinanceError, TransactionUnavailable) as error:
        return await it.followup.send(str(error), ephemeral=True)
    await it.followup.send(
        f"✅ Guilda **{discord.utils.escape_markdown(emoji.strip())} {discord.utils.escape_markdown(nome.strip())}** criada! "
        "Taxa de **4.000 Essências** descontada. O bônus de guilda será acumulado no cofre.",
        ephemeral=True, allowed_mentions=discord.AllowedMentions.none(),
    )
